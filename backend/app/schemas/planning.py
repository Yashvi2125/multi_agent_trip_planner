from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.base import ConflictStatus
from app.schemas.itinerary import Itinerary


class ItineraryOut(BaseModel):
    version: int
    change_summary: str | None
    created_at: datetime
    itinerary: Itinerary
    budget: dict[str, Any] | None


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    version: int
    change_summary: str | None
    created_at: datetime


class ConflictOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    description: str
    proposed_compromise: str | None
    involved_user_ids: list[int]
    status: ConflictStatus
    created_at: datetime
    accept_votes: int = 0
    reject_votes: int = 0
    my_vote: str | None = None


class PreferenceOut(BaseModel):
    user_id: int
    user_name: str
    category: str
    value: str
    weight: int


class ConstraintOut(BaseModel):
    user_id: int | None
    user_name: str | None
    type: str
    value: dict[str, Any]


class PreferencesOut(BaseModel):
    preferences: list[PreferenceOut]
    constraints: list[ConstraintOut]


class ExplainIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)

    @field_validator("question")
    @classmethod
    def strip(cls, v: str) -> str:
        return v.strip()


class VoteIn(BaseModel):
    vote: Literal["accept", "reject"]


class TripUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    destination: str | None = Field(default=None, min_length=2, max_length=120)
    start_date: date | None = None
    end_date: date | None = None
    group_budget: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)


class ChecklistOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    label: str
    category: str
    done: bool


class ChecklistPatch(BaseModel):
    done: bool


class ChecklistIn(BaseModel):
    label: str = Field(min_length=2, max_length=200)
    category: Literal["booking", "document", "packing"] = "booking"
