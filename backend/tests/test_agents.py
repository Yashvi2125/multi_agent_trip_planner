import json
from datetime import date

import httpx
import pytest

from app.agents.llm import GeminiClient, LLMError
from app.agents.preference import extract_preferences
from app.core.database import SessionLocal
from app.models import Constraint, Preference, Trip
from app.schemas.agents import ExtractionResult
from app.services import conflict_service
from app.services.preference_service import apply_extraction
from app.services.topics import normalize_topic
from tests.conftest import GOA, make_user
from tests.fakes import FakeLLM


def setup_trip(client, n_extra=1):
    """Creator + n_extra members. Returns (trip_id, [user_ids])."""
    h, u, _ = make_user(client)
    t = client.post("/api/trips", json=GOA, headers=h).json()
    ids = [u["id"]]
    for i in range(n_extra):
        h2, u2, _ = make_user(client, ["Priya Shah", "Aman Verma", "Neha Rao"][i], f"m{i}@example.com")
        client.post("/api/trips/join", json={"code": t["code"]}, headers=h2)
        ids.append(u2["id"])
    return t["id"], ids


def feed(trip_id, user_id, payload: dict, msg="x"):
    with SessionLocal() as db:
        trip = db.get(Trip, trip_id)
        return apply_extraction(db, trip, user_id, None, ExtractionResult.model_validate(payload))


def sync(trip_id):
    with SessionLocal() as db:
        return conflict_service.sync_conflicts(db, db.get(Trip, trip_id))


def pref(cat, topic, w=3):
    return {"category": cat, "topic": topic, "weight": w}


# ---------- preference extraction ----------

def test_topic_normalisation():
    assert normalize_topic("Late-night clubs") == "nightlife"
    assert normalize_topic("BEACH") == "beaches"
    assert normalize_topic("Dudhsagar Falls") == "dudhsagar falls"   # a specific place is not a topic synonym
    assert normalize_topic("pottery classes") == "pottery classes"


def test_extraction_passes_through_llm_and_validates():
    llm = FakeLLM({"I want beaches and no clubs": {"preferences": [pref("interest", "beaches", 4), pref("dislike", "clubs")]}})
    r = extract_preferences(llm, "I want beaches and no clubs", "Goa", date(2026, 10, 1))
    assert [p.topic for p in r.preferences] == ["beaches", "clubs"]


def test_no_preferences_is_a_valid_empty_result(client):
    tid, (u1, _) = setup_trip(client)
    llm = FakeLLM({})
    r = extract_preferences(llm, "lol ok", "Goa")
    with SessionLocal() as db:
        out = apply_extraction(db, db.get(Trip, tid), u1, None, r)
    assert out.empty


@pytest.mark.parametrize("bad", [
    {"constraints": [{"type": "max_budget"}]},
    {"constraints": [{"type": "unavailable_day"}]},
    {"constraints": [{"type": "dietary", "text": "  "}]},
    {"preferences": [{"category": "interest", "topic": "x", "weight": 9}]},
    {"preferences": [{"category": "bogus", "topic": "x"}]},
])
def test_schema_rejects_malformed_extractions(bad):
    with pytest.raises(Exception):
        ExtractionResult.model_validate(bad)


def test_personal_budget_becomes_hard_constraint_owned_by_user(client):
    tid, (u1, u2) = setup_trip(client)
    feed(tid, u2, {"constraints": [{"type": "max_budget", "amount": "12000"}]})
    with SessionLocal() as db:
        c = db.query(Constraint).one()
        assert c.user_id == u2 and c.value == {"amount": "12000"}
        assert db.get(Trip, tid).group_budget == 60000   # personal limit doesn't touch the group budget


def test_group_budget_statement_updates_trip(client):
    tid, (u1, _) = setup_trip(client)
    feed(tid, u1, {"constraints": [{"type": "max_budget", "amount": "80000", "applies_to_group": True}]})
    with SessionLocal() as db:
        assert db.get(Trip, tid).group_budget == 80000
        assert db.query(Constraint).one().user_id is None


def test_latest_budget_wins_and_duplicates_are_ignored(client):
    tid, (u1, _) = setup_trip(client)
    feed(tid, u1, {"constraints": [{"type": "max_budget", "amount": "12000"}]})
    feed(tid, u1, {"constraints": [{"type": "max_budget", "amount": "15000"}]})
    feed(tid, u1, {"preferences": [pref("interest", "beaches")]})
    out = feed(tid, u1, {"preferences": [pref("interest", "beach")]})   # same topic, different wording
    assert out.empty
    with SessionLocal() as db:
        active = [c.value["amount"] for c in db.query(Constraint).filter_by(active=True)]
        assert active == ["15000"] and db.query(Preference).count() == 1


# ---------- conflicts ----------

def test_compatible_preferences_no_conflict(client):
    tid, (u1, u2) = setup_trip(client)
    feed(tid, u1, {"preferences": [pref("interest", "beaches")]})
    feed(tid, u2, {"preferences": [pref("interest", "beaches"), pref("interest", "food")]})
    assert sync(tid) == ([], [])


