"""End-to-end through HTTP → runner → LangGraph → DB. Only the LLM and weather are faked."""
from decimal import Decimal

import pytest

from app.core.database import SessionLocal
from app.models import AIAction, Conflict, ItineraryVersion, Message, Trip
from tests.conftest import GOA, make_user, open_ws
from tests.fakes import FakeLLM

RAHUL = "I'd love nightlife and beaches!"
PRIYA = "I'm not into nightlife, I'd rather relax"
AMAN = "Can we add Dudhsagar?"
NEHA = "I can't spend more than ₹12,000"
TABLE = {
    RAHUL: {"preferences": [{"category": "interest", "topic": "nightlife", "weight": 5},
                            {"category": "interest", "topic": "beaches", "weight": 4}]},
    PRIYA: {"preferences": [{"category": "dislike", "topic": "nightlife", "weight": 4},
                            {"category": "interest", "topic": "relaxation", "weight": 4}]},
    AMAN: {"preferences": [{"category": "interest", "topic": "Dudhsagar Falls", "weight": 5},
                           {"category": "interest", "topic": "adventure", "weight": 4}]},
    NEHA: {"constraints": [{"type": "max_budget", "amount": "12000"}]},
    "Actually I'm fine skipping nightlife, I want more food": {"preferences": [
        {"category": "dislike", "topic": "nightlife", "weight": 3}, {"category": "interest", "topic": "food", "weight": 5}]},
}


class Group:
    def __init__(self, client, planner, trip_body=None, n=4):
        self.client, self.planner = client, planner
        planner.deps.llm.table.update(TABLE)
        names = [("Rahul Mehta", "rahul"), ("Priya Shah", "priya"), ("Aman Verma", "aman"), ("Neha Rao", "neha")][:n]
        self.users = {}
        for full, short in names:
            h, u, tok = make_user(client, full, f"{short}@example.com")
            self.users[short] = {"h": h, "id": u["id"], "token": tok}
        self.trip = client.post("/api/trips", json=trip_body or GOA, headers=self.users["rahul"]["h"]).json()
        for short in list(self.users)[1:]:
            client.post("/api/trips/join", json={"code": self.trip["code"]}, headers=self.users[short]["h"])
        self.tid = self.trip["id"]

    def say(self, who, text):
        r = self.client.post(f"/api/trips/{self.tid}/messages", json={"text": text}, headers=self.users[who]["h"])
        assert r.status_code == 202, r.text
        return r.json()

    def messages(self):
        return self.client.get(f"/api/trips/{self.tid}/messages", headers=self.users["rahul"]["h"]).json()

    def ai(self):
        return [m["text"] for m in self.messages() if m["sender_type"] == "ai"]

    def api(self, path, who="rahul"):
        return self.client.get(f"/api/trips/{self.tid}/{path}", headers=self.users[who]["h"])


@pytest.fixture()
def g(client, fake_planner):
    return Group(client, fake_planner)


# ---------- when the AI speaks, and when it doesn't ----------

def test_silent_extraction_then_conflict_surfaces(g):
    g.say("rahul", RAHUL)
    assert g.ai() == []                                        # soft preferences are absorbed quietly
    g.say("priya", PRIYA)
    ai = g.ai()
    assert len(ai) == 1 and "Rahul Mehta" in ai[0] and "Priya Shah" in ai[0] and "single slot" in ai[0]
    prefs = g.api("preferences").json()
    assert {(p["user_name"], p["category"], p["value"]) for p in prefs["preferences"]} >= {
        ("Rahul Mehta", "interest", "nightlife"), ("Priya Shah", "dislike", "nightlife")}
    assert g.api("conflicts").json()[0]["status"] == "open"


def test_hard_constraint_is_acknowledged_by_name(g):
    g.say("neha", NEHA)
    ai = g.ai()
    assert ai[0] == "Got it, Neha. I've noted your limit of ₹12,000 per person."
    assert any("can spend up to ₹12,000" in t for t in ai)     # and the budget clash is raised


def test_humans_talking_about_planning_stay_unanswered(g):
    g.say("rahul", "someone make the itinerary already lol")
    assert g.ai() == []
    assert g.api("itinerary").status_code == 404


def test_addressed_but_nothing_to_do_gets_a_friendly_nudge(g):
    g.say("rahul", "@planner hello")
    assert "Tell me what everyone's after" in g.ai()[0]


# ---------- the full demo script ----------

