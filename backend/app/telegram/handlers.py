"""The Telegram channel adapter. Everything channel-specific lives here: it turns a Telegram update into the
same calls the web uses (chat_service, trip_service, conflict_votes, planner), then returns."""
import logging
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import database
from app.core.config import get_settings
from app.core.errors import AppError
from app.models import Channel, Message, SenderType, Trip, TripMember, User, Vote
from app.schemas.trip import MessageOut, TripCreate
from app.services import chat_service, conflict_votes, itinerary_service, telegram_link, trip_service
from app.services.event_hub import hub
from app.telegram import format as fmt
from app.telegram import service
from app.telegram.client import TelegramError

log = logging.getLogger("wayfare.telegram")
Schedule = Callable[[int, int, str | None], None]     # (trip_id, message_id, command) → run the planner later
GROUPS = ("group", "supergroup")
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_TEXT = 2000


# ------------------------------------------------------------------ identity & trips

def get_or_create_user(db: Session, tg: dict) -> User:
    user = db.scalar(select(User).where(User.telegram_id == tg["id"]))
    name = " ".join(x for x in (tg.get("first_name"), tg.get("last_name")) if x) or tg.get("username") or f"Traveller {tg['id']}"
    if user is None:
        user = User(name=name[:80], telegram_id=tg["id"], telegram_username=tg.get("username"))
        db.add(user)
    elif tg.get("username") and user.telegram_username != tg.get("username"):
        user.telegram_username = tg["username"]
    db.commit()
    return user


def trip_for_chat(db: Session, chat: dict, user: User) -> Trip | None:
    if chat["type"] in GROUPS:
        return db.scalar(select(Trip).where(Trip.telegram_chat_id == chat["id"]))
    latest = db.scalar(select(TripMember).where(TripMember.user_id == user.id).order_by(TripMember.joined_at.desc(), TripMember.id.desc()))
    return db.get(Trip, latest.trip_id) if latest else None


def _announce_join(db: Session, trip: Trip, user: User) -> None:
    note = Message(trip_id=trip.id, sender_type=SenderType.system, source=Channel.system,
                   text=f"{user.name} joined the trip from Telegram.", meta={"origin": "telegram", "user_id": user.id})
    db.add(note)
    db.commit()
    hub.publish_threadsafe(trip.id, {"type": "member.joined", "data": {"user_id": user.id, "name": user.name}})
    hub.publish_threadsafe(trip.id, {"type": "message.new", "data": MessageOut.model_validate(note).model_dump(mode="json")})


def _ensure_member(db: Session, trip: Trip, user: User) -> None:
    _, joined = trip_service.join_trip(db, user, trip.code, Channel.telegram)
    if joined:
        _announce_join(db, trip, user)


def _bind(db: Session, trip: Trip, chat: dict) -> str | None:
    """Connect a Telegram group to a trip. Returns an error message if it can't."""
    if chat["type"] not in GROUPS:
        return None
    if trip.telegram_chat_id == chat["id"]:
        return None
    if trip.telegram_chat_id is not None:
        return "That trip is already connected to a different Telegram group."
    other = db.scalar(select(Trip).where(Trip.telegram_chat_id == chat["id"]))
    if other:
        return f"This group is already connected to {other.name} ({other.code})."
    trip.telegram_chat_id = chat["id"]
    db.commit()
    return None


# ------------------------------------------------------------------ commands

def _money(tok: str) -> Decimal | None:
    t = tok.replace(",", "").replace("₹", "").lower()
    mult = 1000 if t.endswith("k") else 1
    try:
        v = Decimal(t.rstrip("k")) * mult
    except InvalidOperation:
        return None
    return v if v > 0 else None


TRIP_COMMANDS = {"trip", "members", "itinerary", "plan", "regenerate", "budget"}
CREATE_USAGE = "Try: /create Goa 2026-12-10 2026-12-14 60000  (destination, start, end, group budget)"


