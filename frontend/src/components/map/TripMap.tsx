import L from "leaflet";
import { useEffect, useRef } from "react";
import type { ItineraryDay } from "@/types/api";

export const DAY_COLORS = ["#0F5C5A", "#C8553D", "#B7791F", "#5F6E2F", "#6B4E8A", "#2F6F9F", "#8A4B3A"];

/** Day-coloured pins in visiting order. Tiles come from OpenStreetMap, so the pins still work offline. */
export function TripMap({ days, onlyDay, height = 380 }: { days: ItineraryDay[]; onlyDay: number | null; height?: number }) {
  const el = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!el.current) return;
    const map = L.map(el.current, { scrollWheelZoom: false });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "© OpenStreetMap contributors" }).addTo(map);
    const pts: L.LatLngTuple[] = [];
    for (const d of days) {
      if (onlyDay !== null && d.index !== onlyDay) continue;
      const color = DAY_COLORS[(d.index - 1) % DAY_COLORS.length];
      const line: L.LatLngTuple[] = [];
      d.items.forEach((it, n) => {
        if (it.lat === null || it.lon === null) return;
        const p: L.LatLngTuple = [it.lat, it.lon];
        line.push(p); pts.push(p);
        L.marker(p, { icon: L.divIcon({ className: "", html: `<span class="pin" style="background:${color}">${n + 1}</span>`, iconSize: [22, 22], iconAnchor: [11, 11] }) })
          .bindTooltip(`Day ${d.index} · ${it.start} ${it.name}`).addTo(map);
      });
      if (line.length > 1) L.polyline(line, { color, weight: 2, opacity: 0.7, dashArray: "4 6" }).addTo(map);
    }
    if (pts.length) map.fitBounds(L.latLngBounds(pts), { padding: [32, 32], maxZoom: 13 }); else map.setView([20.5, 78.9], 4);
    return () => { map.remove(); };
  }, [days, onlyDay]);
  return <div ref={el} role="region" aria-label="Map of the planned stops" style={{ height }} className="w-full" />;
}
