from decimal import Decimal

from app.services.trip_code import CODE_RE, make_code
from tests.conftest import GOA, make_user


def test_code_format_and_alphabet():
    for d in ("Goa", "Jaipur", "Manali", "  ", "Pune 2"):
        assert CODE_RE.match(make_code(d)), d
    assert make_code("Goa").startswith("GOA-")


def test_create_trip_returns_code_and_creator_is_member(client):
    h, user, _ = make_user(client)
    r = client.post("/api/trips", json=GOA, headers=h)
    assert r.status_code == 201
    t = r.json()
    assert t["code"].startswith("GOA-") and t["member_count"] == 1 and Decimal(t["group_budget"]) == 60000
    detail = client.get(f"/api/trips/{t['id']}", headers=h).json()
    assert detail["members"][0]["role"] == "creator"


def test_invalid_dates_rejected(client):
    h, *_ = make_user(client)
    bad = {**GOA, "start_date": "2026-12-14", "end_date": "2026-12-10"}
    assert client.post("/api/trips", json=bad, headers=h).status_code == 422
    assert client.post("/api/trips", json={**GOA, "group_budget": "-5"}, headers=h).status_code == 422


def test_join_by_code_case_insensitive_and_idempotent(client):
    h1, *_ = make_user(client)
    h2, *_ = make_user(client, "Priya Shah", "priya@example.com")
    trip = client.post("/api/trips", json=GOA, headers=h1).json()
    r = client.post("/api/trips/join", json={"code": f" {trip['code'].lower()} "}, headers=h2)
    assert r.status_code == 200 and r.json()["member_count"] == 2
    again = client.post("/api/trips/join", json={"code": trip["code"]}, headers=h2)
    assert again.json()["member_count"] == 2
    assert len(client.get("/api/trips", headers=h2).json()) == 1


def test_invalid_code_is_friendly_404(client):
    h, *_ = make_user(client)
    r = client.post("/api/trips/join", json={"code": "ZZZ-999"}, headers=h)
    assert r.status_code == 404 and "trip code" in r.json()["error"]["message"]


def test_non_member_cannot_read_trip_or_chat(client):
    h1, *_ = make_user(client)
    h2, *_ = make_user(client, "Outsider", "out@example.com")
    tid = client.post("/api/trips", json=GOA, headers=h1).json()["id"]
    assert client.get(f"/api/trips/{tid}", headers=h2).status_code == 403
    assert client.get(f"/api/trips/{tid}/members", headers=h2).status_code == 403
    assert client.get(f"/api/trips/{tid}/messages", headers=h2).status_code == 403
    assert client.post(f"/api/trips/{tid}/messages", json={"text": "hi"}, headers=h2).status_code == 403


def test_unknown_trip_404(client):
    h, *_ = make_user(client)
    assert client.get("/api/trips/9999", headers=h).status_code == 404
