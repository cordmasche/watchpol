# WatchPol — Incident Map Logger (PostgreSQL)

A small Flask app for reporting incidents on a map. Data is stored in PostgreSQL.
The interface is in German and follows the WatchPol palette (black, yellow, magenta).
There are two modes:

- **Input mode** (`/input`): click the map to place an incident and fill in the form.
- **View mode** (`/view`): see incidents on the map and in a table. You can search them
  (text, type, verified, simulated, date range, current map area) or run read-only SQL.
  Any result with `lat`/`lon` columns is drawn on the map. Results can be downloaded as CSV.

The stack is Flask, PostgreSQL (psycopg 3 with a connection pool) and Leaflet with
OpenStreetMap tiles. There is no build step and no ORM.

## Quick start (local)

**1. Start PostgreSQL.** Pick one option.

- With Docker (easiest): `docker compose up -d`.
  This starts Postgres 16 and runs `database/setup.sql` once.
- With Homebrew:
  ```bash
  brew install postgresql@16
  brew services start postgresql@16
  psql -d postgres -f database/setup.sql
  ```

**2. Run the app.**

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                 # the defaults match setup.sql
flask --app app seed --n 50          # optional: fake events, all flagged simulated=yes
flask --app app run --debug          # http://127.0.0.1:5000
python -m pytest -q                  # tests (use the separate incidents_test DB)
```

The app creates the `events` table on start. `flask --app app init-db` does the same by hand.

`setup.sql` creates these roles and databases:

| name | what it is |
|---|---|
| `incident` | owner role; the app writes with it |
| `incident_reader` | read-only role for the SQL console |
| `incidents` | main database |
| `incidents_test` | database for the test suite |

The passwords in `setup.sql` are for local development only.

## Opening the database without the app

- **Terminal:** `psql postgresql://incident:incident@localhost:5432/incidents`, then run
  `\d events` or `SELECT ...`.
- **GUI:** DBeaver, TablePlus, pgAdmin or Postico. Connect to host `localhost`, port `5432`,
  database `incidents`. Use `incident_reader` if you only want to look.
- **R:** `DBI::dbConnect(RPostgres::Postgres(), dbname="incidents", host="localhost", user="incident_reader", password="reader")`
- **Python:** `pandas.read_sql("SELECT * FROM events", "postgresql+psycopg://...")`
- **CSV export:** `psql ... -c "\copy events TO 'events.csv' CSV HEADER"`

## Changing the event variables

Edit **`schema.py`**:

- `EVENT_TYPES` holds the categories. Each has a `value` (stored in the database, e.g.
  `festnahme`), a `label` (shown to people, e.g. "Festnahme") and a `color` (map and list).
- `FIELDS` holds the other variables: `reporter_role`, `taken_into_custody` and the
  placeholders `var_1`…`var_6`. Rename them, relabel them, add or remove them. Field names
  must be lowercase. `select` options also take `value`/`label` pairs. Fields with
  `"group": "extra"` appear under "Weitere Angaben" in the form.
- In the form, yes/no fields and selects with up to four options are shown as buttons.

The form, validation, search and column list all update from this file. Columns for new fields
are added on the next start (`ADD COLUMN IF NOT EXISTS`). If you rename or remove a field, its
old column is left alone. To actually rename a column, run
`ALTER TABLE events RENAME COLUMN var_1 TO title;` and change `schema.py` to match.

| field type | PostgreSQL type |
|---|---|
| `text`, `textarea`, `select` | `TEXT` |
| `number` | `DOUBLE PRECISION` |
| `integer` | `BIGINT` |
| `boolean` | `BOOLEAN` |
| `date` | `DATE` |
| `datetime` | `TIMESTAMP` |

These core columns are always present:

