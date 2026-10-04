import os

try:  # optional: read settings from a .env file
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-change-me")

    # Main connection (owner role: creates tables, inserts events)
    DATABASE_URL = os.environ.get(
        "DATABASE_URL", "postgresql://incident:incident@localhost:5432/incidents")
    # Read-only role for the SQL console. Strongly recommended; see database/setup.sql.
    DATABASE_URL_READONLY = os.environ.get(
        "DATABASE_URL_READONLY", "postgresql://incident_reader:reader@localhost:5432/incidents") or None
    DB_POOL_MAX = int(os.environ.get("DB_POOL_MAX", 10))

    # Link-based access. Leave empty for open local development.
    #   INPUT_KEY -> link can report incidents:        https://host/input?key=...
    #   VIEW_KEY  -> link can report + view + query:   https://host/view?key=...
    INPUT_KEY = os.environ.get("INPUT_KEY") or None
    VIEW_KEY = os.environ.get("VIEW_KEY") or None

    # Guards for the SQL console
    SQL_MAX_ROWS = int(os.environ.get("SQL_MAX_ROWS", 2000))
    SQL_TIMEOUT_MS = int(os.environ.get("SQL_TIMEOUT_MS", 3000))

    # Map defaults (any tile server with an open licence works)
    MAP_CENTER = [float(x) for x in os.environ.get("MAP_CENTER", "52.52,13.405").split(",")]
    MAP_ZOOM = int(os.environ.get("MAP_ZOOM", 11))
    TILE_URL = os.environ.get("TILE_URL", "https://tile.openstreetmap.org/{z}/{x}/{y}.png")
    TILE_ATTRIBUTION = os.environ.get(
        "TILE_ATTRIBUTION",
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    )
