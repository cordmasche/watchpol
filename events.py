"""Validation, insert and search for incident events."""
from datetime import date, datetime

from psycopg import sql

from db import connection
from schema import EVENT_TYPE_VALUES, FIELDS, option_values

TEXT_TYPES = {"text", "textarea", "select"}
YES = {"yes", "true", "1", "on", True, 1}
NO = {"no", "false", "0", "off", "", None, False, 0}


class ValidationError(ValueError):
    def __init__(self, errors):
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors


def _yes_no(value):
    v = value.lower().strip() if isinstance(value, str) else value
    if v in YES:
        return True
    if v in NO:
        return False
    raise ValueError("ja oder nein")


def _coerce(field, value):
    t = field["type"]
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return False if t == "boolean" else None
    if t in TEXT_TYPES:
        value = str(value).strip()
        if t == "select" and value not in option_values(field.get("options", [])):
            raise ValueError("bitte eine der Optionen wählen")
        if len(value) > field.get("max_length", 5000):
            raise ValueError("zu lang")
        return value
    if t == "number":
        return float(value)
    if t == "integer":
        return int(value)
    if t == "boolean":
        return _yes_no(value)
    if t == "date":
        return date.fromisoformat(str(value))
    if t == "datetime":
        return datetime.fromisoformat(str(value)).replace(tzinfo=None, second=0, microsecond=0)
    raise ValueError(f"unsupported type {t}")


def validate(payload):
    errors, clean = {}, {}

    if payload.get("event_type") not in EVENT_TYPE_VALUES:
        errors["event_type"] = "bitte eine Art des Vorfalls wählen"
    else:
        clean["event_type"] = payload["event_type"]

    for key in ("verified", "simulated"):
        try:
            clean[key] = _yes_no(payload.get(key, "no"))
        except ValueError as e:
            errors[key] = str(e)

    for key, lo, hi in (("lat", -90, 90), ("lon", -180, 180)):
        try:
            v = float(payload.get(key))
            if not lo <= v <= hi:
                raise ValueError
            clean[key] = v
        except (TypeError, ValueError):
            errors[key] = "Ort fehlt – bitte auf die Karte tippen"

    for f in FIELDS:
        try:
            v = _coerce(f, payload.get(f["name"]))
            if f.get("required") and v is None:
                raise ValueError("Pflichtfeld")
            clean[f["name"]] = v
        except (TypeError, ValueError) as e:
            errors[f["name"]] = str(e) if str(e) in ("Pflichtfeld", "ja oder nein", "zu lang", "bitte eine der Optionen wählen") else "ungültiger Wert"

    if errors:
        raise ValidationError(errors)
    return clean


def insert_event(payload):
    data = validate(payload)
    query = sql.SQL("INSERT INTO events ({cols}) VALUES ({vals}) RETURNING *").format(
        cols=sql.SQL(", ").join(map(sql.Identifier, data)),
        vals=sql.SQL(", ").join(sql.Placeholder(k) for k in data),
    )
    with connection() as con:
        return con.execute(query, data).fetchone()


def get_event(event_id):
    with connection() as con:
        return con.execute("SELECT * FROM events WHERE event_id = %s", (event_id,)).fetchone()


def search_events(args, max_rows):
    """Structured search. All filters optional:
    q, event_type, verified, simulated, date_from, date_to, bbox=west,south,east,north, limit
    """
    where, params = [], []

    q = (args.get("q") or "").strip()
    if q:
        text_cols = ["event_type"] + [f["name"] for f in FIELDS if f["type"] in TEXT_TYPES]
        where.append(sql.SQL("({} OR event_id::text = %s)").format(
            sql.SQL(" OR ").join(sql.SQL("{} ILIKE %s").format(sql.Identifier(c)) for c in text_cols)))
        params += [f"%{q}%"] * len(text_cols) + [q]

    if args.get("event_type"):
        where.append(sql.SQL("event_type = %s"))
        params.append(args["event_type"])

    for key in ("verified", "simulated"):
        if args.get(key) in ("yes", "no"):
            where.append(sql.SQL("{} = %s").format(sql.Identifier(key)))
            params.append(args[key] == "yes")

    try:
        if args.get("date_from"):
            params.append(date.fromisoformat(args["date_from"]))
            where.append(sql.SQL("reported_at >= %s"))
        if args.get("date_to"):
            params.append(date.fromisoformat(args["date_to"]))
            where.append(sql.SQL("reported_at < %s::date + 1"))
    except ValueError:
        pass

    if args.get("bbox"):
        try:
            w, s, e, n = (float(x) for x in args["bbox"].split(","))
            where.append(sql.SQL("lat BETWEEN %s AND %s AND lon BETWEEN %s AND %s"))
            params += [s, n, w, e]
        except ValueError:
            pass

    try:
        limit = max(1, min(int(args.get("limit", max_rows)), max_rows))
    except ValueError:
        limit = max_rows

    query = sql.SQL("SELECT * FROM events")
    if where:
        query += sql.SQL(" WHERE ") + sql.SQL(" AND ").join(where)
    query += sql.SQL(" ORDER BY reported_at DESC, event_id DESC LIMIT %s")
    params.append(limit)
    with connection() as con:
        return con.execute(query, params).fetchall()
