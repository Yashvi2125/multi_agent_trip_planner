"""Telegram ↔ web, through the real app. Telegram's Bot API is faked at the HTTP transport; everything
else (webhook route, handlers, DB, hub, LangGraph runner, WebSocket) is real."""
import json
import time

import httpx
import pytest

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import Conflict, ConflictVote, Message, Trip, TripMember, User
from app.services import telegram_link
from app.services.event_hub import hub
from app.telegram import notifier, service
from app.telegram.client import TelegramClient
from tests.conftest import GOA, make_user, open_ws
from tests.test_graph import PRIYA, RAHUL

SECRET = "s3cret-token"
GROUP = -1001234567890


class FakeBotApi:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.fail = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        self.calls.append((method, json.loads(request.content)))
        if self.fail:
            return httpx.Response(500, json={"ok": False, "description": "boom"})
        return httpx.Response(200, json={"ok": True, "result": {}})

    def sent(self, chat_id=None) -> list[dict]:
        return [p for m, p in self.calls if m == "sendMessage" and (chat_id is None or p["chat_id"] == chat_id)]

    def texts(self, chat_id=None) -> list[str]:
        return [p["text"] for p in self.sent(chat_id)]


@pytest.fixture()
def bot(monkeypatch):
    api = FakeBotApi()
    s = get_settings()
    monkeypatch.setattr(s, "telegram_bot_username", "WayfareBot", raising=False)
    monkeypatch.setattr(s, "telegram_webhook_secret", SECRET, raising=False)
    service.configure(TelegramClient("111:AAA", transport=httpx.MockTransport(api)))
    hub.subscribe(notifier.on_event)
    yield api
    hub.unsubscribe(notifier.on_event)
    service.configure(None)
    service._built = False


def wait_for(pred, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.03)
    return False


def update(text, user=1, name="Bhakti Panchal", chat=GROUP, kind="supergroup", reply_to_bot=False, uid=[0]):
    uid[0] += 1
    m = {"message_id": uid[0], "from": {"id": user, "first_name": name.split()[0], "last_name": " ".join(name.split()[1:]) or None,
                                         "username": name.split()[0].lower(), "is_bot": False},
         "chat": {"id": chat if kind != "private" else user, "type": kind}, "text": text}
    if reply_to_bot:
        m["reply_to_message"] = {"from": {"id": 111, "is_bot": True}}
    return {"update_id": uid[0], "message": m}


def callback(data, user, name="Priya Shah"):
    return {"update_id": 1, "callback_query": {"id": "cb1", "data": data, "from": {"id": user, "first_name": name.split()[0],
                                                                                    "last_name": name.split()[1], "is_bot": False}}}


def post(client, u, secret=SECRET):
    headers = {"x-telegram-bot-api-secret-token": secret} if secret is not None else {}
    return client.post("/api/telegram/webhook", json=u, headers=headers)


def web_trip(client, name="Rahul Mehta", email="rahul@example.com", body=None):
    h, u, tok = make_user(client, name, email)
    t = client.post("/api/trips", json=body or GOA, headers=h).json()
    return h, u, tok, t


# ---------------------------------------------------------------- security & basics

def test_webhook_requires_the_secret_token(client, bot):
    assert post(client, update("/help"), secret="wrong").status_code == 403
    assert post(client, update("/help"), secret=None).status_code == 403
    assert bot.calls == []
    assert post(client, update("/help")).status_code == 200 and bot.texts()


def test_webhook_reports_when_the_bot_is_off(client):
    assert client.post("/api/telegram/webhook", json=update("/help")).status_code == 503
    assert client.get("/api/telegram/status").json()["configured"] is False


def test_start_and_help_and_unknown_command(client, bot):
    post(client, update("/start", kind="private"))
    post(client, update("/help", kind="private"))
    post(client, update("/dance", kind="private"))
    t = bot.texts()
    assert "Wayfare trip planner" in t[0] and "/create" in t[1] and "/join" in t[1] and "don't know that one" in t[2]


def test_bots_and_commands_for_other_bots_are_ignored(client, bot):
    u = update("/help")
    u["message"]["from"]["is_bot"] = True
    post(client, u)
    post(client, update("/help@SomeOtherBot"))
    assert bot.calls == []


