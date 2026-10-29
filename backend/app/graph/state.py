from typing import Any, TypedDict


class TripState(TypedDict, total=False):
    """JSON-friendly on purpose: it is checkpointed. Heavy objects (DB session, research bundle,
    typed itinerary) live in the per-run RunContext instead."""
    trip_id: int
    message_id: int
    sender_id: int
    sender_name: str
    text: str
    addressed: bool
    command: str | None
    intent: str
    has_itinerary: bool
    # extraction
    extract_failed: bool
    added_prefs: list[str]
    added_constraints: list[str]
    changed_mind: list[str]
    hard_acks: list[str]
    # conflicts
    new_conflicts: list[dict[str, Any]]
    resolved_conflicts: list[dict[str, Any]]
    plan_request: bool
    stale: bool
    # planning
    blocked: str | None
    notes: list[str]
    excluded: list[str]
    avoid_ids: list[str]
    stay_tier: str | None
    food_tier: str | None
    transport_id: str | None
    loop_count: int
    trimmed: list[str]
    dropped: list[str]
    used_fallback: bool
    itinerary: dict[str, Any] | None
    budget: dict[str, Any] | None
    violations: list[str]
    warnings: list[str]
    coverage: dict[str, bool]
    version: int | None
    change_summary: str | None
    answer: str | None
    # output
    outbox: list[dict[str, Any]]
    events: list[dict[str, Any]]


def initial_state(trip_id: int, message_id: int, sender_id: int, sender_name: str, text: str,
                  addressed: bool, command: str | None) -> TripState:
    """Every key is set, so a re-used checkpoint thread can never leak values from a previous run."""
    return TripState(
        trip_id=trip_id, message_id=message_id, sender_id=sender_id, sender_name=sender_name, text=text,
        addressed=addressed, command=command, intent="chat", has_itinerary=False, extract_failed=False,
        added_prefs=[], added_constraints=[], changed_mind=[], hard_acks=[], new_conflicts=[],
        resolved_conflicts=[], plan_request=False, stale=False, blocked=None, notes=[], excluded=[],
        avoid_ids=[], stay_tier=None, food_tier=None, transport_id=None, loop_count=0, trimmed=[], dropped=[], used_fallback=False,
        itinerary=None, budget=None, violations=[], warnings=[], coverage={}, version=None,
        change_summary=None, answer=None, outbox=[], events=[])
