import httpx

from app.tools.base import GeoPoint, TTLCache, ToolError, haversine_km, http_client


class NominatimProvider:
    """OpenStreetMap geocoder. Usage policy: max 1 request/second and a real User-Agent, so we cache."""
    URL = "https://nominatim.openstreetmap.org/search"

    def __init__(self, transport: httpx.BaseTransport | None = None, cache: TTLCache | None = None):
        self._http = http_client(transport)
        self._cache = cache or TTLCache(24 * 3600)

    def geocode(self, query: str) -> GeoPoint | None:
        q = query.strip()
        if not q:
            return None
        if (hit := self._cache.get(q.lower())) is not None:
            return hit or None
        try:
            r = self._http.get(self.URL, params={"q": q, "format": "jsonv2", "limit": 1, "addressdetails": 1})
            r.raise_for_status()
            rows = r.json()
            point = _to_point(rows[0], q) if rows else None
        except (httpx.HTTPError, KeyError, ValueError, IndexError, TypeError) as e:
            raise ToolError(f"Geocoding failed: {type(e).__name__}") from e
        self._cache.set(q.lower(), point or False)  # remember misses too
        return point


def _to_point(row: dict, query: str) -> GeoPoint:
    extent = None
    try:
        south, north, west, east = (float(x) for x in row["boundingbox"])
        extent = haversine_km(south, west, north, east)
    except (KeyError, ValueError, TypeError):
        pass  # no box: we simply can't judge how large the place is
    addr = row.get("address") or {}
    return GeoPoint(float(row["lat"]), float(row["lon"]), row.get("display_name", query),
                    kind=row.get("addresstype") or row.get("type") or "", country=addr.get("country", ""),
                    country_code=addr.get("country_code", ""), extent_km=extent)