def test_telegram_outage_never_breaks_the_webhook(client, bot):
    bot.fail = True
    assert post(client, update("/help")).status_code == 200


# ---------------------------------------------------------------- creating and joining

def test_create_in_a_group_makes_a_trip_and_connects_the_group(client, bot):
    post(client, update("/create Goa 2026-12-10 2026-12-14 60k"))
    reply = bot.texts()[0]
    with SessionLocal() as db:
        t = db.query(Trip).one()
        assert t.code in reply and t.telegram_chat_id == GROUP and t.destination == "Goa"
        assert str(t.group_budget).startswith("60000") and str(t.start_date) == "2026-12-10"
        m = db.query(TripMember).one()
        assert m.role.value == "creator" and m.joined_via.value == "telegram"
        assert db.query(User).one().email is None             # a Telegram-only person: real user, no password
    assert "This group is now connected" in reply


@pytest.mark.parametrize("cmd,expect", [
    ("/create", "Where are you going"),
    ("/create 2026-12-10", "Where are you going"),
    ("/create Goa 2026-12-10", "both a start and an end"),
    ("/create Goa 2026-12-14 2026-12-10", "don't look right"),
    ("/create Goa 2026-13-45 2026-12-10", "don't look right"),
])
def test_create_explains_bad_input(client, bot, cmd, expect):
    post(client, update(cmd))
    assert expect in bot.texts()[0] and "/create Goa" in bot.texts()[0]
    with SessionLocal() as db:
        assert db.query(Trip).count() == 0


def test_join_by_code_connects_group_and_announces_to_the_web(client, bot):
    h, u, tok, t = web_trip(client)
    with open_ws(client, t['id'], tok) as ws:
        post(client, update(f"/join {t['code'].lower()}", user=7, name="Priya Shah"))
        kinds = {ws.receive_json()["type"] for _ in range(2)}
    assert kinds == {"member.joined", "message.new"}
    d = client.get(f"/api/trips/{t['id']}", headers=h).json()
    assert d["member_count"] == 2 and d["telegram_connected"] is True
    assert {m["joined_via"] for m in d["members"]} == {"web", "telegram"}
    assert "You are in, Priya" in bot.texts()[0] and "This group is connected" in bot.texts()[0]
    assert wait_for(lambda: True) and len(bot.sent()) == 1            # the join note isn't echoed back to Telegram


def test_join_edge_cases(client, bot):
    h, u, tok, t = web_trip(client)
    post(client, update("/join ZZZ-999", user=7))
    assert "doesn't match any trip" in bot.texts()[-1]
    post(client, update("/join", user=7))
    assert "followed by the trip code" in bot.texts()[-1]
    post(client, update(f"/join {t['code']}", user=7, name="Priya Shah"))
    post(client, update(f"/join {t['code']}", user=7, name="Priya Shah"))
    assert "already in" in bot.texts()[-1]
    h2, _, _, t2 = web_trip(client, "Aman Verma", "aman@example.com")
    post(client, update(f"/join {t2['code']}", user=8, name="Neha Rao"))      # this group is bound to trip 1
    assert "already connected to" in bot.texts()[-1]
    post(client, update(f"/join {t['code']}", user=9, name="Third", chat=-555))   # trip 1 is bound to another group
    assert "already connected to a different Telegram group" in bot.texts()[-1]


# ---------------------------------------------------------------- the two-way bridge

def test_telegram_message_reaches_the_web_and_is_not_echoed(client, bot):
    h, u, tok, t = web_trip(client)
    post(client, update(f"/join {t['code']}", user=7, name="Priya Shah"))
    sent_before = len(bot.sent())
    with open_ws(client, t['id'], tok) as ws:
        post(client, update("I'd love to see Dudhsagar", user=7, name="Priya Shah"))
        evt = ws.receive_json()
    assert evt["type"] == "message.new" and evt["data"]["source"] == "telegram" and evt["data"]["sender"]["name"] == "Priya Shah"
    msgs = client.get(f"/api/trips/{t['id']}/messages", headers=h).json()
    assert msgs[-1]["text"] == "I'd love to see Dudhsagar" and msgs[-1]["source"] == "telegram"
    time.sleep(0.3)
    assert len(bot.sent()) == sent_before                                  # no echo to the origin channel