def test_full_demo_flow(g):
    for who, text in [("rahul", RAHUL), ("priya", PRIYA), ("aman", AMAN), ("neha", NEHA)]:
        g.say(who, text)
    g.say("rahul", "@planner make the itinerary")

    r = g.api("itinerary")
    assert r.status_code == 200
    v1 = r.json()
    assert v1["version"] == 1 and v1["change_summary"] == "First version of the plan."
    it = v1["itinerary"]
    assert len(it["days"]) == 5 and it["destination"] == "Goa"
    placed = [i["place_id"] for d in it["days"] for i in d["items"]]
    assert "dudhsagar" in placed                                # Aman's ask made it in
    assert placed.count("titos_lane") <= 1                      # contested nightlife limited to one slot
    assert len(set(placed)) == len(placed)

    plan_msg = [t for t in g.ai() if "version 1" in t][0]
    assert "Day 1 ·" in plan_msg and "per person" not in plan_msg.split("\n")[0] or "each" in plan_msg

    b = g.api("budget").json()
    assert b["travelers"] == 4 and b["cap"] == "48000"          # strictest: 12,000 × 4 beats the 60,000 group budget
    assert Decimal(b["total"]) / 4 == Decimal(b["per_person"]) or abs(Decimal(b["total"]) / 4 - Decimal(b["per_person"])) < 1

    # Rahul changes his mind → conflict resolves, plan updates, change is explained
    g.say("rahul", "Actually I'm fine skipping nightlife, I want more food")
    assert any("sorts out the earlier disagreement" in t for t in g.ai())
    g.say("priya", "@planner please update the plan")
    v2 = g.api("itinerary").json()
    assert v2["version"] == 2 and v2["change_summary"] != "First version of the plan."
    versions = g.api("itinerary/versions").json()
    assert [v["version"] for v in versions] == [1, 2]
    assert g.api("itinerary?version=1").json()["version"] == 1
    assert "What changed:" in [t for t in g.ai() if "version 2" in t][0]
    with SessionLocal() as db:
        assert db.get(Trip, g.tid).current_itinerary_version == 2


def test_budget_loop_pulls_levers_and_says_so(g):
    g.say("neha", NEHA)                                         # cap 48,000 for 4 people
    g.say("rahul", "@planner make the itinerary")
    msg = [t for t in g.ai() if "version 1" in t][0]
    b = g.api("budget").json()
    with SessionLocal() as db:
        reasoning = db.query(AIAction).filter(AIAction.intent == "plan").one().reasoning
    assert reasoning["loop_count"] >= 1 and reasoning["trimmed"]
    assert Decimal(b["total"]) <= Decimal(b["cap"]) or "over your" in msg   # fits, or says plainly that it doesn't


def test_unfixable_budget_is_reported_honestly_but_plan_is_still_saved(client, fake_planner):
    g = Group(client, fake_planner, {**GOA, "group_budget": "8000"})
    g.say("rahul", "@planner make the itinerary")
    msg = [t for t in g.ai() if "version 1" in t][0]
    assert "over your ₹8,000 budget" in msg and "couldn't close the gap" in msg
    assert g.api("budget").json()["status"] == "over"


def test_loose_budget_needs_no_trimming(client, fake_planner):
    g = Group(client, fake_planner, {**GOA, "group_budget": "300000"})
    g.say("rahul", "@planner make the itinerary")
    msg = [t for t in g.ai() if "version 1" in t][0]
    assert "comfortably inside" in msg
    with SessionLocal() as db:
        assert db.query(AIAction).filter(AIAction.intent == "plan").one().reasoning["loop_count"] == 0


# ---------- failure & edge handling ----------

def test_missing_dates_asks_instead_of_guessing(client, fake_planner):
    body = {k: v for k, v in GOA.items() if k not in ("start_date", "end_date")}
    g = Group(client, fake_planner, body)
    g.say("rahul", "@planner make the itinerary")
    assert "I need your trip dates" in g.ai()[0] and g.api("itinerary").status_code == 404


def test_unsupported_destination_lists_what_is_supported(client, fake_planner):
    g = Group(client, fake_planner, {**GOA, "destination": "Pune", "name": "Pune weekend"})
    g.say("rahul", "@planner make the itinerary")
    assert "Goa, Jaipur, Manali" in g.ai()[0]


def test_works_without_any_llm(client, fake_planner):
    g = Group(client, fake_planner)
    fake_planner.deps.llm = None
    g.say("rahul", RAHUL)                                       # extraction skipped, nobody crashes
    g.say("rahul", "@planner make the itinerary")
    msg = [t for t in g.ai() if "version 1" in t][0]
    assert "without my language model" in msg
    assert g.api("preferences").json()["preferences"] == []


