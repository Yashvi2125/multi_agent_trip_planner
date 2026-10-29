"""LangGraph workflow. Channel-agnostic: it reads a normalised message and returns an outbox + events.
Nothing here knows about Telegram or WebSockets."""
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.agents.explainer import explain
from app.agents.itinerary import TIERS, cheapest_transport, cost_lines, plan_itinerary, required_places, score
from app.agents.llm import LLMError
from app.agents.preference import extract_preferences
from app.agents.profile import GroupProfile, load_profile
from app.agents.research import ResearchBundle, availability, research, resolve_destination
from app.agents.router import classify
from app.agents.validator import ValidationReport, validate
from app.graph.deps import Deps
from app.graph.responder import compose, describe_constraint
from app.graph.state import TripState
from app.models import AIAction, Trip
from app.schemas.itinerary import Itinerary
from app.services import itinerary_service
from app.services.budget_calc import DISCRETIONARY_ORDER, BudgetResult, compute_budget
from app.services.conflict_service import sync_conflicts
from app.services.preference_service import apply_extraction

log = logging.getLogger("wayfare.graph")


@dataclass
class RunContext:
    db: Session
    deps: Deps
    trip: Trip
    action_id: int | None = None
    status: Callable[[str], None] = lambda _t: None
    profile: GroupProfile | None = None
    previous: Itinerary | None = None
    bundle: ResearchBundle | None = None
    itinerary: Itinerary | None = None
    budget: BudgetResult | None = None
    label_map: dict[str, str] = field(default_factory=dict)
    report: ValidationReport | None = None


def budget_to_dict(r: BudgetResult, lines) -> dict[str, Any]:
    return {"total": str(r.total), "per_person": str(r.per_person), "travelers": r.travelers, "status": r.status,
            "cap": None if r.cap is None else str(r.cap), "remaining": None if r.remaining is None else str(r.remaining),
            "over_by": str(r.over_by), "by_category": {k: str(v) for k, v in r.by_category.items()},
            "lines": [{"category": l.category, "label": l.label, "total": str(l.total(r.travelers))} for l in lines]}