def cmd_create(db: Session, user: User, chat: dict, args: str) -> str:
    toks = args.split()
    dest_words = []
    while toks and not ISO.match(toks[0]) and _money(toks[0]) is None:
        dest_words.append(toks.pop(0))
    if not dest_words:
        return "Where are you going? " + CREATE_USAGE
    start = end = budget = None
    try:
        if toks and ISO.match(toks[0]):
            start = date.fromisoformat(toks.pop(0))
            if not (toks and ISO.match(toks[0])):
                return "I need both a start and an end date. " + CREATE_USAGE
            end = date.fromisoformat(toks.pop(0))
        if toks:
            budget = _money(toks.pop(0))
            if budget is None:
                return "I couldn't read that budget. " + CREATE_USAGE
        dest = " ".join(dest_words)
        data = TripCreate(name=f"{dest} trip", destination=dest, start_date=start, end_date=end, group_budget=budget)
    except (ValueError, Exception) as e:   # noqa: BLE001  (pydantic ValidationError subclasses ValueError)
        return f"Those details don't look right ({str(e).splitlines()[-1][:80]}). " + CREATE_USAGE
    trip = trip_service.create_trip(db, user, data)
    trip.members[0].joined_via = Channel.telegram
    db.commit()
    bound = _bind(db, trip, chat) is None and chat["type"] in GROUPS
    web = get_settings().public_web_url.rstrip("/")
    tail = ("This group is now connected. Everyone who writes here joins the trip automatically."
            if bound else "Add me to your group chat and send /join " + trip.code + " there.")
    return (f"Your {trip.destination} trip is ready. Trip code: {trip.code}\n{tail}\n"
            f"Friends on the web can join at {web}/join/{trip.code}")


def cmd_join(db: Session, user: User, chat: dict, code: str) -> str:
    if not code.strip():
        return "Send /join followed by the trip code, like /join GOA-4X7."
    try:
        trip, joined = trip_service.join_trip(db, user, code, Channel.telegram)
    except AppError as e:
        return e.message
    problem = _bind(db, trip, chat)
    if joined:
        _announce_join(db, trip, user)
    n = db.query(TripMember).filter_by(trip_id=trip.id).count()
    out = f"{'You are in' if joined else 'You are already in'}, {user.name.split()[0]}. {trip.name}: {trip.destination}, {fmt.dates_text(trip)}, {n} travellers."
    if chat["type"] in GROUPS and not problem:
        out += " This group is connected, so I'll keep the plan in sync with everyone on the web."
    return out + (f"\n{problem}" if problem else "")


def cmd_link(db: Session, user: User, tg: dict, code: str) -> str:
    uid = telegram_link.consume_code(code) if code.strip() else None
    web_user = db.get(User, uid) if uid else None
    if not web_user:
        return "That link code didn't work. Get a fresh one under Settings on the web and send it within 10 minutes."
    try:
        name = telegram_link.link_telegram(db, web_user, tg["id"], tg.get("username"))
    except AppError as e:
        return e.message
    return f"Linked. You're now {name} on Wayfare, and your Telegram chats show under that account."


def _run_as_user(db: Session, trip: Trip, user: User, text: str, command: str, schedule: Schedule) -> None:
    _ensure_member(db, trip, user)
    msg = chat_service.post_user_message(db, trip.id, user, text, Channel.telegram)
    hub.publish_threadsafe(trip.id, {"type": "message.new", "data": MessageOut.model_validate(msg).model_dump(mode="json")})
    schedule(trip.id, msg.id, command)


def handle_command(db: Session, cmd: str, args: str, user: User, tg: dict, chat: dict, schedule: Schedule) -> str | None:
    if cmd == "start":
        return cmd_join(db, user, chat, args) if args.strip() else (
            "Hi, I'm the Wayfare trip planner. " + ("Send /join with your trip code, or /create to start one. /help shows everything."))
    if cmd == "help":
        return fmt.HELP
    if cmd == "create":
        return cmd_create(db, user, chat, args)
    if cmd == "join":
        return cmd_join(db, user, chat, args)
    if cmd == "link":
        return cmd_link(db, user, tg, args)
    if cmd not in TRIP_COMMANDS:
        return "I don't know that one. /help lists what I can do."
    trip = trip_for_chat(db, chat, user)
    if trip is None:
        return ("This group isn't connected to a trip yet. Send /join with your trip code." if chat["type"] in GROUPS
                else "You're not on a trip yet. Send /join with a trip code, or /create to start one.")
    if cmd == "trip":
        return fmt.trip_summary(trip, db.query(TripMember).filter_by(trip_id=trip.id).count(), get_settings().public_web_url)
    if cmd == "members":
        rows = db.scalars(select(TripMember).where(TripMember.trip_id == trip.id).order_by(TripMember.id))
        return "On this trip:\n" + "\n".join(f"{m.user.name} ({'creator, ' if m.role.value == 'creator' else ''}{m.joined_via.value})" for m in rows)
    if cmd == "itinerary":
        row = itinerary_service.latest(db, trip.id)
        if not row:
            return "There's no plan yet. Tell the group what you're after, then send /plan."
        return fmt.itinerary_text(itinerary_service.itinerary_of(row), row.version, row.budget_breakdown)
    if cmd in ("plan", "regenerate"):
        _run_as_user(db, trip, user, "Please update the plan.", "regenerate", schedule)
        return None
    _run_as_user(db, trip, user, "How much will this cost?", "budget", schedule)    # cmd == "budget"
    return None


