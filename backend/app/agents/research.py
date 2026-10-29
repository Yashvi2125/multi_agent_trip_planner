"""Research Agent. Tool-driven, never invents places: curated data is the backbone,
live APIs enrich it, and every failure is recorded in `notes` so the planner can be honest."""
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.agents.dynamic_research import DynamicOutcome, DynamicResearcher, sources_note
from app.tools.base import GeocodeProvider, ToolError, WeatherDay, WeatherProvider
from app.tools.curated import Destination, Place, find_destination, place_open_on, supported_destinations
from app.tools.weather import within_forecast_range

log = logging.getLogger("wayfare.research")


@dataclass
class ExcludedPlace:
    place: Place
    reason: str


@dataclass
class ResearchBundle:
    supported: bool
    destination: Destination | None = None
    places: list[Place] = field(default_factory=list)
    excluded: list[ExcludedPlace] = field(default_factory=list)
    weather: list[WeatherDay] = field(default_factory=list)
    weather_source: str = "none"  # live | climatology | none
    notes: list[str] = field(default_factory=list)  # human-readable caveats, shown to the group
    degraded: bool = False
    source: str = "curated"   # curated | researched: where the destination data came from
    reason: str = ""          # why no plan can be built (unrecognized | too_broad | insufficient | unavailable)


def _trip_days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def availability(dest: Destination, start: date, end: date) -> tuple[list[Place], list[ExcludedPlace]]:
    days = _trip_days(start, end)
    ok, out = [], []
    for p in dest.places:
        if any(place_open_on(p, d) for d in days):
            ok.append(p)
        else:
            why = (f"{p.name} isn't available in {days[0]:%B}." if p.closed_months and not p.only_days
                   else f"{p.name} doesn't run on any of your trip days.")
            out.append(ExcludedPlace(p, why))
    return ok, out


def resolve_destination(name: str, dynamic: DynamicResearcher | None = None) -> Destination | None:
    """Curated data first; otherwise whatever the researcher already has cached. Never triggers research."""
    return find_destination(name) or (dynamic.cached(name) if dynamic is not None else None)


_SETTINGS = ("To get a plan, change the trip's destination in Settings, or start a new trip for it. "
             "Everyone's preferences stay saved either way.")


def _fallback(destination: str, outcome: DynamicOutcome) -> ResearchBundle:
    """A specific, useful answer for a destination we recognise but can't plan (yet), instead of a flat 'unsupported'."""
    shown = destination or "that destination"
    name = outcome.place_name or shown
    message = {
        "unrecognized": f"I couldn't find “{shown}” on the map. Check the spelling, or try a nearby city.",
        "too_broad": f"“{shown}” is a whole country or large region, which is too big to plan day by day. "
                     f"Pick a city or area inside it.",
        "insufficient": f"I can recognize {name}, but I couldn't gather enough reliable information to build a "
                        f"complete plan yet. You can add preferences in chat or try another destination.",
        "unavailable": f"I couldn't reach the map and research services just now, so I can't plan {shown} yet. "
                       f"Try again in a few minutes.",
    }[outcome.status]
    bundle = ResearchBundle(supported=False, degraded=True, reason=outcome.status)
    bundle.notes += [message, f"I already know {', '.join(supported_destinations())} in depth. {_SETTINGS}"]
    return bundle


def research(destination: str, start: date | None, end: date | None,
             weather: WeatherProvider, geocoder: GeocodeProvider | None = None,
             today: date | None = None, dynamic: DynamicResearcher | None = None,
             resolved: Destination | None = None) -> ResearchBundle:
    today = today or date.today()
    dest = resolved or find_destination(destination)
    if dest is None and dynamic is not None:        # not curated: research it from real providers
        outcome = dynamic.research(destination)
        if outcome.destination is None:
            return _fallback(destination, outcome)
        dest = outcome.destination
    if dest is None:
        # No researcher configured on this server: only curated destinations can be planned.
        bundle = ResearchBundle(supported=False, degraded=True, reason="unconfigured")
        options = ", ".join(supported_destinations())
        bundle.notes.append(f"I can't research {destination or 'that destination'} on this server yet, "
                            f"so right now I can only plan trips to {options}.")
        if geocoder:  # still useful to confirm the place exists
            try:
                if (pt := geocoder.geocode(destination)):
                    bundle.notes.append(f"I found it on the map ({pt.label.split(',')[0]}), but can't build an itinerary there yet.")
            except ToolError:
                log.warning("geocode failed for unsupported destination")
        # Say what to do next. Preferences are stored per trip, so switching destination loses nothing.
        bundle.notes.append("To get a plan, change the trip's destination in Settings to one of those, or start a new "
                            "trip for it. Everyone's preferences stay saved either way.")
        return bundle

    bundle = ResearchBundle(supported=True, destination=dest, source=dest.source)
    if dest.source == "researched" and dest.places:   # say plainly what is fact and what is estimate
        bundle.notes.append(sources_note(dest))

    # Which places can actually be visited on these dates?
    if start and end:
        days = _trip_days(start, end)
        bundle.places, bundle.excluded = availability(dest, start, end)
        weather_days = days
    else:
        bundle.places = list(dest.places)
        bundle.notes.append("Trip dates aren't set yet, so I haven't checked seasonal closures or the forecast.")
        weather_days = []

    # Weather: live forecast when in range, typical climate otherwise, and honesty when both fail
    if weather_days:
        if within_forecast_range(start, end, today):
            try:
                bundle.weather = weather.forecast(dest.lat, dest.lon, start, end)
                bundle.weather_source = "live"
            except ToolError:
                bundle.degraded = True
                bundle.notes.append("I couldn't reach the weather service, so this plan uses typical conditions instead of a live forecast."
                                    if dest.has_climate() else
                                    "I couldn't reach the weather service, so this plan has no forecast.")
        elif dest.has_climate():
            bundle.notes.append(f"Your trip is too far out for a live forecast, so I'm using typical conditions for {start:%B}.")
        else:
            bundle.notes.append(f"Your trip is too far out for a live forecast, and I couldn't find typical conditions for {dest.name}.")
        if bundle.weather_source != "live" and dest.has_climate():
            c = dest.climate_for(start.month)
            bundle.weather = [WeatherDay(d, {"low": "Mostly dry", "moderate": "Chance of showers", "heavy": "Heavy rain likely"}[c.rain],
                                         float(c.hi), float(c.lo), None) for d in weather_days]
            bundle.weather_source = "climatology"
        if dest.has_climate() and dest.climate_for(start.month).rain == "heavy":
            bundle.notes.append(f"{start:%B} was very wet in {dest.name} last year, so outdoor plans may need a backup."
                                if dest.source == "researched" else
                                f"{start:%B} is monsoon season in {dest.name}. Outdoor plans may need a backup.")
        if dest.is_peak(start.month):
            bundle.notes.append(f"{start:%B} is peak season in {dest.name}, so stays cost roughly {int((dest.peak_multiplier - 1) * 100)}% more than usual.")
    return bundle
