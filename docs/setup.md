# Setup

## Prerequisites
Python 3.10+, Docker (for PostgreSQL), Node 18+ (frontend, later milestone).

## Backend
```bash
docker compose up -d db
cp .env.example .env            # then set JWT_SECRET
cd backend
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```
API docs: http://localhost:8000/docs

## Tests (use in-memory SQLite, no Postgres needed)
```bash
cd backend && python -m pytest -q
```

## LLM
Set `GEMINI_API_KEY` (and optionally `GEMINI_MODEL`) in `.env`. Tests never call the network.

## External tools
- Weather: Open-Meteo (no key). Live forecast only for trips within 16 days; later trips use typical climate.
- Geocoding: Nominatim/OSM (no key; cached; real User-Agent required by their policy).
- Places and costs: curated JSON in `backend/app/data/curated/` (Goa, Jaipur, Manali).
  Figures are planning estimates. Verify before relying on them.

## Destinations: hand-checked and researched
Any destination can be planned. Wayfare picks the source automatically:

1. **Curated** (Goa, Jaipur, Manali, Bali): data in `backend/app/data/curated/*.json`. Used first, exactly as before,
   and no external research runs. This is the highest-quality path.
2. **Researched** (everything else): `DynamicResearcher` (`backend/app/agents/dynamic_research.py`) builds the same
   `Destination` object from real providers, so the LangGraph planner, budget, validator, Telegram and conflict code
   are unchanged:
   - geocode and validate the place (Nominatim). A whole country or region is rejected as too broad to plan day by day.
   - attractions and neighbourhoods from OpenStreetMap (Overpass), notable places (with a Wikidata entry) first;
   - last year's observed monthly weather (Open-Meteo archive);
   - **estimated**, and labelled as such: travel times (from distance), visit lengths, and every price. Prices come from
     one AI estimate (validated against sane ranges); if that is unavailable they fall back to a generic baseline,
     and the plan says so ("could be far off").

Opening hours are used only where OpenStreetMap lists them; otherwise they're unknown, never guessed.
If research can't find enough, the planner answers helpfully ("I can recognize X, but I couldn't gather enough reliable
information…") and saves nothing. Results are cached for 24 hours per destination (in memory).

Set `DYNAMIC_RESEARCH_ENABLED=false` to go back to curated-only (unknown destinations get the original message).

**Check the real providers from your machine** (the test suite uses fakes and needs no internet):
```bash
cd backend && python ../scripts/check_live_research.py "Tokyo"
```

### Adding a hand-checked destination (optional)
Drop a JSON file shaped like `bali.json` into `backend/app/data/curated/` (areas, a travel-time row for **every** pair
of areas including each area with itself, places with hours and costs, stay tiers, food and transport costs, climate,
checklist) and restart. `tests/test_tools.py` validates it (add its id to `DEST_IDS`). Curated data always wins over
research for that name. The Create-trip page suggests curated destinations from `GET /api/destinations`, but that
endpoint no longer limits what can be chosen. Costs and timings in curated files are planning estimates too.
