"""Map incident logger — Flask entry point.

Run locally:   flask --app app run --debug
"""
import atexit
import hmac
import random
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from functools import wraps

import click
import psycopg
from flask import (Flask, current_app, jsonify, redirect, render_template, request,
                   session, url_for)
from flask.json.provider import DefaultJSONProvider

import db
import events
from config import Config
from schema import EVENT_TYPE_VALUES, EVENT_TYPES, FIELDS, option_values

ROLE_RANK = {None: 0, "input": 1, "view": 2}


# --- access control (secret links) -----------------------------------------

def current_role():
    cfg = current_app.config
    roles = [session.get("role")]
    if not cfg["INPUT_KEY"]:
        roles.append("input")  # no input key configured -> input is open
    if not cfg["VIEW_KEY"]:
        roles.append("view")   # no view key configured -> everything is open
    return max(roles, key=ROLE_RANK.get)


def requires(role):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if ROLE_RANK[current_role()] < ROLE_RANK[role]:
                if request.path.startswith("/api/"):
                    return jsonify(error="forbidden: this link does not grant access"), 403
                return render_template("denied.html"), 403
            return fn(*args, **kwargs)
        return wrapper
    return deco


def _accept_key_from_url():
    """?key=... in any URL stores the role in a session cookie, then strips the key."""
    key = request.args.get("key")
    if key is None or request.endpoint == "static":
        return None
    for role, cfg_name in (("view", "VIEW_KEY"), ("input", "INPUT_KEY")):
        expected = current_app.config[cfg_name]
        if expected and hmac.compare_digest(key.encode(), expected.encode()):
            session["role"] = role
            session.permanent = True
            break
    args = {k: v for k, v in request.args.items() if k != "key"}
    return redirect(url_for(request.endpoint, **(request.view_args or {}), **args))


# --- JSON: ISO dates, numbers for NUMERIC, str() for other Postgres types ------

class JSONProvider(DefaultJSONProvider):
    @staticmethod
    def default(o):
        if isinstance(o, (datetime, date, time)):
            return o.isoformat()
        if isinstance(o, Decimal):
            return float(o)
        try:
            return DefaultJSONProvider.default(o)
        except TypeError:
            return str(o)  # intervals, ranges, etc. from the SQL console


# --- app factory -----------------------------------------------------------

