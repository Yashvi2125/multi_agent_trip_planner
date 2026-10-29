from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.base import Channel, MemberRole, SenderType, TripStatus
from app.schemas.auth import UserOut


class TripCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    destination: str = Field(min_length=2, max_length=120)
    start_date: date | None = None
    end_date: date | None = None
    group_budget: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)

    @field_validator("name", "destination")
    @classmethod
    def strip(cls, v: str) -> str:
        return v.strip()

    @model_validator(mode="after")
    def dates_in_order(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("The trip can't end before it starts")
        return self


class JoinIn(BaseModel):
    code: str = Field(min_length=3, max_length=12)

    @field_validator("code")
    @classmethod
    def normalize(cls, v: str) -> str:
        return v.strip().upper()


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user: UserOut
    role: MemberRole
    joined_via: Channel
    joined_at: datetime


class TripOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    destination: str
    start_date: date | None
    end_date: date | None
    group_budget: Decimal | None
    currency: str
    status: TripStatus
    current_itinerary_version: int
    creator_id: int | None = None
    member_count: int = 0


class TripDetail(TripOut):
    members: list[MemberOut]
    telegram_connected: bool = False


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Message can't be empty")
        return v


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    trip_id: int
    sender_type: SenderType
    source: Channel
    text: str
    created_at: datetime
    sender: UserOut | None = None
    reply_to_id: int | None = None       # lets a client match an AI answer to the question that caused it
    meta: dict | None = None             # e.g. {"conflict_ids": [...]} or {"version": 2}