def test_graph_crash_gives_friendly_message_only_if_addressed(g, monkeypatch):
    import app.graph.builder as b
    monkeypatch.setattr(b, "plan_itinerary", lambda *a, **k: 1 / 0)
    g.say("rahul", "just chatting")
    assert g.ai() == []
    g.say("rahul", "@planner make the itinerary")
    ai = g.ai()
    assert len(ai) == 1 and "hit a snag" in ai[0] and "ZeroDivision" not in ai[0]
    with SessionLocal() as db:
        assert db.query(AIAction).filter(AIAction.status == "failed").count() == 1


def test_weather_outage_is_disclosed(client, fake_planner):
    from tests.fakes import FakeWeather
    body = {**GOA, "start_date": "2026-10-05", "end_date": "2026-10-07"}
    g = Group(client, fake_planner, body)
    fake_planner.deps.weather = FakeWeather(fail=True)
    g.say("rahul", "@planner make the itinerary")
    assert any("couldn't reach the weather service" in t for t in g.ai())


# ---------- explainability ----------

def test_why_questions_are_grounded_in_the_plan(g):
    g.say("aman", AMAN)
    g.say("rahul", "@planner make the itinerary")
    g.say("aman", "@planner why is Dudhsagar in the plan?")
    ans = g.ai()[-1]
    assert "Dudhsagar Falls" in ans and "Day " in ans and "Aman" in ans


def test_llm_phrases_the_answer_but_only_from_facts(g, fake_planner):
    g.say("rahul", "@planner make the itinerary")
    fake_planner.deps.llm.answer = "Because it fits the group's budget."
    g.say("rahul", "@planner why this hotel?")
    assert g.ai()[-1] == "Because it fits the group's budget."
    schema, prompt = fake_planner.deps.llm.calls[-1]
    assert schema == "Answer" and "Facts:" in prompt and "stays in" in prompt


def test_explain_endpoint_and_regenerate_endpoint(g):
    g.say("rahul", "@planner make the itinerary")
    r = g.client.post(f"/api/trips/{g.tid}/explain", json={"question": "Why was this moved?"},
                      headers=g.users["priya"]["h"])
    assert r.status_code == 202 and r.json()["text"] == "Why was this moved?"
    r2 = g.client.post(f"/api/trips/{g.tid}/regenerate", headers=g.users["priya"]["h"])
    assert r2.status_code == 202
    assert g.api("itinerary").json()["version"] == 2
    assert g.client.post(f"/api/trips/{g.tid}/explain", json={"question": "x"}, headers=g.users["priya"]["h"]).status_code == 422


def test_explain_before_any_plan_is_helpful(g):
    g.say("rahul", "@planner why is the plan like this?")
    assert "no itinerary yet" in g.ai()[-1]


# ---------- auto re-plan policy ----------

def test_stale_hint_when_auto_replan_off(g):
    g.say("rahul", "@planner make the itinerary")
    g.say("rahul", "Actually I'm fine skipping nightlife, I want more food")
    assert any("doesn't include that yet" in t for t in g.ai())
    assert g.api("itinerary").json()["version"] == 1


def test_auto_replan_when_enabled(g, fake_planner):
    fake_planner.deps.auto_replan = True
    g.say("rahul", "@planner make the itinerary")
    g.say("rahul", "Actually I'm fine skipping nightlife, I want more food")
    assert g.api("itinerary").json()["version"] == 2


# ---------- plumbing ----------

def test_audit_trail_and_checkpoint(g):
    g.say("rahul", "@planner make the itinerary")
    with SessionLocal() as db:
        a = db.query(AIAction).filter(AIAction.intent == "plan").one()
        assert a.status == "ok" and "itinerary" in a.agents_run and a.finished_at
        assert a.reasoning["version"] == 1
        assert db.query(ItineraryVersion).one().created_by_action_id == a.id
    from app.graph.checkpointer import get_checkpointer
    assert get_checkpointer().get_tuple({"configurable": {"thread_id": str(g.tid)}}) is not None


def test_ai_never_replies_to_itself_or_loops(g):
    g.say("rahul", "@planner hello")
    with SessionLocal() as db:
        ai_msgs = db.query(Message).filter(Message.sender_type == "ai").count()
    assert ai_msgs == 1


def test_realtime_events_reach_websocket_members(g):
    with open_ws(g.client, g.tid, g.users['aman']['token']) as ws:
        g.say("rahul", "@planner make the itinerary")
        seen = set()
        for _ in range(60):
            seen.add(ws.receive_json()["type"])
            if {"itinerary.updated", "budget.updated", "ai.status"} <= seen:
                break
        assert {"message.new", "itinerary.updated", "budget.updated", "ai.status"} <= seen