def test_nightlife_conflict_detected_with_compromise(client):
    tid, (u1, u2) = setup_trip(client)
    feed(tid, u1, {"preferences": [pref("interest", "clubs", 5)]})
    feed(tid, u2, {"preferences": [pref("dislike", "nightlife", 4)]})
    opened, resolved = sync(tid)
    assert len(opened) == 1 and opened[0].kind == "topic_clash"
    assert "Rahul Mehta" in opened[0].description and "Priya Shah" in opened[0].description
    assert "single slot" in opened[0].proposed_compromise
    assert sorted(opened[0].involved_user_ids) == sorted([u1, u2])


def test_sync_is_idempotent(client):
    tid, (u1, u2) = setup_trip(client)
    feed(tid, u1, {"preferences": [pref("interest", "nightlife")]})
    feed(tid, u2, {"preferences": [pref("dislike", "nightlife")]})
    assert len(sync(tid)[0]) == 1
    assert sync(tid) == ([], [])


def test_user_changing_mind_auto_resolves_conflict(client):
    tid, (u1, u2) = setup_trip(client)
    feed(tid, u1, {"preferences": [pref("interest", "nightlife")]})
    feed(tid, u2, {"preferences": [pref("dislike", "nightlife")]})
    sync(tid)
    out = feed(tid, u1, {"preferences": [pref("dislike", "nightlife")]})   # Rahul now agrees with Priya
    assert out.changed_mind == ["nightlife"]
    opened, resolved = sync(tid)
    assert opened == [] and len(resolved) == 1 and resolved[0].status.value == "resolved"


def test_hard_avoid_vs_soft_want_is_flagged_differently(client):
    tid, (u1, u2) = setup_trip(client)
    feed(tid, u1, {"preferences": [pref("interest", "nightlife")]})
    feed(tid, u2, {"constraints": [{"type": "must_avoid", "text": "clubs"}]})
    opened, _ = sync(tid)
    assert [c.kind for c in opened] == ["hard_vs_soft"]
    assert "ruled it out" in opened[0].description and "optional" in opened[0].proposed_compromise


def test_budget_gap_against_group_share(client):
    tid, (u1, u2) = setup_trip(client)            # 60,000 / 2 members = 30,000 each
    feed(tid, u2, {"constraints": [{"type": "max_budget", "amount": "12000"}]})
    opened, _ = sync(tid)
    assert opened[0].kind == "budget_gap" and "₹12,000" in opened[0].description and "₹30,000" in opened[0].description
    feed(tid, u2, {"constraints": [{"type": "max_budget", "amount": "35000"}]})
    assert sync(tid)[1][0].kind == "budget_gap"   # raising the limit resolves it


def test_unavailable_day_inside_trip_only(client):
    tid, (u1, u2) = setup_trip(client)
    feed(tid, u2, {"constraints": [{"type": "unavailable_day", "dates": ["2027-01-20"]}]})
    assert sync(tid) == ([], [])                  # outside 10–14 Dec
    feed(tid, u2, {"constraints": [{"type": "unavailable_day", "dates": ["2026-12-12"]}]})
    opened, _ = sync(tid)
    assert opened[0].kind == "date_clash" and "12 Dec" in opened[0].description


# ---------- Gemini client (mocked transport, no network) ----------

def gemini(handler, key="k"):
    return GeminiClient(api_key=key, model="m", transport=httpx.MockTransport(handler))


def reply(text):
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})


def test_gemini_parses_valid_json():
    seen = {}

    def h(req):
        seen["key"], seen["body"] = req.headers["x-goog-api-key"], json.loads(req.content)
        return reply(json.dumps({"preferences": [pref("interest", "beaches")]}))

    r = gemini(h).structured(ExtractionResult, "sys", "I like beaches")
    assert r.preferences[0].topic == "beaches"
    assert seen["key"] == "k" and seen["body"]["generationConfig"]["temperature"] == 0


def test_gemini_repairs_once_then_succeeds():
    calls = []

    def h(req):
        calls.append(1)
        return reply("not json") if len(calls) == 1 else reply("{}")

    assert gemini(h).structured(ExtractionResult, "s", "u") == ExtractionResult()
    assert len(calls) == 2


def test_gemini_gives_up_after_two_bad_replies():
    with pytest.raises(LLMError):
        gemini(lambda r: reply("nope")).structured(ExtractionResult, "s", "u")


@pytest.mark.parametrize("handler", [
    lambda r: httpx.Response(429, json={}),
    lambda r: httpx.Response(200, json={"candidates": []}),
    lambda r: (_ for _ in ()).throw(httpx.ConnectError("offline")),
])
def test_gemini_failures_become_llm_error(handler):
    with pytest.raises(LLMError):
        gemini(handler).structured(ExtractionResult, "s", "u")


def test_gemini_without_key_fails_fast():
    with pytest.raises(LLMError):
        gemini(lambda r: reply("{}"), key="").structured(ExtractionResult, "s", "u")