def test_web_message_is_forwarded_to_the_group_with_the_senders_name(client, bot):
    h, u, tok, t = web_trip(client)
    post(client, update(f"/join {t['code']}", user=7, name="Priya Shah"))
    client.post(f"/api/trips/{t['id']}/messages", json={"text": "Can we do a sunset at Chapora?"}, headers=h)
    assert wait_for(lambda: "Rahul Mehta (web): Can we do a sunset at Chapora?" in bot.texts(GROUP))


def test_group_chatter_joins_members_silently_and_unbound_groups_are_ignored(client, bot):
    h, u, tok, t = web_trip(client)
    post(client, update(f"/join {t['code']}", user=7, name="Priya Shah"))
    post(client, update("hey all", user=8, name="Aman Verma"))              # a new voice in the connected group
    assert client.get(f"/api/trips/{t['id']}", headers=h).json()["member_count"] == 3
    n = len(bot.sent())
    post(client, update("random chatter", user=9, name="Stranger", chat=-777))
    post(client, update("hello?", user=9, name="Stranger", chat=-777))
    with SessionLocal() as db:
        assert db.query(Message).filter(Message.text == "random chatter").count() == 0
        assert db.query(TripMember).filter_by(trip_id=t["id"]).count() == 3
    assert len(bot.sent()) == n                                              # silence, not nagging
    post(client, update("@WayfareBot hi", user=9, name="Stranger", chat=-777))
    assert "not connected to a trip" in bot.texts()[-1]


def test_mention_and_reply_address_the_planner_and_the_plan_comes_back(client, bot, fake_planner):
    h, u, tok, t = web_trip(client)
    post(client, update(f"/join {t['code']}", user=7, name="Priya Shah"))
    post(client, update("@WayfareBot make the itinerary", user=7, name="Priya Shah"))
    msgs = client.get(f"/api/trips/{t['id']}/messages", headers=h).json()
    assert any(m["text"] == "@planner make the itinerary" and m["source"] == "telegram" for m in msgs)
    assert wait_for(lambda: any("version 1" in x for x in bot.texts(GROUP)))
    assert client.get(f"/api/trips/{t['id']}/itinerary", headers=h).json()["version"] == 1
    assert any(m == "sendChatAction" for m, _ in bot.calls)                  # "typing…" while it works
    post(client, update("why the first stop?", user=7, name="Priya Shah", reply_to_bot=True))
    def answered():
        ms = client.get(f"/api/trips/{t['id']}/messages", headers=h).json()
        q = next((m for m in ms if m["text"] == "@planner why the first stop?"), None)     # "@planner" was added for us
        return q and any(m["sender_type"] == "ai" and m["reply_to_id"] == q["id"] for m in ms)
    assert wait_for(answered)


def test_commands_trip_members_itinerary_plan_budget(client, bot):
    h, u, tok, t = web_trip(client)
    post(client, update(f"/join {t['code']}", user=7, name="Priya Shah"))
    post(client, update("/trip", user=7, name="Priya Shah"))
    summary = bot.texts()[-1]
    assert "Goa with the gang" in summary and t["code"] in summary and "no plan yet" in summary and f"/trip/{t['id']}" in summary
    post(client, update("/members", user=7, name="Priya Shah"))
    assert "Rahul Mehta (creator, web)" in bot.texts()[-1] and "Priya Shah (telegram)" in bot.texts()[-1]
    post(client, update("/itinerary", user=7, name="Priya Shah"))
    assert "no plan yet" in bot.texts()[-1]
    post(client, update("/plan", user=7, name="Priya Shah"))
    assert wait_for(lambda: any("version 1" in x for x in bot.texts(GROUP)))
    post(client, update("/itinerary", user=7, name="Priya Shah"))
    plan = bot.texts()[-1]
    assert "Goa plan, version 1" in plan and "Day 1 (Thu 10 Dec)" in plan and "Day 5" in plan
    post(client, update("/budget", user=7, name="Priya Shah"))
    assert wait_for(lambda: any("The plan comes to about" in x for x in bot.texts(GROUP)))


