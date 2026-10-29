"""Direct-message mode: members who joined from a private chat (no Telegram group bound) must receive the
same trip traffic as a group would: web messages, other members' messages, the planner's replies and vote buttons."""
from app.core.database import SessionLocal
from app.models import Trip
from tests.test_graph import PRIYA, RAHUL
from tests.test_telegram import bot, post, update, wait_for, web_trip  # noqa: F401  (bot is a fixture)

PRIYA_ID, AMAN_ID = 7, 8


def dm(text, user, name):
    return update(text, user=user, name=name, kind="private")


def dm_trip(client, members=((PRIYA_ID, "Priya Shah"),)):
    h, u, tok, t = web_trip(client)
    for uid, name in members:
        post(client, dm(f"/join {t['code']}", uid, name))
    return h, tok, t


def test_web_message_reaches_dm_members(client, bot):
    h, tok, t = dm_trip(client)
    client.post(f"/api/trips/{t['id']}/messages", json={"text": "Sunset at Chapora?"}, headers=h)
    assert wait_for(lambda: "Rahul Mehta (web): Sunset at Chapora?" in bot.texts(PRIYA_ID))


def test_planner_replies_to_a_dm_user_in_their_dm(client, bot):
    h, tok, t = dm_trip(client)
    post(client, dm("@planner hello", PRIYA_ID, "Priya Shah"))
    assert wait_for(lambda: any("I'm here" in x for x in bot.texts(PRIYA_ID)))


def test_dm_members_see_each_other_but_never_their_own_message(client, bot):
    h, tok, t = dm_trip(client, ((PRIYA_ID, "Priya Shah"), (AMAN_ID, "Aman Verma")))
    post(client, dm("I'd love Dudhsagar", PRIYA_ID, "Priya Shah"))
    assert wait_for(lambda: "Priya Shah (Telegram): I'd love Dudhsagar" in bot.texts(AMAN_ID))
    assert not any("I'd love Dudhsagar" in x for x in bot.texts(PRIYA_ID))          # no echo to the sender


def test_dm_user_only_receives_their_current_trip(client, bot):
    h, tok, t = dm_trip(client)
    h2, _, _, other = web_trip(client, "Neha Rao", "neha@example.com")
    post(client, dm(f"/join {other['code']}", PRIYA_ID, "Priya Shah"))              # Priya's latest trip is now `other`
    bot.calls.clear()
    client.post(f"/api/trips/{t['id']}/messages", json={"text": "only for the first trip"}, headers=h)
    client.post(f"/api/trips/{other['id']}/messages", json={"text": "for the second trip"}, headers=h2)
    assert wait_for(lambda: "Neha Rao (web): for the second trip" in bot.texts(PRIYA_ID))
    assert not any("only for the first trip" in x for x in bot.texts(PRIYA_ID))


def test_bound_group_still_gets_everything_and_dm_members_are_not_duplicated(client, bot):
    h, tok, t = dm_trip(client)
    GROUP = -1001234567890
    post(client, update(f"/join {t['code']}", user=AMAN_ID, name="Aman Verma"))      # binds the group
    bot.calls.clear()
    client.post(f"/api/trips/{t['id']}/messages", json={"text": "hello everyone"}, headers=h)
    assert wait_for(lambda: "Rahul Mehta (web): hello everyone" in bot.texts(GROUP))
    assert not any("hello everyone" in x for x in bot.texts(PRIYA_ID))              # the group is the channel


def test_conflict_vote_buttons_reach_dm_members(client, bot, fake_planner):
    fake_planner.deps.llm.table.update({
        RAHUL: {"preferences": [{"category": "interest", "topic": "nightlife", "weight": 5}]},
        PRIYA: {"preferences": [{"category": "dislike", "topic": "nightlife", "weight": 4}]}})
    h, tok, t = dm_trip(client, ((PRIYA_ID, "Priya Shah"), (AMAN_ID, "Aman Verma")))
    client.post(f"/api/trips/{t['id']}/messages", json={"text": RAHUL}, headers=h)
    post(client, dm(PRIYA, PRIYA_ID, "Priya Shah"))
    assert wait_for(lambda: any(p.get("reply_markup") for p in bot.sent(AMAN_ID)))
    kb = next(p["reply_markup"] for p in bot.sent(AMAN_ID) if p.get("reply_markup"))
    assert [b["callback_data"].split(":")[2] for b in kb["inline_keyboard"][0]] == ["accept", "reject"]
