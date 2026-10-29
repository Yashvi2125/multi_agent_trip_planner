"""Run the dynamic researcher against the REAL providers for one destination and print what it found.

    cd backend && python ../scripts/check_live_research.py "Tokyo"

Needs internet (Nominatim, Overpass, Open-Meteo). Set GEMINI_API_KEY in backend/.env to also get AI price
estimates; without it the costs fall back to a labelled generic baseline."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.agents.dynamic_research import DynamicResearcher, sources_note  # noqa: E402
from app.agents.llm import GeminiClient  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.tools.geocode import NominatimProvider  # noqa: E402
from app.tools.places import OverpassProvider  # noqa: E402
from app.tools.weather import OpenMeteoProvider  # noqa: E402


def main(query: str) -> int:
    s = get_settings()
    weather = OpenMeteoProvider()
    llm = GeminiClient() if s.gemini_api_key else None
    out = DynamicResearcher(NominatimProvider(), OverpassProvider(), climate=weather, llm=llm).research(query)
    print(f"status: {out.status}   recognised as: {out.place_name or '-'}")
    d = out.destination
    if d is None:
        print({"unrecognized": "The map doesn't know this name.", "too_broad": "Too large to plan day by day.",
               "insufficient": "Found the place but too few real attractions.",
               "unavailable": "A provider was unreachable (check your internet, or try again: Overpass is sometimes busy)."}[out.status])
        return 1
    print(f"{d.name}, {d.country}  ({d.lat:.3f}, {d.lon:.3f})   cost basis: {d.cost_basis}   AI estimates: {'yes' if llm else 'no (GEMINI_API_KEY not set)'}")
    print(f"\n{len(d.places)} places in {len(d.areas)} areas:")
    for a in d.areas:
        n = sum(1 for p in d.places if p.area == a.id)
        print(f"  - {a.name}: {n} places")
    print("\nTop places (name | topics | visit | hours | entry):")
    for p in d.places[:10]:
        hours = f"{p.opens}-{p.closes}" if p.opens else "hours unknown"
        print(f"  - {p.name} | {','.join(p.topics)} | {p.duration_min} min | {hours} | ₹{p.cost_pp}")
    print(f"\nclimate: {'12 months of observed data' if d.has_climate() else 'unavailable'}")
    print("\nWhat is fact and what is estimate:")
    for k, v in d.provenance.items():
        print(f"  {k:14} {v}")
    print(f"\nShown to the group:\n  {sources_note(d)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(" ".join(sys.argv[1:]) or "Tokyo"))
