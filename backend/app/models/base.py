import enum
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Enum
from sqlalchemy.dialects.postgresql import JSONB

# JSONB on Postgres, plain JSON elsewhere (keeps tests runnable on SQLite)
JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def TZDateTime() -> DateTime:
    return DateTime(timezone=True)


def StrEnum(enum_cls: type[enum.Enum]) -> Enum:
    # Stored as VARCHAR + CHECK: simple migrations, no Postgres ENUM type juggling
    return Enum(enum_cls, native_enum=False, length=20, values_callable=lambda e: [m.value for m in e])


class TripStatus(str, enum.Enum):
    planning = "planning"
    researching = "researching"
    planned = "planned"
    locked = "locked"


class MemberRole(str, enum.Enum):
    creator = "creator"
    member = "member"


class Channel(str, enum.Enum):
    web = "web"
    telegram = "telegram"
    system = "system"


class SenderType(str, enum.Enum):
    user = "user"
    ai = "ai"
    system = "system"


class ConstraintType(str, enum.Enum):
    max_budget = "max_budget"
    dates = "dates"
    dietary = "dietary"
    accessibility = "accessibility"
    unavailable_day = "unavailable_day"
    must_include = "must_include"
    must_avoid = "must_avoid"


class ConflictStatus(str, enum.Enum):
    open = "open"
    accepted = "accepted"
    dismissed = "dismissed"
    resolved = "resolved"


class Vote(str, enum.Enum):
    accept = "accept"
    reject = "reject"
