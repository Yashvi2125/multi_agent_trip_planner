from fastapi import APIRouter, Depends, Query

from app.agents.dynamic_research import MAX_EXTENT_KM
from app.api.deps import current_user
from app.core.rate_limit import rate_limit
from app.models import User
from app.services import planner_gateway
from app.tools.base import ToolError
from app.tools.curated import _all, find_destination

router = APIRouter(prefix="/api/destinations", tags=["destinations"])


@router.get("")
def destinations():
    """Suggestions: destinations with hand-checked data. Any other destination can be created and is researched on demand."""
    out = []
    for d in _all().values():
        dry = [c.month for c in d.climate if c.rain == "low"]
        out.append({"id": d.id, "name": d.name, "country": d.country, "places": len(d.places), "areas": len(d.areas),
                    "peak_months": d.peak_months, "dry_months": dry,
                    "highlights": [p.name for p in d.places if p.kind in ("sight", "activity")][:4]})
    return out


@router.get("/lookup", dependencies=[Depends(rate_limit(30, 60))])
def lookup(q: str = Query(min_length=2, max_length=120), _: User = Depends(current_user)):
    """Is this somewhere we can plan? Used for a gentle hint while typing; it never blocks creating a trip.
    status: curated | found | too_broad | not_found | unavailable | unchecked"""
    if (known := find_destination(q)) is not None:
        return {"query": q, "status": "curated", "name": known.name, "country": known.country}
    deps = getattr(planner_gateway.planner, "deps", None)
    if deps is None:
        from app.graph.deps import default_deps
        deps = default_deps()
    if deps.geocoder is None or getattr(deps, "dynamic", None) is None:
        return {"query": q, "status": "unchecked"}
    try:
        pt = deps.geocoder.geocode(q)
    except ToolError:
        return {"query": q, "status": "unavailable"}
    if pt is None:
        return {"query": q, "status": "not_found"}
    name = pt.label.split(",")[0].strip() or q
    broad = pt.extent_km is not None and pt.extent_km > MAX_EXTENT_KM
    return {"query": q, "status": "too_broad" if broad else "found", "name": name, "country": pt.country}
