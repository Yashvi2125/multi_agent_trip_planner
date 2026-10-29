"""Hub subscriber: forwards what happens on the web (and the AI's replies) to the connected Telegram group.
The origin channel is skipped, so a Telegram message is never echoed back to Telegram."""
import logging

import anyio
from sqlalchemy import select

from app.core import database
from app.models import Trip, TripMember, User
from app.telegram import service
from app.telegram.client import TelegramError

log = logging.getLogger("wayfare.telegram")


def _keyboard(conflict_ids: list[int]) -> dict | None:
    if not conflict_ids:
        return None
    return {"inline_keyboard": [[{"text": f"Accept{'' if len(conflict_ids) == 1 else f' #{cid}'}", "callback_data": f"v:{cid}:accept"},
                                 {"text": f"Pass{'' if len(conflict_ids) == 1 else f' #{cid}'}", "callback_data": f"v:{cid}:reject"}]
                                for cid in conflict_ids]}


def _dm_recipients(db, trip_id: int, skip: set[int]) -> list[int]:
    """DM mode (no group bound): every Telegram member whose *current* trip this is, which is the same rule
    inbound DMs use, so a person on two trips never gets the wrong trip's chatter. `skip` = user ids to leave out."""
    rows = db.execute(select(User.id, User.telegram_id).join(TripMember, TripMember.user_id == User.id)
                      .where(TripMember.trip_id == trip_id, User.telegram_id.is_not(None))).all()
    out = []
    for uid, tg_id in rows:
        current = db.scalar(select(TripMember.trip_id).where(TripMember.user_id == uid)
                            .order_by(TripMember.joined_at.desc(), TripMember.id.desc()).limit(1))
        if uid not in skip and current == trip_id:
            out.append(tg_id)
    return out


def _forward(trip_id: int, event: dict) -> None:
    c = service.get_client()
    if c is None or event["type"] not in ("message.new", "ai.status"):
        return
    data = event["data"]
    meta = data.get("meta") or {} if event["type"] == "message.new" else {}
    from_telegram = event["type"] == "message.new" and (data["source"] == "telegram" or meta.get("origin") == "telegram")
    with database.SessionLocal() as db:
        trip = db.get(Trip, trip_id)
        if trip is None:
            return
        group = trip.telegram_chat_id
        if group is not None:
            chats = [] if from_telegram else [group]          # already visible in the group it came from
        elif event["type"] == "ai.status":
            chats = []                                        # no typing indicator in DMs: we can't tell whose it is
        else:
            skip = {(data.get("sender") or {}).get("id"), meta.get("user_id")} - {None}
            chats = _dm_recipients(db, trip_id, skip)         # everyone but the author, so no echo
    try:
        if event["type"] == "ai.status":
            if data.get("text") and chats:
                c.send_typing(chats[0])
            return
        name = (data.get("sender") or {}).get("name", "Someone")
        origin = "Telegram" if from_telegram else "web"
        text = f"{name} ({origin}): {data['text']}" if data["sender_type"] == "user" else data["text"]
    except KeyError:
        return
    for chat in chats:
        try:
            c.send_message(chat, text, _keyboard(meta.get("conflict_ids") or []))
        except TelegramError:
            log.warning("Telegram forward failed for trip %s (chat %s)", trip_id, chat)   # one bad chat must not block the rest


async def on_event(trip_id: int, event: dict) -> None:
    await anyio.to_thread.run_sync(_forward, trip_id, event)
