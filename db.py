"""PostgreSQL access: schema creation/migration, connection pool, read-only SQL console."""
import logging
import re

import psycopg
from flask import current_app
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from schema import FIELDS

log = logging.getLogger(__name__)

PG_TYPES = {
    "text": "TEXT", "textarea": "TEXT", "select": "TEXT",
    "date": "DATE", "datetime": "TIMESTAMP",
    "number": "DOUBLE PRECISION", "integer": "BIGINT", "boolean": "BOOLEAN",
}
IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")  # lowercase: no quoting surprises in the SQL console
CORE_COLUMNS = ["event_id", "event_type", "verified", "simulated", "lat", "lon", "reported_at"]
CONN_KWARGS = {"options": "-c timezone=UTC", "connect_timeout": 5}

DDL = """
CREATE TABLE IF NOT EXISTS events (
    event_id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_type  TEXT             NOT NULL,
    verified    BOOLEAN          NOT NULL DEFAULT FALSE,
    simulated   BOOLEAN          NOT NULL DEFAULT FALSE,
    lat         DOUBLE PRECISION NOT NULL CHECK (lat BETWEEN -90 AND 90),
    lon         DOUBLE PRECISION NOT NULL CHECK (lon BETWEEN -180 AND 180),
    reported_at TIMESTAMPTZ      NOT NULL DEFAULT date_trunc('second', now())
)"""


def _check_fields():
    seen = set(CORE_COLUMNS)
    for f in FIELDS:
        name = f["name"]
        if not IDENT.match(name):
            raise ValueError(f"Invalid field name {name!r} (lowercase letters, digits, underscore)")
        if name in seen:
            raise ValueError(f"Duplicate/reserved field name {name!r}")
        if f["type"] not in PG_TYPES:
            raise ValueError(f"Unknown type {f['type']!r} for field {name!r}")
        seen.add(name)


def init_db(url, readonly_url=None):
    """Create the table if missing, add columns for new placeholder fields,
    and grant the read-only role SELECT. Safe to run from several workers at once."""
    _check_fields()
    with psycopg.connect(url, **CONN_KWARGS) as con:
        con.execute("SELECT pg_advisory_xact_lock(724061)")  # serialise concurrent starts
        con.execute(DDL)
        for f in FIELDS:
            con.execute(sql.SQL("ALTER TABLE events ADD COLUMN IF NOT EXISTS {} {}").format(
                sql.Identifier(f["name"]), sql.SQL(PG_TYPES[f["type"]])))
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events (event_type)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_time ON events (reported_at)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_latlon ON events (lat, lon)")

        reader = conninfo_to_dict(readonly_url).get("user") if readonly_url else None
        if reader:
            if con.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (reader,)).fetchone():
                con.execute(sql.SQL("GRANT SELECT ON events TO {}").format(sql.Identifier(reader)))
            else:
                log.warning("Read-only role %r not found - run database/setup.sql", reader)
        # leaving the with-block commits


def create_pool(url, max_size):
    return ConnectionPool(url, min_size=1, max_size=max_size, open=True,
                          kwargs={**CONN_KWARGS, "row_factory": dict_row})


def connection():
    """Borrow a pooled connection: `with connection() as con:` commits on success,
    rolls back on error, and returns the connection to the pool."""
    return current_app.extensions["db_pool"].connection()


def table_columns():
    with connection() as con:
        rows = con.execute("""
            SELECT column_name AS name, data_type AS type
            FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = 'events'
            ORDER BY ordinal_position""").fetchall()
    return rows


# --- SQL console -----------------------------------------------------------

def run_readonly_sql(query, max_rows, timeout_ms):
    """Run ONE statement in a read-only, time-limited transaction that is always rolled back.

    Protection layers:
      1. connects as the read-only role (DATABASE_URL_READONLY) which has only SELECT
         and default_transaction_read_only = on
      2. the transaction itself is READ ONLY and rolled back afterwards
      3. prepare=True makes the server reject multiple statements ("SELECT 1; DELETE ...")
      4. statement_timeout aborts long queries; rows are capped at max_rows
    """
    url = current_app.config["DATABASE_URL_READONLY"]
    if not url:
        log.warning("DATABASE_URL_READONLY not set - SQL console uses the owner role")
        url = current_app.config["DATABASE_URL"]
    with psycopg.connect(url, **CONN_KWARGS) as con:
        con.read_only = True
        with con.transaction(force_rollback=True):
            con.execute("SELECT set_config('statement_timeout', %s, true)", (str(timeout_ms),))
            cur = con.cursor()
            cur.execute(query, prepare=True)
            if cur.description is None:
                return [], [], False
            columns = [d.name for d in cur.description]
            rows = cur.fetchmany(max_rows + 1)
    truncated = len(rows) > max_rows
    return columns, [list(r) for r in rows[:max_rows]], truncated