def build_graph(ctx: RunContext, checkpointer=None):
    d, trip = ctx.deps, ctx.trip

    def n_days() -> int:
        return (trip.end_date - trip.start_date).days + 1

    # ---------------- nodes ----------------
    def load(s: TripState):
        ctx.profile = load_profile(ctx.db, trip)
        prev = itinerary_service.latest(ctx.db, trip.id)
        ctx.previous = itinerary_service.itinerary_of(prev)
        return {"has_itinerary": prev is not None}

    def route(s: TripState):
        return {"intent": classify(s["text"], s["addressed"], s.get("command"))}

    def extract(s: TripState):
        if d.llm is None:
            return {"extract_failed": True}
        try:
            result = extract_preferences(d.llm, s["text"], trip.destination, d.today())
        except LLMError as e:
            log.warning("Extraction skipped: %s", e)
            return {"extract_failed": True}
        out = apply_extraction(ctx.db, trip, s["sender_id"], s["message_id"], result)
        return {"added_prefs": out.added_preferences, "added_constraints": out.added_constraints,
                "changed_mind": out.changed_mind, "hard_acks": [describe_constraint(c) for c in out.new_constraints]}

    def conflicts(s: TripState):
        opened, resolved = sync_conflicts(ctx.db, trip)
        ctx.profile = load_profile(ctx.db, trip)
        changed = bool(s["added_prefs"] or s["added_constraints"])
        plan = s["intent"] == "plan" or (s["has_itinerary"] and changed and d.auto_replan)
        ev = [{"type": "conflict.new", "data": {"id": c.id, "kind": c.kind, "description": c.description,
                                                "compromise": c.proposed_compromise}} for c in opened]
        ev += [{"type": "conflict.resolved", "data": {"id": c.id}} for c in resolved]
        return {"new_conflicts": [{"id": c.id, "description": c.description, "compromise": c.proposed_compromise}
                                  for c in opened],
                "resolved_conflicts": [{"id": c.id} for c in resolved], "plan_request": plan,
                "stale": s["has_itinerary"] and changed and not plan, "events": s["events"] + ev}

    def research_node(s: TripState):
        ctx.status("Checking weather and places…")
        ctx.bundle = research(trip.destination, trip.start_date, trip.end_date, d.weather, d.geocoder, d.today(),
                              dynamic=d.dynamic)
        blocked = None
        if not ctx.bundle.supported:
            blocked = "unsupported"
        elif not (trip.start_date and trip.end_date):
            blocked = "no_dates"
        elif n_days() > get_max_days():
            blocked = "too_long"
        return {"blocked": blocked, "notes": ctx.bundle.notes, "excluded": [e.reason for e in ctx.bundle.excluded]}

    def itinerary_node(s: TripState):
        ctx.status("Putting the itinerary together…")
        it, dropped = plan_itinerary(d.llm, ctx.bundle, ctx.profile, trip.start_date, n_days(),
                                     set(s["avoid_ids"]), s["stay_tier"], ctx.previous,
                                     s["food_tier"], s["transport_id"])
        ctx.itinerary = it
        return {"dropped": dropped, "used_fallback": it.used_fallback}

    def budget_node(s: TripState):
        ctx.status("Working out costs…")
        lines, ctx.label_map = cost_lines(ctx.itinerary, ctx.bundle.destination, ctx.profile.travelers)
        ctx.budget = compute_budget(lines, ctx.profile.travelers, ctx.profile.cap)
        return {"budget": budget_to_dict(ctx.budget, lines)}

    def _cut_pool(s: TripState, requested: bool) -> list[tuple[Any, str]]:
        """Trim candidates. requested=False: items nobody asked for. requested=True: items someone wants,
        lowest group score first. Must-haves are never in either pool."""
        protected = {p.id for p in required_places(ctx.bundle, ctx.profile)[0]}
        avoid = set(s["avoid_ids"]) | protected
        places = {p.id: p for p in ctx.bundle.destination.places}
        wanted_by = {i.place_id: len(i.serves) for day in ctx.itinerary.days for i in day.items}
        rank = {c: n for n, c in enumerate(DISCRETIONARY_ORDER)}
        pool = [(l, ctx.label_map[l.label]) for l in ctx.budget.cut_candidates
                if (pid := ctx.label_map.get(l.label)) and pid not in avoid and (wanted_by.get(pid, 0) > 0) == requested]
        return sorted(pool, key=lambda x: (item_score(places[x[1]]) if requested else 0, rank[x[0].category],
                                           -x[0].total(ctx.budget.travelers)))

    def item_score(place) -> float:
        return score(place, ctx.profile)

    def _cuts(s: TripState) -> list[str]:
        return [l.label for l, _ in _cut_pool(s, False) + _cut_pool(s, True)]

    def _levers(s: TripState) -> dict[str, Any]:
        it, dest = ctx.itinerary, ctx.bundle.destination
        tier = s["stay_tier"] or (it.stay.tier if it.stay else None)
        food = s["food_tier"] or it.food_tier
        tr = s["transport_id"] or it.transport_id
        return {"tier": tier, "food": food, "transport": tr,
                "cheapest": cheapest_transport(dest, ctx.profile.travelers, len(it.days))}

    def _can_tighten(s: TripState) -> bool:
        lv = _levers(s)
        return bool(_cuts(s)) or (lv["tier"] in TIERS and TIERS.index(lv["tier"]) > 0) \
            or TIERS.index(lv["food"]) > 0 or lv["transport"] != lv["cheapest"]

    def budget_edge(s: TripState):
        if ctx.budget.status == "over" and s["loop_count"] < 2 and _can_tighten(s):
            return "tighten"
        return "validate"

    def tighten(s: TripState):
        """Budget feedback loop, gentlest first:
        pass 1: drop extras nobody asked for → if still short, pull stay/meals/transport levers.
        pass 2: only now trim things members asked for (lowest-scored first); must-haves are untouchable."""
        ctx.status("That's over budget, so I'm trimming the plan…")
        avoid, done, covered = set(s["avoid_ids"]), [], 0
        need = ctx.budget.over_by

        def cut_until_covered(pool):
            nonlocal covered
            for l, pid in pool:
                if covered >= need:
                    break
                avoid.add(pid)
                done.append(l.label)
                covered += l.total(ctx.budget.travelers)

        cut_until_covered(_cut_pool(s, False))
        if s["loop_count"] >= 1:
            cut_until_covered(_cut_pool(s, True))
        lv = _levers(s)
        tier, food, tr = lv["tier"], lv["food"], lv["transport"]
        if covered < need:
            if tier in TIERS and TIERS.index(tier) > 0:
                tier = TIERS[TIERS.index(tier) - 1]
                done.append("a more budget-friendly stay")
            if TIERS.index(food) > 0:
                food = TIERS[TIERS.index(food) - 1]
                done.append("simpler meals")
            if tr != lv["cheapest"]:
                tr = lv["cheapest"]
                done.append("cheaper local transport")
        return {"avoid_ids": sorted(avoid), "stay_tier": tier, "food_tier": food, "transport_id": tr,
                "loop_count": s["loop_count"] + 1, "trimmed": s["trimmed"] + done}

    def validate_node(s: TripState):
        ctx.report = validate(ctx.itinerary, ctx.bundle, ctx.profile, trip.start_date, n_days(), ctx.budget.status)
        return {"violations": ctx.report.violations, "warnings": ctx.report.warnings, "coverage": ctx.report.coverage,
                "itinerary": ctx.itinerary.model_dump(mode="json")}

    def persist(s: TripState):
        diff = itinerary_service.diff_summary(ctx.previous, ctx.itinerary)
        row = itinerary_service.save_version(ctx.db, trip, ctx.itinerary, s["budget"], diff, ctx.action_id)
        ev = [{"type": "itinerary.updated", "data": {"version": row.version, "change_summary": diff}},
              {"type": "budget.updated", "data": s["budget"]}]
        return {"version": row.version, "change_summary": diff, "events": s["events"] + ev}

    def explain_node(s: TripState):
        ctx.status("Looking at the plan…")
        row = itinerary_service.latest(ctx.db, trip.id)
        excluded: list[str] = []
        dest = resolve_destination(trip.destination, d.dynamic)
        if dest and trip.start_date and trip.end_date:
            excluded = [e.reason for e in availability(dest, trip.start_date, trip.end_date)[1]]
        trimmed: list[str] = []
        if row and row.created_by_action_id and (act := ctx.db.get(AIAction, row.created_by_action_id)) and act.reasoning:
            trimmed = act.reasoning.get("trimmed", [])
        text = explain(d.llm, s["text"], ctx.previous, row.budget_breakdown if row else None,
                       row.change_summary if row else None, [], excluded, dest, trimmed)
        return {"answer": text}

    def respond(s: TripState):
        it = ctx.itinerary or ctx.previous
        topics = ctx.profile.limited_topics if ctx.profile else set()
        first = s["sender_name"].split()[0] if s["sender_name"] else "there"
        return {"outbox": compose(s, ctx.itinerary if s["plan_request"] else it, first, topics)}

    def get_max_days() -> int:
        from app.core.config import get_settings
        return get_settings().max_trip_days

    # ---------------- edges ----------------
    g = StateGraph(TripState)
    for name, fn in [("load", load), ("route", route), ("extract", extract), ("conflicts", conflicts),
                     ("research", research_node), ("itinerary", itinerary_node), ("budget", budget_node),
                     ("tighten", tighten), ("validate", validate_node), ("persist", persist),
                     ("explain", explain_node), ("respond", respond)]:
        g.add_node(name, fn)
    g.add_edge(START, "load")
    g.add_edge("load", "route")
    g.add_conditional_edges("route", lambda s: "explain" if s["intent"] == "explain" else "extract",
                            {"explain": "explain", "extract": "extract"})
    g.add_edge("extract", "conflicts")
    g.add_conditional_edges("conflicts", lambda s: "research" if s["plan_request"] else "respond",
                            {"research": "research", "respond": "respond"})
    g.add_conditional_edges("research", lambda s: "respond" if s["blocked"] else "itinerary",
                            {"respond": "respond", "itinerary": "itinerary"})
    g.add_edge("itinerary", "budget")
    g.add_conditional_edges("budget", budget_edge, {"tighten": "tighten", "validate": "validate"})
    g.add_edge("tighten", "itinerary")        # the budget feedback loop (max 2 passes)
    g.add_conditional_edges("validate", lambda s: "persist" if not s["violations"] else "respond",
                            {"persist": "persist", "respond": "respond"})
    g.add_edge("persist", "respond")
    g.add_edge("explain", "respond")
    g.add_edge("respond", END)
    return g.compile(checkpointer=checkpointer)
