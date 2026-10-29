import { Check, X } from "lucide-react";
import { useState } from "react";
import { Badge, cx } from "@/components/ui";
import { ApiError } from "@/services/api";
import { useTrip } from "@/store/trip";
import type { Conflict } from "@/types/api";

const STATUS: Record<Conflict["status"], { tone: "amber" | "olive" | "neutral"; label: string }> = {
  open: { tone: "amber", label: "Needs a decision" }, accepted: { tone: "olive", label: "Compromise accepted" },
  dismissed: { tone: "neutral", label: "Set aside" }, resolved: { tone: "olive", label: "Sorted out" },
};

/** Shown in chat, on the overview and on the People page. Votes from Telegram land on the same record. */
export function ConflictBlock({ conflict: c, compact = false }: { conflict: Conflict; compact?: boolean }) {
  const { vote } = useTrip();
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const open = c.status === "open";

  async function cast(v: "accept" | "reject") {
    setBusy(v); setErr(null);
    try { await vote(c.id, v); } catch (e) { setErr(e instanceof ApiError ? e.message : "Couldn't record that vote."); } finally { setBusy(null); }
  }
  const btn = (v: "accept" | "reject", label: string, Icon: typeof Check) => (
    <button key={v} onClick={() => cast(v)} disabled={!!busy} aria-pressed={c.my_vote === v}
      className={cx("inline-flex items-center gap-1.5 rounded border px-3 py-1.5 text-sm font-semibold transition-colors disabled:opacity-60",
        c.my_vote === v ? "border-lagoon bg-lagoon text-white" : "border-sand-dark bg-surface text-ink hover:bg-sand-light")}>
      <Icon size={14} aria-hidden />{label}
    </button>
  );
  return (
    <section aria-label="Group decision" className={cx("border-l-2 pl-4", open ? "border-amber" : "border-sand-dark")}>
      <div className="flex flex-wrap items-center gap-2"><Badge tone={STATUS[c.status].tone}>{STATUS[c.status].label}</Badge>
        {(c.accept_votes > 0 || c.reject_votes > 0) && <span className="text-xs text-ink-faint">{c.accept_votes} for · {c.reject_votes} against</span>}</div>
      <p className={cx("mt-1.5", compact ? "text-sm" : "text-[15px]")}>{c.description}</p>
      {c.proposed_compromise && <p className={cx("mt-1 text-ink-soft", compact ? "text-sm" : "text-[15px]")}>
        <span className="font-semibold text-ink">A compromise that could work: </span>{c.proposed_compromise}</p>}
      {open && <div className="mt-3 flex flex-wrap gap-2">{btn("accept", "Works for me", Check)}{btn("reject", "Not for me", X)}</div>}
      {err && <p role="alert" className="mt-2 text-sm text-terracotta-dark">{err}</p>}
    </section>
  );
}
