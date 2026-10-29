import { Cloud, CloudDrizzle, CloudRain, CloudSnow, CloudSun, Sun, Zap } from "lucide-react";
import type { Weather } from "@/types/api";
import { dayLabel } from "@/utils/format";

function icon(summary: string) {
  const s = summary.toLowerCase();
  if (s.includes("thunder")) return Zap;
  if (s.includes("snow")) return CloudSnow;
  if (s.includes("heavy") || s.includes("rain likely")) return CloudRain;
  if (s.includes("rain") || s.includes("shower") || s.includes("drizzle")) return CloudDrizzle;
  if (s.includes("partly") || s.includes("mostly")) return CloudSun;
  if (s.includes("clear") || s.includes("dry")) return Sun;
  return Cloud;
}

export function WeatherStrip({ w }: { w: Weather }) {
  if (!w.supported || w.days.length === 0) return <p className="text-ink-soft">{w.notes[0] ?? "Add trip dates and a supported destination to see the weather."}</p>;
  return (
    <div>
      <ul className="flex gap-5 overflow-x-auto pb-1">
        {w.days.slice(0, 7).map((d) => { const I = icon(d.summary); return (
          <li key={d.date} className="min-w-[4.5rem] text-center">
            <p className="text-xs text-ink-faint">{dayLabel(d.date)}</p>
            <I size={22} className="mx-auto my-1.5 text-lagoon" aria-label={d.summary} />
            <p className="text-sm font-semibold tabular-nums">{Math.round(d.temp_max)}°<span className="font-normal text-ink-faint"> {Math.round(d.temp_min)}°</span></p>
            {d.rain_chance !== null && <p className="text-xs text-ink-faint">{d.rain_chance}% rain</p>}
          </li>); })}
      </ul>
      <p className="mt-2 text-xs text-ink-faint">{w.source === "live" ? "Live forecast." : "Typical conditions for these dates. A live forecast appears closer to the trip."}</p>
    </div>
  );
}
