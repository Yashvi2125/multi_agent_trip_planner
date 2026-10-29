from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import (
    Channel, ConflictStatus, ConstraintType, JSONType, MemberRole, SenderType,
    StrEnum, TripStatus, TZDateTime, Vote, utcnow,
)
from app.models.user import User


class Trip(Base):
    __tablename__ = "trips"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    destination: Mapped[str] = mapped_column(String(120))
    start_date: Mapped[date | None]
    end_date: Mapped[date | None]
    group_budget: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    status: Mapped[TripStatus] = mapped_column(StrEnum(TripStatus), default=TripStatus.planning)
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    telegram_chat_id: Mapped[int | None] = mapped_column(unique=True)
    current_itinerary_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)

    members: Mapped[list["TripMember"]] = relationship(back_populates="trip", cascade="all, delete-orphan")


class TripMember(Base):
    __tablename__ = "trip_members"
    __table_args__ = (UniqueConstraint("trip_id", "user_id", name="uq_member_trip_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[MemberRole] = mapped_column(StrEnum(MemberRole), default=MemberRole.member)
    joined_via: Mapped[Channel] = mapped_column(StrEnum(Channel), default=Channel.web)
    joined_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)

    trip: Mapped[Trip] = relationship(back_populates="members")
    user: Mapped[User] = relationship()


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_trip_created", "trip_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"))
    sender_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    sender_type: Mapped[SenderType] = mapped_column(StrEnum(SenderType), default=SenderType.user)
    source: Mapped[Channel] = mapped_column(StrEnum(Channel), default=Channel.web)
    text: Mapped[str] = mapped_column(Text)
    reply_to_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"))
    meta: Mapped[dict | None] = mapped_column("metadata", JSONType)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)

    sender: Mapped[User | None] = relationship()


class Preference(Base):
    """Soft, per-member preference ("likes beaches")."""
    __tablename__ = "preferences"
    __table_args__ = (Index("ix_pref_trip_user", "trip_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    category: Mapped[str] = mapped_column(String(20))  # interest|dislike|style|food|stay
    value: Mapped[str] = mapped_column(String(200))
    weight: Mapped[int] = mapped_column(Integer, default=3)
    source_message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)


class Constraint(Base):
    """Hard constraint. user_id NULL = applies to the whole group."""
    __tablename__ = "constraints"
    __table_args__ = (Index("ix_constraint_trip", "trip_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    type: Mapped[ConstraintType] = mapped_column(StrEnum(ConstraintType))
    value: Mapped[dict] = mapped_column(JSONType)
    source_message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)


class Conflict(Base):
    __tablename__ = "conflicts"
    __table_args__ = (Index("ix_conflict_trip_status", "trip_id", "status"), Index("ix_conflict_trip_key", "trip_id", "key"))

    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40))
    key: Mapped[str] = mapped_column(String(160))  # stable identity, e.g. "topic_clash:nightlife"
    description: Mapped[str] = mapped_column(Text)
    involved_user_ids: Mapped[list] = mapped_column(JSONType, default=list)
    proposed_compromise: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ConflictStatus] = mapped_column(StrEnum(ConflictStatus), default=ConflictStatus.open)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(TZDateTime())


class ConflictVote(Base):
    __tablename__ = "conflict_votes"

    conflict_id: Mapped[int] = mapped_column(ForeignKey("conflicts.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    vote: Mapped[Vote] = mapped_column(StrEnum(Vote))


class AIAction(Base):
    """Audit trail + the raw material for 'why did you choose this?'."""
    __tablename__ = "ai_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    trigger_message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"))
    intent: Mapped[str | None] = mapped_column(String(40))
    agents_run: Mapped[list] = mapped_column(JSONType, default=list)
    reasoning: Mapped[dict | None] = mapped_column(JSONType)
    status: Mapped[str] = mapped_column(String(20), default="running")
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(TZDateTime())


class ItineraryVersion(Base):
    """Immutable snapshot. Every change creates a new row."""
    __tablename__ = "itinerary_versions"
    __table_args__ = (UniqueConstraint("trip_id", "version", name="uq_itin_trip_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    created_by_action_id: Mapped[int | None] = mapped_column(ForeignKey("ai_actions.id"))
    days: Mapped[list] = mapped_column(JSONType)
    budget_breakdown: Mapped[dict | None] = mapped_column(JSONType)
    meta: Mapped[dict | None] = mapped_column(JSONType)  # stay choice, coverage, warnings, within_budget
    change_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)


class ChecklistItem(Base):
    __tablename__ = "checklist_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(20), default="booking")  # booking|document|packing
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    done_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
