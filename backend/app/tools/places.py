"""Places from OpenStreetMap via the public Overpass API (free, no key). Everything returned is a real,
named map feature; we never make a place up. Notability is judged by how well documented a feature is."""
import re
import logging
import httpx
log = logging.getLogger("wayfare.places")

from app.core.config import get_settings
from app.tools.base import NearbyResult, Poi, Suburb, TTLCache, ToolError, http_client

SUBURB_KINDS = "suburb|neighbourhood|quarter|city_district|borough"
_LATIN = re.compile(r"[A-Za-z]")


MIN_NOTABLE = 15      # fewer well-documented places than this → also search the less-documented ones


def build_query(
    lat: float,
    lon: float,
    radius_m: int,
    notable_only: bool = False,
) -> str:
    # The caller already chooses the scan radius; avoid shrinking a valid city-sized query.
    radius_m = max(int(radius_m), 4000)
    a = f"(around:{radius_m},{lat:.5f},{lon:.5f})"
    notable = '["wikidata"]' if notable_only else ''

    return f"""[out:json][timeout:20];
(
  nwr{a}["tourism"~"^(attraction|museum|viewpoint|zoo|theme_park|aquarium|gallery)$"]["name"]{notable};
  nwr{a}["historic"]["name"]{notable};
  nwr{a}["natural"~"^(beach|waterfall|peak|volcano|hot_spring|cave_entrance)$"]["name"]{notable};
  nwr{a}["leisure"~"^(park|garden|nature_reserve)$"]["name"]{notable};
  nwr{a}["amenity"="place_of_worship"]["name"]{notable};
  nwr{a}["amenity"="marketplace"]["name"]{notable};
);
out center tags 100;
"""


def _name(tags: dict) -> str:
    # Prefer an English/international name so the plan reads naturally; fall back to the local one.
    return (tags.get("name:en") or tags.get("int_name") or tags.get("name") or "").strip()


def _notability(tags: dict) -> float:
    s = 0.0
    s += 3 if "wikidata" in tags else 0
    s += 2 if "wikipedia" in tags else 0
    s += 1 if (tags.get("website") or tags.get("contact:website")) else 0
    s += 1 if tags.get("heritage") else 0
    s += 1 if tags.get("tourism") in ("attraction", "museum") else 0
    s += 0.5 if tags.get("opening_hours") else 0
    s += 0.25 if _LATIN.search(_name(tags)) else 0       # tie-break toward names readers can use
    return s


def parse(data: dict, max_pois: int = 60) -> NearbyResult:
    pois: dict[str, Poi] = {}
    suburbs: dict[str, Suburb] = {}
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        name = _name(tags)
        pos = el if "lat" in el else el.get("center") or {}
        if len(name) < 3 or "lat" not in pos or "lon" not in pos:
            continue
        if tags.get("place") and tags["place"] in SUBURB_KINDS.split("|"):
            suburbs.setdefault(name.lower(), Suburb(name, float(pos["lat"]), float(pos["lon"])))
            continue
        poi = Poi(f"{el.get('type', 'node')}/{el.get('id', 0)}", name, float(pos["lat"]), float(pos["lon"]), tags,
                  _notability(tags))
        key = name.lower()
        if key not in pois or poi.score > pois[key].score:     # the same sight is often mapped several times
            pois[key] = poi
    ranked = sorted(pois.values(), key=lambda p: (-p.score, p.name))
    return NearbyResult(pois=ranked[:max_pois], suburbs=sorted(suburbs.values(), key=lambda s: s.name))



class OverpassProvider:
    URLS = (
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)

    def __init__(
        self,
        transport: httpx.BaseTransport | None = None,
        cache: TTLCache | None = None,
    ):
        self._http = http_client(
            transport,
            timeout=get_settings().overpass_timeout_seconds,
        )
        self._cache = cache or TTLCache(24 * 3600)

    
    def _fetch(
        self,
        lat: float,
        lon: float,
        radius_m: int,
        notable_only: bool,
    ) -> NearbyResult:
        for url in self.URLS:
            try:
                response = self._http.post(
                    url,
                    data={
                        "data": build_query(
                            lat, lon, radius_m, notable_only
                        )
                    },
                    timeout=35.0,
                )
                response.raise_for_status()
                data = response.json()
                result = parse(data)

                if result.pois:
                    log.info(
                        "Overpass returned %d places from %s",
                        len(result.pois),
                        url,
                    )
                    return result

                log.warning(
                    "Overpass returned zero places: %s; response elements=%d",
                    url,
                    len(data.get("elements", [])),
                )

            except (
                httpx.HTTPError,
                ValueError,
                TypeError,
                AttributeError,
            ) as exc:
                log.warning(
                    "Overpass endpoint failed: %s (%s)",
                    url,
                    type(exc).__name__,
                )

        raise ToolError(
            "Places lookup failed: all Overpass endpoints timed out or returned no usable places"
        )

    def nearby(
        self,
        lat: float,
        lon: float,
        radius_m: int,
    ) -> NearbyResult:
        radius_m = max(int(radius_m), 4000)
        key = (round(lat, 3), round(lon, 3), radius_m)

        hit = self._cache.get(key)
        if hit is not None:
            return hit

        result = self._fetch(lat, lon, radius_m, notable_only=True)
        if len(result.pois) < MIN_NOTABLE:
            widened = self._fetch(lat, lon, radius_m, notable_only=False)
            if len(widened.pois) > len(result.pois):
                result = widened

        self._cache.set(key, result)
        return result