# ------------------------------------------------------------------ plain chat

def normalise_text(text: str, bot_username: str, replying_to_bot: bool) -> tuple[str, bool]:
    """'@YourBot why Goa?' → '@planner why Goa?'. A reply to one of the bot's messages counts as addressing it."""
    text = text.strip()[:MAX_TEXT]
    mentioned = False
    if bot_username:
        text, n = re.subn(rf"@{re.escape(bot_username)}\b", "@planner", text, flags=re.I)
        mentioned = n > 0
    if replying_to_bot and "@planner" not in text.lower():
        text, mentioned = "@planner " + text, True
    return text, mentioned


def handle_chat(db: Session, text: str, user: User, chat: dict, schedule: Schedule, replying_to_bot: bool) -> str | None:
    trip = trip_for_chat(db, chat, user)
    text, mentioned = normalise_text(text, get_settings().telegram_bot_username, replying_to_bot)
    if trip is None:
        if mentioned or chat["type"] == "private":
            return "I'm not connected to a trip here yet. Send /join with your trip code, or /create to start one."
        return None                      # an unconnected group's chatter is none of our business
    _ensure_member(db, trip, user)       # in a connected group, speaking = joining
    msg = chat_service.post_user_message(db, trip.id, user, text, Channel.telegram)
    hub.publish_threadsafe(trip.id, {"type": "message.new", "data": MessageOut.model_validate(msg).model_dump(mode="json")})
    schedule(trip.id, msg.id, None)
    return None


# ------------------------------------------------------------------ inline-button votes

def handle_callback(db: Session, cb: dict) -> None:
    c = service.get_client()
    m = re.fullmatch(r"v:(\d+):(accept|reject)", cb.get("data", ""))
    if not (c and m):
        return
    user = get_or_create_user(db, cb["from"])
    cid, vote = int(m.group(1)), m.group(2)
    from app.models import Conflict
    conflict = db.get(Conflict, cid)
    try:
        if not conflict or not trip_service.is_member(db, conflict.trip_id, user.id):
            raise AppError("forbidden", "Join the trip first, then you can vote.", 403)
        _, t = conflict_votes.cast_vote(db, conflict.trip_id, cid, user, Vote(vote))
        reply = f"Vote recorded: {vote}. {t['accept']} for, {t['reject']} against so far."
    except AppError as e:
        reply = e.message
    try:
        c.answer_callback(cb["id"], reply)
    except TelegramError:
        log.warning("answerCallbackQuery failed")


# ------------------------------------------------------------------ entry point

def process_update(update: dict, schedule: Schedule) -> None:
    c = service.get_client()
    if c is None:
        return
    with database.SessionLocal() as db:
        if "callback_query" in update:
            return handle_callback(db, update["callback_query"])
        msg = update.get("message")
        if not msg or not msg.get("text") or not msg.get("from") or msg["from"].get("is_bot"):
            return
        chat, tg, text = msg["chat"], msg["from"], msg["text"]
        user = get_or_create_user(db, tg)
        replying_to_bot = bool((msg.get("reply_to_message") or {}).get("from", {}).get("id") == c.bot_id and c.bot_id)
        if text.startswith("/"):
            head, _, args = text.partition(" ")
            cmd, _, target = head[1:].partition("@")
            if target and get_settings().telegram_bot_username and target.lower() != get_settings().telegram_bot_username.lower():
                return                   # a command meant for a different bot in the same group
            reply = handle_command(db, cmd.lower(), args.strip(), user, tg, chat, schedule)
        else:
            reply = handle_chat(db, text, user, chat, schedule, replying_to_bot)
        if reply:
            try:
                c.send_message(chat["id"], reply)
            except TelegramError:
                log.warning("Could not reply on Telegram (chat %s)", chat["id"])
