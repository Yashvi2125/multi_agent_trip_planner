import { BudgetBar, budgetSentence, CATS, toneClass } from "@/components/budget/BudgetBar";
import { Button, EmptyState, Skeleton } from "@/components/ui";
import { useTrip } from "@/store/trip";
import { inr } from "@/utils/format";
import { usePlanAction } from "./Overview";

export default function BudgetPage() {
  const t = useTrip();
  const act = usePlanAction();
  if (!t.ready) return <div className="space-y-4"><Skeleton className="h-10 w-1/2" /><Skeleton className="h-32" /></div>;
  const b = t.budget;
  if (!b) return <EmptyState title="No budget estimate yet" action={<Button variant="primary" busy={act.busy} onClick={act.run}>Build the first plan</Button>}>The estimate appears once the first plan is built. Costs, the total and each person's share are all worked out in code, not guessed by the AI.</EmptyState>;
  const s = budgetSentence(b), total = Number(b.total);
  const stats: [string, string][] = [
    ["Estimated total", inr(b.total)], ["Budget limit", b.cap ? inr(b.cap) : "None set"],
    [b.status === "over" ? "Over by" : "Remaining", b.status === "over" ? inr(b.over_by) : inr(b.remaining)], ["Per person", inr(b.per_person)],
  ];
  return (
    <div className="space-y-10">
      <dl className="grid grid-cols-2 gap-y-6 border-b border-sand pb-8 sm:grid-cols-4">
        {stats.map(([k, v]) => <div key={k}><dt className="text-sm text-ink-soft">{k}</dt><dd className={`mt-1 font-display text-3xl ${k === "Over by" ? "text-terracotta-dark" : ""}`}>{v}</dd></div>)}
      </dl>
      <section aria-label="Against the limit"><BudgetBar b={b} legend={false} /><p className={`mt-3 ${toneClass(s.tone)}`}>{s.text}</p>
        <p className="mt-1 text-sm text-ink-faint">Split between {b.travelers} travellers. The limit is the strictest of the group budget and anyone's personal cap × group size.</p></section>
      <section>
        <h2 className="mb-3 text-xl">By category</h2>
        <table className="w-full text-[15px]"><tbody className="divide-y divide-sand">
          {CATS.filter((c) => Number(b.by_category[c.key] ?? 0) > 0).map((c) => { const v = Number(b.by_category[c.key]); return (
            <tr key={c.key}><td className="py-2.5"><span aria-hidden className="mr-2 inline-block size-2.5 rounded-sm" style={{ background: c.color }} />{c.label}</td>
              <td className="py-2.5 text-right text-ink-soft">{total ? Math.round((v / total) * 100) : 0}%</td><td className="w-28 py-2.5 text-right font-semibold tabular-nums">{inr(v)}</td></tr>); })}
        </tbody></table>
      </section>
      <section>
        <h2 className="mb-3 text-xl">What's in it</h2>
        <div className="overflow-x-auto"><table className="w-full text-[15px]">
          <thead className="text-left text-sm text-ink-faint"><tr><th className="pb-2 font-semibold">Item</th><th className="pb-2 font-semibold">Type</th><th className="pb-2 text-right font-semibold">Group total</th></tr></thead>
          <tbody className="divide-y divide-sand">{[...b.lines].sort((x, y) => Number(y.total) - Number(x.total)).map((l, i) => <tr key={`${l.label}-${i}`}><td className="py-2.5 pr-4">{l.label}</td><td className="py-2.5 pr-4 capitalize text-ink-soft">{l.category}</td><td className="py-2.5 text-right tabular-nums">{inr(l.total)}</td></tr>)}</tbody></table></div>
        <p className="mt-4 text-sm text-ink-faint">These are planning estimates from curated data (peak-season rates included). Check prices when you book.</p>
      </section>
    </div>
  );
}
