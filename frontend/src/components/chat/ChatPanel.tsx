import { Compass, Send as SendIcon } from "lucide-react";
import { type FormEvent, type KeyboardEvent, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Avatar, Button, cx, PlatformGlyph } from "@/components/ui";
import { ConflictBlock } from "@/components/trip/ConflictBlock";
import { ApiError } from "@/services/api";
import { useTrip } from "@/store/trip";
import type { Message } from "@/types/api";
import { clock } from "@/utils/format";

const GROUP_WINDOW_MS = 3 * 60_000;

function PlannerMark({ size = 32 }: { size?: number }) {
  return <span aria-hidden className="grid shrink-0 place-items-center rounded bg-lagoon text-paper" style={{ width: size, height: size }}><Compass size={size * 0.58} /></span>;
}

function MessageRow({ m, showHeader, mine }: { m: Message; showHeader: boolean; mine: boolean }) {
  const { conflicts, id } = useTrip();
  if (m.sender_type === "system") return <p className="py-1 text-center text-xs text-ink-faint">{m.text}</p>;
  const ai = m.sender_type === "ai";
  const name = ai ? "Planner" : m.sender?.name ?? "Someone";
  const linked = (m.meta?.conflict_ids ?? []).map((cid) => conflicts.find((c) => c.id === cid)).filter(Boolean);
  return (
    <div className={cx("flex gap-3", showHeader ? "pt-3" : "pt-0.5")}>
      <div className="w-8 shrink-0">{showHeader && (ai ? <PlannerMark /> : <Avatar name={name} id={m.sender?.id} />)}</div>
      <div className="min-w-0 flex-1">
        {showHeader && (
          <p className="flex items-center gap-1.5 text-sm">
            <span className="font-semibold">{mine ? "You" : name}</span>
            {!ai && <PlatformGlyph via={m.source} size={12} />}
            <time className="text-xs text-ink-faint" dateTime={m.created_at}>{clock(m.created_at)}</time>
          </p>
        )}
        <p className={cx("whitespace-pre-wrap break-words text-[15px] leading-relaxed", ai && "border-l-2 border-lagoon/50 pl-3 text-ink")}>{m.text}</p>
        {ai && m.meta?.version && (
          <Link to={`/trip/${id}/itinerary`} className="mt-1.5 inline-block pl-3 text-sm font-semibold text-lagoon underline-offset-2 hover:underline">
            Open version {m.meta.version} →</Link>
        )}
        {ai && linked.length > 0 && <div className="mt-3 space-y-4 pl-3">{linked.map((c) => <ConflictBlock key={c!.id} conflict={c!} compact />)}</div>}
      </div>
    </div>
  );
}

export function ChatPanel({ className }: { className?: string }) {
  const { messages, send, aiStatus, conn, me, ready } = useTrip();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const box = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = scroller.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [messages.length, aiStatus]);

  async function submit(e?: FormEvent) {
    e?.preventDefault();
    const t = text.trim();
    if (!t || busy) return;
    setBusy(true); setError(null);
    try { await send(t); setText(""); stick.current = true; }
    catch (err) { setError(err instanceof ApiError ? err.message : "That message didn't send. Please try again."); }
    finally { setBusy(false); box.current?.focus(); }
  }
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void submit(); } };
  const mention = () => { setText((t) => (t.includes("@planner") ? t : `@planner ${t}`)); box.current?.focus(); };

  return (
    <div className={cx("flex min-h-0 flex-col bg-surface", className)}>
      <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto px-4 pb-3" role="log" aria-label="Trip chat" aria-live="polite"
        onScroll={(e) => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80; }}>
        {!ready ? <div className="space-y-4 pt-4">{[0, 1, 2].map((i) => <div key={i} className="skeleton h-12" />)}</div>
          : messages.length === 0 ? (
            <div className="grid h-full place-items-center text-center text-ink-soft"><p className="max-w-[16rem]">
              No messages yet. Say what you'd love from this trip, and mention <b className="text-ink">@planner</b> whenever you want it to act.</p></div>
          ) : messages.map((m, i) => {
            const prev = messages[i - 1];
            const same = prev && prev.sender_type === m.sender_type && prev.sender?.id === m.sender?.id && m.sender_type !== "system" &&
              Date.parse(m.created_at) - Date.parse(prev.created_at) < GROUP_WINDOW_MS;
            return <MessageRow key={m.id} m={m} showHeader={!same} mine={m.sender?.id === me && m.sender_type === "user"} />;
          })}
      </div>
      <div className="border-t border-sand px-4 pb-3 pt-2">
        <p className="h-5 text-sm text-lagoon" aria-live="polite">{aiStatus ? <span className="dots">{aiStatus.replace(/…$/, "")}</span> : conn === "offline" ? <span className="text-ink-faint">Reconnecting…</span> : null}</p>
        {error && <p role="alert" className="mb-1 text-sm text-terracotta-dark">{error}</p>}
        <form onSubmit={submit} className="flex items-end gap-2">
          <textarea ref={box} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKey} rows={1} maxLength={2000}
            aria-label="Message the group" placeholder="Message the group…"
            className="max-h-32 min-h-[44px] flex-1 resize-none rounded border border-sand-dark bg-surface px-3 py-2.5 text-[15px] placeholder:text-ink-faint focus:border-lagoon" />
          <Button type="submit" variant="primary" disabled={!text.trim()} busy={busy} aria-label="Send" className="h-[44px] px-3.5"><SendIcon size={17} aria-hidden /></Button>
        </form>
        <button type="button" onClick={mention} className="mt-2 text-xs font-semibold text-lagoon hover:underline">Ask @planner</button>
        <span className="text-xs text-ink-faint"> · Enter to send, Shift+Enter for a new line</span>
      </div>
    </div>
  );
}