| column | type | meaning |
|---|---|---|
| `event_id` | `BIGINT` identity | auto-assigned |
| `event_type` | `TEXT` | one of `EVENT_TYPES` |
| `verified` | `BOOLEAN` | yes/no |
| `simulated` | `BOOLEAN` | yes/no |
| `lat`, `lon` | `DOUBLE PRECISION` | WGS84 coordinates from the map |
| `reported_at` | `TIMESTAMPTZ` | set by the server, UTC |

## Access via link

If `INPUT_KEY` and `VIEW_KEY` are left empty, everything is open (fine for local work). If you
set them, access works through the link:

- `https://your-host/input?key=<INPUT_KEY>` can report incidents only.
- `https://your-host/view?key=<VIEW_KEY>` can report, view, search and run SQL.

The key is saved in a session cookie and then removed from the URL.

## SQL console safety

The console has four independent layers of protection:

1. It connects as `incident_reader`. That role only has `SELECT` on `events`, and its
   transactions are read-only by default.
2. Each query runs in a `READ ONLY` transaction that is always rolled back.
3. Queries are sent as prepared statements, so PostgreSQL rejects stacked statements such as
   `SELECT 1; DELETE …`.
4. `statement_timeout` (`SQL_TIMEOUT_MS`) stops long queries, and results are capped at
   `SQL_MAX_ROWS`.

If `DATABASE_URL_READONLY` is empty, layers 2–4 still apply and the app logs a warning.
On a server, always use the reader role.

## API

| method | path | role |
|---|---|---|
| POST | `/api/events` (JSON) | input |
| GET | `/api/events?q=&event_type=&verified=yes&simulated=no&date_from=&date_to=&bbox=w,s,e,n&limit=` | view |
| GET | `/api/events/<id>` | view |
| GET | `/api/events.geojson?…same filters…` | view |
| POST | `/api/sql` `{"sql": "SELECT …"}` | view |

## Deploying to a server

1. Get a PostgreSQL database. It can be managed (Hetzner, Aiven, Neon, a university instance)
   or run on the same server. Run `database/setup.sql` with **new passwords**. On a managed
   database, create the two roles through the provider's tools if you aren't a superuser.
2. Copy the project and run `pip install -r requirements.txt`.
3. Create a `.env` with a long random `SECRET_KEY`, both access keys, and both database URLs.
   Add `?sslmode=require` to the URLs if the database is on another machine.
4. Run it with `gunicorn -w 3 -b 127.0.0.1:8000 'app:create_app()'` behind nginx or Caddy
   with HTTPS. Each worker opens up to `DB_POOL_MAX` connections, so keep
   workers × `DB_POOL_MAX` below the database's connection limit.
5. For backups, run `pg_dump -Fc incidents > backup-$(date +%F).dump` every day.
   Restore with `pg_restore`. Managed databases usually back up automatically.

**Moving to PostGIS later:** run `CREATE EXTENSION postgis;` and add a generated
`geom geography(Point,4326)` column from `lon`/`lat`. That enables spatial queries such as
"within 500 m of X" in the SQL console.

**Look of the map:** the map uses normal OpenStreetMap tiles, darkened with a CSS filter
(`.leaflet-tile-pane` in `static/app.css`). If you switch `TILE_URL` to tiles that are already
dark, remove that filter. Leaflet and the heatmap plugin are bundled in `static/vendor/`, so
browsers only contact your server and the tile server.

**Tiles:** the public OpenStreetMap tile server is for light use only
([policy](https://operations.osmfoundation.org/policies/tiles/)). Set `TILE_URL` to use
another provider.

## Files

```
app.py              routes, access control, JSON, CLI (init-db, seed)
schema.py           ← event types + placeholder variables
db.py               schema migration, connection pool, read-only SQL runner
events.py           validation, insert, search
config.py           settings (env / .env)
database/setup.sql  roles + databases (run once)
docker-compose.yml  local PostgreSQL
templates/, static/ frontend; static/vendor/ holds Leaflet + Leaflet.heat, static/logo.jpg the logo
tests/              pytest suite (needs incidents_test DB)
```