def create_app(overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    app.json = JSONProvider(app)

    try:
        db.init_db(app.config["DATABASE_URL"], app.config["DATABASE_URL_READONLY"])
    except psycopg.OperationalError as e:
        raise SystemExit(f"Cannot reach PostgreSQL at DATABASE_URL ({e}).\n"
                         "Is it running? Local dev: `docker compose up -d` - see README.") from e
    pool = db.create_pool(app.config["DATABASE_URL"], app.config["DB_POOL_MAX"])
    app.extensions["db_pool"] = pool
    atexit.register(pool.close)
    app.before_request(_accept_key_from_url)

    def page_config():
        return {
            "fields": FIELDS,
            "eventTypes": EVENT_TYPES,
            "mapCenter": app.config["MAP_CENTER"],
            "mapZoom": app.config["MAP_ZOOM"],
            "tileUrl": app.config["TILE_URL"],
            "tileAttribution": app.config["TILE_ATTRIBUTION"],
            "sqlMaxRows": app.config["SQL_MAX_ROWS"],
        }

    @app.context_processor
    def inject_role():
        return {"role": current_role()}

    # ---- pages ----
    @app.get("/")
    def index():
        return redirect(url_for("view_page" if current_role() == "view" else "input_page"))

    @app.get("/input")
    @requires("input")
    def input_page():
        return render_template("input.html", cfg=page_config())

    @app.get("/view")
    @requires("view")
    def view_page():
        cfg = page_config()
        cfg["columns"] = db.table_columns()
        return render_template("view.html", cfg=cfg)

    # ---- API ----
    @app.post("/api/events")
    @requires("input")
    def create_event():
        payload = request.get_json(silent=True) or request.form.to_dict()
        try:
            event = events.insert_event(payload)
        except events.ValidationError as e:
            return jsonify(error="validation failed", fields=e.errors), 400
        return jsonify(event), 201

    @app.get("/api/events")
    @requires("view")
    def list_events():
        rows = events.search_events(request.args, app.config["SQL_MAX_ROWS"])
        return jsonify(events=rows, count=len(rows))

    @app.get("/api/events/<int:event_id>")
    @requires("view")
    def get_event(event_id):
        event = events.get_event(event_id)
        return (jsonify(event), 200) if event else (jsonify(error="not found"), 404)

    @app.get("/api/events.geojson")
    @requires("view")
    def events_geojson():
        rows = events.search_events(request.args, app.config["SQL_MAX_ROWS"])
        return jsonify(type="FeatureCollection", features=[{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
            "properties": r,
        } for r in rows])

    @app.get("/api/stats")
    @requires("view")
    def stats():
        with db.connection() as con:
            row = con.execute("""
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE reported_at > now() - interval '24 hours') AS last_24h,
                       COUNT(*) FILTER (WHERE verified) AS verified
                FROM events""").fetchone()
        return jsonify(row)

    @app.post("/api/sql")
    @requires("view")
    def sql_query():
        sql = ((request.get_json(silent=True) or {}).get("sql") or "").strip()
        if not sql:
            return jsonify(error="empty query"), 400
        try:
            cols, rows, truncated = db.run_readonly_sql(
                sql, app.config["SQL_MAX_ROWS"], app.config["SQL_TIMEOUT_MS"])
        except psycopg.errors.QueryCanceled:
            return jsonify(error=f"query exceeded {app.config['SQL_TIMEOUT_MS']} ms"), 400
        except (psycopg.errors.ReadOnlySqlTransaction, psycopg.errors.InsufficientPrivilege):
            return jsonify(error="only read-only SELECT queries on the events table are allowed"), 400
        except psycopg.errors.SyntaxError as e:
            msg = str(e).split("\n")[0]
            if "multiple commands" in msg:
                msg = "only one statement per query"
            return jsonify(error=msg), 400
        except psycopg.OperationalError as e:
            return jsonify(error=f"could not connect for SQL console: {e}"), 503
        except psycopg.Error as e:
            return jsonify(error=str(e).split("\n")[0]), 400
        return jsonify(columns=cols, rows=rows, truncated=truncated)

    # ---- CLI ----
    @app.cli.command("init-db")
    def init_db_cmd():
        """Create/migrate the database schema."""
        db.init_db(app.config["DATABASE_URL"], app.config["DATABASE_URL_READONLY"])
        click.echo("Database schema is up to date.")

    @app.cli.command("seed")
    @click.option("--n", default=50, help="Number of fake events")
    def seed_cmd(n):
        """Insert fake events (all flagged simulated=yes) around the map centre."""
        lat0, lon0 = app.config["MAP_CENTER"]
        now = datetime.now(timezone.utc)
        for _ in range(n):
            payload = {
                "event_type": random.choice(EVENT_TYPE_VALUES),
                "verified": random.choice(["yes", "no"]),
                "simulated": "yes",
                "lat": round(lat0 + random.uniform(-0.08, 0.08), 6),
                "lon": round(lon0 + random.uniform(-0.12, 0.12), 6),
            }
            for f in FIELDS:
                t = f["type"]
                payload[f["name"]] = {
                    "select": lambda: random.choice(option_values(f.get("options", [""]))),
                    "number": lambda: round(random.uniform(0, 100), 1),
                    "integer": lambda: random.randint(0, 100),
                    "boolean": lambda: random.choice(["yes", "no"]),
                    "date": lambda: (now - timedelta(days=random.randint(0, 60))).date().isoformat(),
                    "datetime": lambda: (now - timedelta(hours=random.randint(0, 1440)))
                                        .replace(tzinfo=None).isoformat(timespec="minutes"),
                }.get(t, lambda: f"sample {f['name']} {random.randint(1, 999)}")()
            events.insert_event(payload)
        click.echo(f"Inserted {n} simulated events.")

    return app


# `flask --app app ...` finds create_app() automatically.
# Production: gunicorn 'app:create_app()'
if __name__ == "__main__":
    create_app().run(debug=True)