def test_commands_without_a_trip_guide_the_user(client, bot):
    post(client, update("/trip", user=5, kind="private"))
    post(client, update("/plan", chat=-42, user=5))
    assert "not on a trip yet" in bot.texts()[0] and "isn't connected to a trip" in bot.texts()[1]


def test_private_chat_goes_to_the_users_latest_trip(client, bot):
    h, u, tok, t = web_trip(client)
    post(client, update(f"/join {t['code']}", user=7, name="Priya Shah", kind="private"))
    post(client, update("I'm vegetarian", user=7, name="Priya Shah", kind="private"))
    assert client.get(f"/api/trips/{t['id']}/messages", headers=h).json()[-1]["text"] == "I'm vegetarian"
    assert client.get(f"/api/trips/{t['id']}", headers=h).json()["telegram_connected"] is False   # DMs don't bind a group


# ---------------------------------------------------------------- conflicts and voting from both channels

def _conflict_setup(client, bot, fake_planner):
    fake_planner.deps.llm.table.update({
        RAHUL: {"preferences": [{"category": "interest", "topic": "nightlife", "weight": 5}]},
        PRIYA: {"preferences": [{"category": "dislike", "topic": "nightlife", "weight": 4}]}})
    h, u, tok, t = web_trip(client)
    for uid, nm in ((7, "Priya Shah"), (8, "Aman Verma")):
        post(client, update(f"/join {t['code']}", user=uid, name=nm))
    client.post(f"/api/trips/{t['id']}/messages", json={"text": RAHUL}, headers=h)
    post(client, update(PRIYA, user=7, name="Priya Shah"))
    return h, tok, t


def test_conflict_is_forwarded_with_vote_buttons_and_telegram_votes_count(client, bot, fake_planner):
    h, tok, t = _conflict_setup(client, bot, fake_planner)
    assert wait_for(lambda: any(p.get("reply_markup") for p in bot.sent(GROUP)))
    kb = next(p["reply_markup"] for p in bot.sent(GROUP) if p.get("reply_markup"))["inline_keyboard"][0]
    data = [b["callback_data"] for b in kb]
    assert data[0].endswith(":accept") and data[1].endswith(":reject")
    cid = int(data[0].split(":")[1])
    with open_ws(client, t['id'], tok) as ws:
        post(client, callback(data[0], user=7))
        post(client, callback(data[0], user=8, name="Aman Verma"))
        seen = [ws.receive_json() for _ in range(3)]
    assert [e["type"] for e in seen][:2] == ["conflict.updated", "conflict.updated"]
    assert seen[1]["data"]["status"] == "accepted" and seen[1]["data"]["accept_votes"] == 2   # 2 of 3 members
    c = client.get(f"/api/trips/{t['id']}/conflicts", headers=h).json()[0]
    assert c["id"] == cid and c["status"] == "accepted" and c["accept_votes"] == 2
    answers = [p["text"] for m, p in bot.calls if m == "answerCallbackQuery"]
    assert "Vote recorded: accept" in answers[0]


def test_votes_from_web_and_telegram_land_on_the_same_record(client, bot, fake_planner):
    h, tok, t = _conflict_setup(client, bot, fake_planner)
    c = client.get(f"/api/trips/{t['id']}/conflicts", headers=h).json()[0]
    client.post(f"/api/trips/{t['id']}/conflicts/{c['id']}/vote", json={"vote": "accept"}, headers=h)   # web
    post(client, callback(f"v:{c['id']}:accept", user=7))                                              # Telegram
    after = client.get(f"/api/trips/{t['id']}/conflicts", headers=h).json()[0]
    assert after["accept_votes"] == 2 and after["status"] == "accepted" and after["my_vote"] == "accept"


