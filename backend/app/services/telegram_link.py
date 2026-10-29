"""Linking a Telegram identity to a web account. The web user asks for a one-time code, then sends
`/link CODE` to the bot. Codes live in memory (single instance) and expire quickly."""
import secrets
import time

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import (ChecklistItem, ConflictVote, Constraint, Message, Preference, Trip, TripMember, User)
from app.services.trip_code import ALPHABET

TTL_SECONDS = 600
_codes: dict[str, tuple[int, float]] = {}


def create_code(user_id: int) -> str:
    now = time.monotonic()
    for k in [k for k, (_, exp) in _codes.items() if exp < now]:
        _codes.pop(k, None)
    for k in [k for k, (uid, _) in _codes.items() if uid == user_id]:
        _codes.pop(k, None)             # one live code per person
    code = "".join(secrets.choice(ALPHABET) for _ in range(6))
    _codes[code] = (user_id, now + TTL_SECONDS)
    return code


def consume_code(code: str) -> int | None:
    entry = _codes.pop(code.strip().upper(), None)
    return entry[0] if entry and entry[1] >= time.monotonic() else None


def link_telegram(db: Session, web_user: User, tg_id: int, tg_username: str | None) -> str:
    """Attach a Telegram id to a web account, folding in the Telegram-only user if one already exists."""
    if web_user.telegram_id not in (None, tg_id):
        raise AppError("already_linked", "That Wayfare account is already linked to a different Telegram account.", 409)
    tg_user = db.scalar(select(User).where(User.telegram_id == tg_id))
    if tg_user and tg_user.id != web_user.id:
        if tg_user.email:
            raise AppError("tg_has_account", "That Telegram account already belongs to another Wayfare login.", 409)
        _merge(db, source=tg_user, target=web_user)
    web_user.telegram_id, web_user.telegram_username = tg_id, tg_username
    db.commit()
    return web_user.name


def _merge(db: Session, source: User, target: User) -> None:
    """Move everything the Telegram-only user did onto the web account, then delete the stub."""
    mine = {m.trip_id for m in db.scalars(select(TripMember).where(TripMember.user_id == target.id))}
    for m in list(db.scalars(select(TripMember).where(TripMember.user_id == source.id))):
        if m.trip_id in mine:
            db.delete(m)                   # already a member on the web side
        else:
            m.user_id = target.id
    voted = {v.conflict_id for v in db.scalars(select(ConflictVote).where(ConflictVote.user_id == target.id))}
    for v in list(db.scalars(select(ConflictVote).where(ConflictVote.user_id == source.id))):
        if v.conflict_id in voted:
            db.delete(v)
        else:
            v.user_id = target.id
    for model, col in ((Message, "sender_user_id"), (Preference, "user_id"), (Constraint, "user_id"),
                       (ChecklistItem, "done_by"), (Trip, "creator_id")):
        db.execute(update(model).where(getattr(model, col) == source.id).values({col: target.id}))
    source.telegram_id = None
    db.flush()                              # free the unique telegram_id before reuse
    db.delete(source)
    db.flush()
