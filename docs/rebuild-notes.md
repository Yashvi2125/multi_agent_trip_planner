# Milestone 6 rebuild notes

Three modules were lost (overwritten) and rebuilt from their consumers and the existing tests:
`backend/app/schemas/itinerary.py`, `backend/app/agents/itinerary.py`, `backend/app/agents/validator.py`.

The inherited tests (`test_itinerary.py`, `test_itinerary_rules.py`, `test_graph.py`) were the specification.
Everything below was **inferred**, not recovered. If you have the originals, diff against these.

## Inferred behaviour (pinned by tests unless noted)
- Day 1 starts at 12:00 (arrival); other days at 09:00; a one-day trip has no arrival rule and no stay cost.
- Items are placed in order with a 15-minute buffer plus the area-to-area drive, rounded up to a 15-minute grid.
  `start_time` from the LLM is a floor, never a command.
- **Not pinned by any original test (my choice):** a long excursion that opens early and is the first stop of a
  non-arrival day may start as early as 07:00 (needed for Rohtang: 7h, closes 15:00). Tested in `test_rebuild_checks.py`.
- `nightlife` means clubs/bars (`kind == "nightlife"`), so an evening market or a beach is not nightlife.
  This is data-agnostic: it works whether or not the curated data tags a place `nightlife`.
- Over-budget is a warning, not a violation: the plan is saved and the shortfall is stated.
- The LLM draft is accepted if at least one grounded place survives; otherwise the rule-based planner runs.
  Empty days from a thin LLM draft are left as free days (not topped up).
- Budget trims are silent in `dropped` (a decision, not a failure). Unknown ids, duplicates, closed places and
  timing failures are reported.

## Known leftovers (not touched)
- `backend/app/services/itinerary_logic.py`, `budget_plan.py`, `plan_service.py`, `app/agents/responder.py` and
  `tests/harness.py` belong to an earlier, abandoned design. Nothing imports them and they reference schema names
  that no longer exist. Safe to delete.
- `_my_m6_attempt/` held stale copies of superseded files. Safe to delete.
