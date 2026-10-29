import { Check, Copy } from "lucide-react";
import { useState } from "react";
import { cx } from "@/components/ui";

/** A value you're meant to copy (trip code, invite link, Telegram link code). */
export function CopyField({ label, value, mono = true }: { label: string; value: string; mono?: boolean }) {
  const [done, setDone] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(value); setDone(true); setTimeout(() => setDone(false), 1600); }
    catch { /* clipboard blocked: the value is still on screen to select by hand */ }
  };
  return (
    <div className="flex items-stretch overflow-hidden rounded border border-sand-dark bg-surface">
      <code aria-label={label} className={cx("min-w-0 flex-1 select-all truncate px-3 py-2.5 text-[15px]", mono && "font-mono")}>{value}</code>
      <button onClick={copy} aria-label={`Copy ${label}`}
        className="inline-flex items-center gap-1.5 border-l border-sand-dark bg-sand-light px-3 text-sm font-semibold hover:bg-sand">
        {done ? <Check size={14} className="text-olive" aria-hidden /> : <Copy size={14} aria-hidden />}{done ? "Copied" : "Copy"}
      </button>
    </div>
  );
}
