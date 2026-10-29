from datetime import date, timedelta

import httpx

from app.tools.base import MonthClimate, TTLCache, ToolError, WeatherDay, http_client

# WMO weather interpretation codes → plain language
WMO = {0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Fog",
       51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 61: "Light rain", 63: "Rain", 65: "Heavy rain",
       71: "Light snow", 73: "Snow", 75: "Heavy snow", 80: "Rain showers", 81: "Rain showers", 82: "Heavy showers",
       95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm"}
FORECAST_HORIZON_DAYS = 16  # Open-Meteo's free forecast range


class OpenMeteoProvider:
    URL = "https://api.open-meteo.com/v1/forecast"
    ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

    def __init__(self, transport: httpx.BaseTransport | None = None, cache: TTLCache | None = None):
        self._http = http_client(transport)
        self._cache = cache or TTLCache(3 * 3600)
        self._climate_cache = TTLCache(30 * 24 * 3600)

    def forecast(self, lat: float, lon: float, start: date, end: date) -> list[WeatherDay]:
        key = (round(lat, 2), round(lon, 2), start, end)
        if (hit := self._cache.get(key)) is not None:
            return hit
        params = {"latitude": lat, "longitude": lon, "timezone": "auto",
                  "start_date": start.isoformat(), "end_date": end.isoformat(),
                  "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"}
        try:
            r = self._http.get(self.URL, params=params)
            r.raise_for_status()
            d = r.json()["daily"]
            days = [WeatherDay(date.fromisoformat(t), WMO.get(int(c), "Mixed conditions"), float(hi), float(lo),
                               None if rain is None else int(rain))
                    for t, c, hi, lo, rain in zip(d["time"], d["weather_code"], d["temperature_2m_max"],
                                                  d["temperature_2m_min"], d["precipitation_probability_max"])
                    if c is not None and hi is not None and lo is not None]
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as e:
            raise ToolError(f"Weather lookup failed: {type(e).__name__}") from e
        self._cache.set(key, days)
        return days

    def monthly_climate(self, lat: float, lon: float) -> list[MonthClimate]:
        """Observed weather for each month of LAST year (Open-Meteo archive). It is one year of real observations,
        not a long-term average, and callers must say so."""
        year = date.today().year - 1
        key = (round(lat, 1), round(lon, 1), year)
        if (hit := self._climate_cache.get(key)) is not None:
            return hit
        params = {"latitude": lat, "longitude": lon, "timezone": "auto", "start_date": f"{year}-01-01",
                  "end_date": f"{year}-12-31", "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum"}
        try:
            r = self._http.get(self.ARCHIVE_URL, params=params)
            r.raise_for_status()
            d = r.json()["daily"]
            by_month: dict[int, list[tuple[float, float, float]]] = {}
            for t, hi, lo, rain in zip(d["time"], d["temperature_2m_max"], d["temperature_2m_min"], d["precipitation_sum"]):
                if hi is not None and lo is not None:
                    by_month.setdefault(int(t[5:7]), []).append((float(hi), float(lo), float(rain or 0)))
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as e:
            raise ToolError(f"Climate lookup failed: {type(e).__name__}") from e
        if sorted(by_month) != list(range(1, 13)) or any(len(v) < 20 for v in by_month.values()):
            raise ToolError("Climate lookup returned incomplete data")
        out = [MonthClimate(m, sum(x[0] for x in v) / len(v), sum(x[1] for x in v) / len(v), sum(x[2] for x in v))
               for m, v in sorted(by_month.items())]
        self._climate_cache.set(key, out)
        return out


def within_forecast_range(start: date, end: date, today: date) -> bool:
    return today <= start and end <= today + timedelta(days=FORECAST_HORIZON_DAYS - 1)
