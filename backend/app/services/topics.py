"""Canonical topics so "clubs", "party" and "nightlife" are recognised as the same thing.
Conflict detection compares canonical topics, never raw LLM strings."""
import re

CANONICAL: dict[str, tuple[str, ...]] = {
    "nightlife": ("nightlife", "night life", "club", "clubs", "clubbing", "party", "partying", "pub", "pubs", "bar", "bars"),
    "beaches": ("beach", "beaches", "seaside", "sunbathing"),
    "adventure": ("adventure", "trek", "trekking", "hiking", "rafting", "water sports", "watersports", "paragliding", "scuba"),
    "culture": ("culture", "heritage", "history", "historical", "fort", "forts", "museum", "museums", "temples"),
    "food": ("food", "foodie", "street food", "local cuisine", "restaurants", "seafood"),
    "relaxation": ("relax", "relaxing", "relaxation", "chill", "spa", "slow", "quiet", "peaceful"),
    "nature": ("nature", "waterfall", "waterfalls", "wildlife", "scenic", "mountains"),
    "shopping": ("shopping", "markets", "market", "souvenirs"),
    "cafes": ("cafe", "cafes", "coffee"),
}
_LOOKUP = {alias: topic for topic, aliases in CANONICAL.items() for alias in aliases}


def normalize_topic(raw: str) -> str:
    t = re.sub(r"[^a-z0-9 ]", " ", raw.lower()).strip()
    t = re.sub(r"\s+", " ", t)
    if t in _LOOKUP:
        return _LOOKUP[t]
    for word in t.split():  # "late night clubs" → nightlife
        if word in _LOOKUP:
            return _LOOKUP[word]
    return t