def test_nonmember_cannot_read_plan_or_trigger_ai(client, g):
    h, *_ = make_user(client, "Outsider", "out@example.com")
    for path in ("itinerary", "budget", "conflicts", "preferences", "itinerary/versions"):
        assert client.get(f"/api/trips/{g.tid}/{path}", headers=h).status_code == 403
    assert client.post(f"/api/trips/{g.tid}/regenerate", headers=h).status_code == 403


# ---------- must-haves, trim priority, "why isn't X in the plan" ----------

MUST = "We absolutely must visit Dudhsagar"
TABLE[MUST] = {"constraints": [{"type": "must_include", "text": "Dudhsagar"}]}
TABLE["We must see the Spice plantation"] = {"constraints": [{"type": "must_include", "text": "spice plantation"}]}


def placed(g):
    return [i["place_id"] for d in g.api("itinerary").json()["itinerary"]["days"] for i in d["items"]]


def test_must_have_is_acknowledged_and_enforced(g):
    g.say("aman", MUST)
    assert "Dudhsagar as a must-have" in g.ai()[0]
    g.say("rahul", "@planner make the itinerary")
    assert "dudhsagar" in placed(g)


def test_must_have_survives_an_aggressive_budget(client, fake_planner):
    g = Group(client, fake_planner, {**GOA, "group_budget": "30000"})
    g.say("aman", MUST)
    g.say("rahul", "@planner make the itinerary")
    assert "dudhsagar" in placed(g)                            # trimmed everything else first, never this


def test_requested_extras_survive_while_unrequested_ones_are_trimmed(g):
    g.say("aman", AMAN)
    g.say("neha", NEHA)                                         # cap 48,000
    g.say("rahul", "@planner make the itinerary")
    with SessionLocal() as db:
        trimmed = db.query(AIAction).filter(AIAction.intent == "plan").one().reasoning["trimmed"]
    assert "Dudhsagar Falls" not in trimmed
    assert "dudhsagar" in placed(g)


def test_must_have_closed_for_the_season_is_explained_not_ignored(client, fake_planner):
    g = Group(client, fake_planner, {**GOA, "start_date": "2026-07-10", "end_date": "2026-07-13"})
    g.say("aman", MUST)
    g.say("rahul", "@planner make the itinerary")
    msg = [t for t in g.ai() if "version 1" in t][0]
    assert "isn't available in July" in msg and "couldn't include it" in msg
    assert "dudhsagar" not in placed(g)


def test_explaining_a_place_that_is_not_in_the_plan(client, fake_planner):
    g = Group(client, fake_planner, {**GOA, "start_date": "2026-07-10", "end_date": "2026-07-13"})
    g.say("rahul", "@planner make the itinerary")
    g.say("aman", "@planner why isn't Dudhsagar in the plan?")
    assert "Dudhsagar Falls isn't in the plan" in g.ai()[-1] and "July" in g.ai()[-1]


def test_explaining_a_budget_trimmed_place(client, fake_planner):
    g = Group(client, fake_planner, {**GOA, "group_budget": "30000"})
    g.say("rahul", "@planner make the itinerary")
    with SessionLocal() as db:
        trimmed = db.query(AIAction).filter(AIAction.intent == "plan").one().reasoning["trimmed"]
    candidates = [t for t in trimmed if t in ("Water sports at Baga", "Dudhsagar Falls", "Spice plantation tour")]
    assert candidates, trimmed
    g.say("aman", f"@planner why isn't {candidates[0]} in the plan?")
    assert "trimmed to bring the cost down" in g.ai()[-1] and "must-have" in g.ai()[-1]


def test_unmatched_must_have_is_flagged_by_validator(g):
    TABLE["We must go bungee jumping"] = {"constraints": [{"type": "must_include", "text": "bungee jumping"}]}
    g.planner.deps.llm.table.update(TABLE)
    g.say("rahul", "We must go bungee jumping")
    g.say("rahul", "@planner make the itinerary")
    assert any("don't have a verified place matching “bungee jumping”" in t for t in g.ai())


def test_trims_are_always_disclosed_and_free_days_read_naturally(g):
    g.say("rahul", RAHUL)
    g.say("neha", NEHA)                                         # cap 48,000 → something gets trimmed
    g.say("rahul", "@planner make the itinerary")
    msg = [t for t in g.ai() if "version 1" in t][0]
    with SessionLocal() as db:
        trimmed = db.query(AIAction).filter(AIAction.intent == "plan").one().reasoning["trimmed"]
    assert trimmed and "To get the cost down I made these changes" in msg
    assert all(t in msg for t in trimmed)
    assert "Free day: Free day" not in msg
