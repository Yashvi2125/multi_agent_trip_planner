import { Check, Plus } from "lucide-react";
import { type FormEvent, useState } from "react";
import { Button, cx, Input } from "@/components/ui";
import { ApiError } from "@/services/api";
import { useTrip } from "@/store/trip";
import type { ChecklistItem } from "@/types/api";

const GROUPS: { key: ChecklistItem["category"]; label: string }[] = [
  { key: "booking", label: "Book" }, { key: "document", label: "Documents" }, { key: "packing", label: "Pack" },
];

export function Checklist() {
  const { checklist, toggleItem, addItem } = useTrip();
  const [label, setLabel] = useState("");
  const [cat, setCat] = useState<ChecklistItem["category"]>("booking");
  const [err, setErr] = useState<string | null>(null);

  async function add(e: FormEvent) {
    e.preventDefault();
    if (label.trim().length < 2) return;
    try { await addItem(label.trim(), cat); setLabel(""); setErr(null); } catch (x) { setErr(x instanceof ApiError ? x.message : "Couldn't add that."); }
  }
  const flip = (i: ChecklistItem) => toggleItem(i.id, !i.done).catch((x) => setErr(x instanceof ApiError ? x.message : "Couldn't update that."));
  const done = checklist.filter((i) => i.done).length;
  return (
    <div>
      <p className="mb-3 text-sm text-ink-soft">{done} of {checklist.length} done</p>
      <div className="grid gap-x-10 gap-y-5 sm:grid-cols-3">
        {GROUPS.map((g) => (
          <div key={g.key}>
            <h3 className="mb-2 text-xs font-bold uppercase tracking-widest text-ink-faint">{g.label}</h3>
            <ul className="space-y-1.5">
              {checklist.filter((i) => i.category === g.key).map((i) => (
                <li key={i.id}><button onClick={() => flip(i)} role="checkbox" aria-checked={i.done} className="flex w-full items-start gap-2.5 text-left text-[15px]">
                  <span className={cx("mt-0.5 grid size-[18px] shrink-0 place-items-center rounded-sm border", i.done ? "border-lagoon bg-lagoon text-white" : "border-sand-dark bg-surface")}>{i.done && <Check size={12} aria-hidden />}</span>
                  <span className={cx(i.done && "text-ink-faint line-through")}>{i.label}</span></button></li>))}
            </ul>
          </div>))}
      </div>
      <form onSubmit={add} className="mt-5 flex flex-wrap gap-2">
        <Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Add something to the list" aria-label="New checklist item" className="min-w-0 flex-1 basis-48" maxLength={200} />
        <select value={cat} onChange={(e) => setCat(e.target.value as ChecklistItem["category"])} aria-label="Category" className="rounded border border-sand-dark bg-surface px-2 text-[15px]">
          {GROUPS.map((g) => <option key={g.key} value={g.key}>{g.label}</option>)}</select>
        <Button type="submit" disabled={label.trim().length < 2}><Plus size={16} aria-hidden />Add</Button>
      </form>
      {err && <p role="alert" className="mt-2 text-sm text-terracotta-dark">{err}</p>}
    </div>
  );
}
