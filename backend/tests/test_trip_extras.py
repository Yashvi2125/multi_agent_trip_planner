from app.core.database import SessionLocal
from app.models import Conflict, Message
import pytest

from tests.conftest import GOA, make_user
from tests.test_graph import Group, NEHA, PRIYA, RAHUL


@pytest.fixture()
def g(client, fake_planner):
    return Group(client, fake_planner)


def test_destinations_lists_supported_places(client):
    r = client.get("/api/destinations").json()
    assert [d["name"] for d in r] == ["Bali", "Goa", "Jaipur", "Manali"]
    assert all(d["places"] >= 10 and d["highlights"] and d["peak_months"] for d in r)
    assert 12 in next(d for d in r if d["name"] == "Goa")["peak_months"]


def test_only_creator_can_edit_trip_and_dates_are_validated(g):
    r = g.client.patch(f"/api/trips/{g.tid}", json={"name": "Goa, final"}, headers=g.users["priya"]["h"])
    assert r.status_code == 403 and "created the trip" in r.json()["error"]["message"]
    h = g.users["rahul"]["h"]
    assert g.client.patch(f"/api/trips/{g.tid}", json={"name": "Goa, final", "group_budget": "80000"}, headers=h).json()["name"] == "Goa, final"
    bad = g.client.patch(f"/api/trips/{g.tid}", json={"end_date": "2026-12-01"}, headers=h)
    assert bad.status_code == 422 and "can't end before" in bad.json()["error"]["message"]
    assert g.client.patch(f"/api/trips/{g.tid}", json={"group_budget": "-1"}, headers=h).status_code == 422
    msgs = [m["text"] for m in g.messages() if m["sender_type"] == "system"]
    assert any("updated the trip (name, group budget)" in t for t in msgs)


def test_destination_is_locked_once_a_plan_exists(g):
    h = g.users["rahul"]["h"]
    assert g.client.patch(f"/api/trips/{g.tid}", json={"destination": "Jaipur"}, headers=h).status_code == 200
    g.client.patch(f"/api/trips/{g.tid}", json={"destination": "Goa"}, headers=h)
    g.say("rahul", "@planner make the itinerary")
    r = g.client.patch(f"/api/trips/{g.tid}", json={"destination": "Jaipur"}, headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "destination_locked"


def test_non_member_blocked_from_every_new_endpoint(client, g):
    h, *_ = make_user(client, "Outsider", "out@example.com")
    p = f"/api/trips/{g.tid}"
    assert client.patch(p, json={"name": "x"}, headers=h).status_code == 403
    for path in ("/weather", "/checklist"):
        assert client.get(p + path, headers=h).status_code == 403
    assert client.post(p + "/conflicts/1/vote", json={"vote": "accept"}, headers=h).status_code == 403


def test_weather_endpoint_reports_source_and_days(g):
    w = g.client.get(f"/api/trips/{g.tid}/weather", headers=g.users["rahul"]["h"]).json()
    assert w["supported"] and w["source"] == "climatology" and len(w["days"]) == 5
    assert any("too far out" in n for n in w["notes"])


def test_checklist_seeds_from_destination_and_toggles(g):
    h = g.users["aman"]["h"]
    items = g.client.get(f"/api/trips/{g.tid}/checklist", headers=h).json()
    assert any("scooter" in i["label"] for i in items) and not any(i["done"] for i in items)
    assert len(g.client.get(f"/api/trips/{g.tid}/checklist", headers=h).json()) == len(items)   # seeded once
    r = g.client.patch(f"/api/trips/{g.tid}/checklist/{items[0]['id']}", json={"done": True}, headers=h)
    assert r.json()["done"] is True
    new = g.client.post(f"/api/trips/{g.tid}/checklist", json={"label": "Pack reef-safe sunscreen", "category": "packing"}, headers=h)
    assert new.status_code == 201 and new.json()["category"] == "packing"
    assert g.client.patch(f"/api/trips/{g.tid}/checklist/99999", json={"done": True}, headers=h).status_code == 404


def _open_conflict(g):
    g.say("rahul", RAHUL)
    g.say("priya", PRIYA)
    return g.client.get(f"/api/trips/{g.tid}/conflicts", headers=g.users["rahul"]["h"]).json()[0]


def test_conflict_vote_needs_strict_majority_and_closes(g):
    c = _open_conflict(g)
    assert c["status"] == "open" and c["accept_votes"] == 0 and c["my_vote"] is None
    url = f"/api/trips/{g.tid}/conflicts/{c['id']}/vote"
    r = g.client.post(url, json={"vote": "accept"}, headers=g.users["rahul"]["h"]).json()
    assert r["status"] == "open" and r["accept_votes"] == 1 and r["my_vote"] == "accept"       # 1 of 4 is not a majority
    g.client.post(url, json={"vote": "accept"}, headers=g.users["priya"]["h"])
    r = g.client.post(url, json={"vote": "accept"}, headers=g.users["aman"]["h"]).json()
    assert r["status"] == "accepted" and r["accept_votes"] == 3
    assert any("accepted this compromise" in m["text"] for m in g.messages() if m["sender_type"] == "system")
    again = g.client.post(url, json={"vote": "reject"}, headers=g.users["neha"]["h"])
    assert again.status_code == 409 and again.json()["error"]["code"] == "conflict_closed"


def test_votes_can_change_and_a_rejecting_majority_dismisses(g):
    c = _open_conflict(g)
    url = f"/api/trips/{g.tid}/conflicts/{c['id']}/vote"
    g.client.post(url, json={"vote": "accept"}, headers=g.users["rahul"]["h"])
    r = g.client.post(url, json={"vote": "reject"}, headers=g.users["rahul"]["h"]).json()
    assert r["accept_votes"] == 0 and r["reject_votes"] == 1                                    # changed, not double-counted
    r = g.client.post(url, json={"vote": "reject"}, headers=g.users["priya"]["h"]).json()
    assert r["status"] == "open"                                                                # 2 of 4 is not a majority
    r = g.client.post(url, json={"vote": "reject"}, headers=g.users["aman"]["h"]).json()
    assert r["status"] == "dismissed"                                                           # 3 of 4 is
    assert g.client.get(f"/api/trips/{g.tid}/conflicts", headers=g.users["aman"]["h"]).json()[0]["my_vote"] == "reject"


def test_vote_validation_and_unknown_conflict(g):
    h = g.users["rahul"]["h"]
    assert g.client.post(f"/api/trips/{g.tid}/conflicts/9999/vote", json={"vote": "accept"}, headers=h).status_code == 404
    assert g.client.post(f"/api/trips/{g.tid}/conflicts/1/vote", json={"vote": "maybe"}, headers=h).status_code == 422


def test_messages_expose_reply_link_and_meta(g):
    g.say("rahul", "@planner make the itinerary")
    msgs = g.messages()
    ai = [m for m in msgs if m["sender_type"] == "ai"][-1]
    asker = next(m for m in msgs if m["sender_type"] == "user")
    assert ai["reply_to_id"] == asker["id"] and ai["meta"]["version"] == 1