def test_vote_callbacks_from_outsiders_and_garbage_are_safe(client, bot, fake_planner):
    h, tok, t = _conflict_setup(client, bot, fake_planner)
    cid = client.get(f"/api/trips/{t['id']}/conflicts", headers=h).json()[0]["id"]
    post(client, callback(f"v:{cid}:accept", user=999, name="Out Sider"))
    post(client, callback("v:99999:accept", user=7))
    post(client, callback("nonsense", user=7))
    answers = [p["text"] for m, p in bot.calls if m == "answerCallbackQuery"]
    assert "Join the trip first" in answers[0] and len(answers) == 2
    with SessionLocal() as db:
        assert db.query(ConflictVote).count() == 0


# ---------------------------------------------------------------- linking a Telegram identity to a web account

def test_link_merges_the_telegram_identity_into_the_web_account(client, bot):
    h, u, tok, t = web_trip(client)                                          # Rahul owns a web trip
    post(client, update("/create Jaipur 2027-01-10 2027-01-12", user=7, name="Priya Shah", chat=-9001))
    post(client, update("hello from telegram", user=7, name="Priya Shah", chat=-9001))
    ph, pu, ptok = make_user(client, "Priya Shah", "priya@example.com")
    assert client.post("/api/telegram/link-code").status_code == 401
    code = client.post("/api/telegram/link-code", headers=ph).json()["code"]
    post(client, update(f"/link {code}", user=7, name="Priya Shah", kind="private"))
    assert "Linked. You're now Priya Shah" in bot.texts()[-1]
    trips = client.get("/api/trips", headers=ph).json()
    assert [x["destination"] for x in trips] == ["Jaipur"]                    # her Telegram-made trip is now on her web account
    msgs = client.get(f"/api/trips/{trips[0]['id']}/messages", headers=ph).json()
    assert any(m["text"] == "hello from telegram" and m["sender"]["id"] == pu["id"] for m in msgs)
    with SessionLocal() as db:
        assert db.query(User).filter(User.telegram_id == 7).one().email == "priya@example.com"
        assert db.query(User).filter(User.email.is_(None)).count() == 0       # the stub is gone
    post(client, update(f"/join {t['code']}", user=7, name="Priya Shah"))      # and she's the same person everywhere
    assert client.get(f"/api/trips/{t['id']}", headers=h).json()["member_count"] == 2


def test_link_codes_are_single_use_expire_and_reject_conflicts(client, bot, monkeypatch):
    ph, pu, _ = make_user(client, "Priya Shah", "priya@example.com")
    code = client.post("/api/telegram/link-code", headers=ph).json()["code"]
    post(client, update(f"/link {code}", user=7, name="Priya Shah", kind="private"))
    post(client, update(f"/link {code}", user=7, name="Priya Shah", kind="private"))
    assert "didn't work" in bot.texts()[-1]                                  # single use
    post(client, update("/link ", user=7, name="Priya Shah", kind="private"))
    assert "didn't work" in bot.texts()[-1]
    code2 = client.post("/api/telegram/link-code", headers=ph).json()["code"]
    post(client, update(f"/link {code2}", user=8, name="Someone Else", kind="private"))
    assert "already linked to a different Telegram" in bot.texts()[-1]
    gh, _, _ = make_user(client, "Gone Late", "late@example.com")
    code3 = client.post("/api/telegram/link-code", headers=gh).json()["code"]
    monkeypatch.setattr(telegram_link, "TTL_SECONDS", 0)
    telegram_link._codes[code3] = (telegram_link._codes[code3][0], time.monotonic() - 1)
    post(client, update(f"/link {code3}", user=9, name="Late", kind="private"))
    assert "didn't work" in bot.texts()[-1]


def test_cannot_hijack_an_account_that_already_has_a_login(client, bot):
    a, _, _ = make_user(client, "Priya Shah", "priya@example.com")
    b, _, _ = make_user(client, "Aman Verma", "aman@example.com")
    c1 = client.post("/api/telegram/link-code", headers=a).json()["code"]
    post(client, update(f"/link {c1}", user=7, name="Priya Shah", kind="private"))
    c2 = client.post("/api/telegram/link-code", headers=b).json()["code"]
    post(client, update(f"/link {c2}", user=7, name="Priya Shah", kind="private"))
    assert "already belongs to another Wayfare login" in bot.texts()[-1]
