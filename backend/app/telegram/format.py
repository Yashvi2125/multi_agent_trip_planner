"""Plain-text renderers for Telegram (no parse_mode: nothing to escape, nothing to break)."""
from decimal import Decimal

from app.core.money import format_inr
from app.models import Trip
from app.schemas.itinerary import Itinerary


def dates_text(trip: Trip) -> str:
    if trip.start_date and trip.end_date:
        return f"{trip.start_date.day} {trip.start_date:%b} to {trip.end_date.day} {trip.end_date:%b %Y}"
    return "dates not set yet"


def trip_summary(trip: Trip, members: int, web_url: str) -> str:
    budget = f"{format_inr(trip.group_budget)} group budget" if trip.group_budget else "no budget set"
    plan = f"plan version {trip.current_itinerary_version}" if trip.current_itinerary_version else "no plan yet"
    return (f"{trip.name}\n{trip.destination}, {dates_text(trip)}\n{members} travellers, {budget}, {plan}\n"
            f"Trip code: {trip.code}\nOpen it on the web: {web_url.rstrip('/')}/trip/{trip.id}")


def itinerary_text(it: Itinerary, version: int, budget: dict | None) -> str:
    head = f"{it.destination} plan, version {version}"
    if budget and budget.get("per_person"):
        head += f". About {format_inr(Decimal(budget['per_person']))} each."
    lines = [head, it.summary] if it.summary else [head]
    for d in it.days:
        when = f" ({d.date.strftime('%a')} {d.date.day} {d.date:%b})" if d.date else ""
        lines.append(f"\nDay {d.index}{when}: {d.title}")
        if d.note:
            lines.append(f"  {d.note}")
        if not d.items:
            lines.append("  Nothing scheduled, a free day.")
        for i in d.items:
            lines.append(f"  {i.start}  {i.name}{' (optional)' if i.optional else ''}")
    return "\n".join(lines)


HELP = """I plan group trips with you. Talk to each other normally and I'll pick up preferences quietly.
I only speak when you mention me (@planner), reply to me, or use a command.

/create Goa 2026-12-10 2026-12-14 60000  start a trip
/join CODE  join a trip (in a group, this connects the group)
/trip  trip summary
/itinerary  the current plan
/plan  build or update the plan
/budget  what it costs
/members  who's in
/link CODE  connect your Wayfare web account (get the code in Settings)"""
