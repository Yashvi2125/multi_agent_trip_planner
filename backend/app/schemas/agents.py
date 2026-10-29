"""Pydantic contracts for agent output. The LLM must fill these; code validates them."""
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ExtractedPreference(BaseModel):
    category: Literal["interest", "dislike", "style", "food", "stay"]
    topic: str = Field(min_length=1, max_length=100)
    weight: int = Field(default=3, ge=1, le=5)

    @field_validator("topic")
    @classmethod
    def clean(cls, v: str) -> str:
        return v.strip()


class ExtractedConstraint(BaseModel):
    type: Literal["max_budget", "dietary", "accessibility", "unavailable_day", "must_include", "must_avoid"]
    amount: Decimal | None = Field(default=None, gt=0)
    text: str | None = None
    dates: list[date] = Field(default_factory=list)
    applies_to_group: bool = False  # "our budget is 60k" vs "I can't spend more than 12k"

    @model_validator(mode="after")
    def has_required_payload(self):
        if self.type == "max_budget" and self.amount is None:
            raise ValueError("max_budget needs an amount")
        if self.type in ("dietary", "accessibility", "must_include", "must_avoid") and not (self.text or "").strip():
            raise ValueError(f"{self.type} needs text")
        if self.type == "unavailable_day" and not self.dates:
            raise ValueError("unavailable_day needs dates")
        return self


class ExtractionResult(BaseModel):
    """Empty lists are the right answer for small talk."""
    preferences: list[ExtractedPreference] = Field(default_factory=list)
    constraints: list[ExtractedConstraint] = Field(default_factory=list)
