"""Tests run against a real PostgreSQL test database (created by database/setup.sql).

    TEST_DATABASE_URL           default postgresql://incident:incident@localhost:5432/incidents_test
    TEST_DATABASE_URL_READONLY  default postgresql://incident_reader:reader@localhost:5432/incidents_test

The events table in the TEST database is dropped before every test.
"""
import os
import sys
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app  # noqa: E402

URL = os.environ.get("TEST_DATABASE_URL",
                     "postgresql://incident:incident@localhost:5432/incidents_test")
RO_URL = os.environ.get("TEST_DATABASE_URL_READONLY",
                        "postgresql://incident_reader:reader@localhost:5432/incidents_test")


def make_app(**overrides):
    try:
        with psycopg.connect(URL, connect_timeout=3) as con:
            con.execute("DROP TABLE IF EXISTS events")
    except psycopg.OperationalError as e:
        pytest.skip(f"test database not reachable: {e}")
    cfg = {"DATABASE_URL": URL, "DATABASE_URL_READONLY": RO_URL, "TESTING": True,
           "INPUT_KEY": None, "VIEW_KEY": None, "DB_POOL_MAX": 2}
    cfg.update(overrides)
    return create_app(cfg)


@pytest.fixture
def client():
    app = make_app()
    yield app.test_client()
    app.extensions["db_pool"].close()


def valid(**kw):
    return {"event_type": "festnahme", "verified": "no", "simulated": "yes",
            "lat": 52.5, "lon": 13.4, "reporter_role": "bystander", "taken_into_custody": "yes",
            "var_1": "hello", "var_5": "2026-09-01T14:30", **kw}


def test_create_and_search(client):
    r = client.post("/api/events", json=valid())
    assert r.status_code == 201, r.json
    assert r.json["event_id"] == 1 and r.json["simulated"] is True
    assert r.json["var_5"] == "2026-09-01T14:30:00"
    assert r.json["reporter_role"] == "bystander" and r.json["taken_into_custody"] is True
    assert client.get("/api/events?q=HELLO&simulated=yes").json["count"] == 1  # ILIKE
    assert client.get("/api/events?verified=yes").json["count"] == 0
    assert client.get("/api/events?q=1").json["count"] == 1  # event_id match


def test_validation(client):
    r = client.post("/api/events", json=valid(event_type="nope", lat=200, reporter_role=""))
    assert r.status_code == 400
    assert {"event_type", "lat", "reporter_role"} <= set(r.json["fields"])
    r = client.post("/api/events", json=valid(reporter_role="police"))
    assert r.status_code == 400 and "reporter_role" in r.json["fields"]


def test_stats(client):
    client.post("/api/events", json=valid())
    client.post("/api/events", json=valid(verified="yes"))
    assert client.get("/api/stats").json == {"total": 2, "last_24h": 2, "verified": 1}


def test_bbox_and_dates(client):
    client.post("/api/events", json=valid())
    assert client.get("/api/events?bbox=13,52,14,53").json["count"] == 1
    assert client.get("/api/events?bbox=0,0,1,1").json["count"] == 0
    assert client.get("/api/events?date_from=2000-01-01").json["count"] == 1
    assert client.get("/api/events?date_to=2000-01-01").json["count"] == 0


def test_sql_readonly(client):
    client.post("/api/events", json=valid())
    r = client.post("/api/sql", json={"sql": "SELECT event_type, COUNT(*) n, AVG(lat) FROM events GROUP BY 1"})
    assert r.status_code == 200 and r.json["rows"] == [["festnahme", 1, 52.5]]
    r = client.post("/api/sql", json={"sql": "SELECT * FROM events WHERE var_1 LIKE '%ell%'"})
    assert r.status_code == 200 and len(r.json["rows"]) == 1
    for bad in ["DELETE FROM events", "DROP TABLE events", "UPDATE events SET verified=true",
                "SELECT 1; DELETE FROM events", "COMMIT; DELETE FROM events",
                "INSERT INTO events (event_type, lat, lon) VALUES ('x', 1, 1)",
                "CREATE TABLE x (a int)", "SET TRANSACTION READ WRITE"]:
        r = client.post("/api/sql", json={"sql": bad})
        assert r.status_code == 400, (bad, r.json)
    assert client.get("/api/events").json["count"] == 1


def test_sql_timeout():
    app = make_app(SQL_TIMEOUT_MS=100)
    r = app.test_client().post("/api/sql", json={"sql": "SELECT pg_sleep(2)"})
    assert r.status_code == 400 and "exceeded" in r.json["error"]
    app.extensions["db_pool"].close()


def test_access_keys():
    app = make_app(INPUT_KEY="in-secret", VIEW_KEY="view-secret")
    c = app.test_client()
    assert c.get("/input").status_code == 403
    assert c.get("/input?key=in-secret").status_code == 302
    assert c.get("/input").status_code == 200
    assert c.get("/view").status_code == 403
    assert c.post("/api/sql", json={"sql": "SELECT 1"}).status_code == 403
    c.get("/view?key=view-secret")
    assert c.get("/view").status_code == 200
    app.extensions["db_pool"].close()


def test_pages_render(client):
    assert "Neuer Vorfall" in client.get("/input").get_data(as_text=True)
    assert b"reported_at" in client.get("/view").data
