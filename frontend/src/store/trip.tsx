/** One provider per open trip. REST gives the state; the WebSocket says when it changed.
 *  Slices fail independently: a missing itinerary (404) is a normal state, not an error. */
import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, tokenStore } from "@/services/api";
import { type ConnState, TripSocket } from "@/services/socket";
import type {
  Budget, ChecklistItem, Conflict, ItineraryOut, Message, Preferences, TripDetail, VersionOut, Weather, WsEvent,
} from "@/types/api";
import { useAuth } from "./auth";

interface TripCtx {
  id: number;
  trip: TripDetail | null;
  loadError: string | null;
  messages: Message[];
  plan: ItineraryOut | null;
  versions: VersionOut[];
  budget: Budget | null;
  conflicts: Conflict[];
  prefs: Preferences | null;
  checklist: ChecklistItem[];
  weather: Weather | null;
  aiStatus: string | null;
  conn: ConnState;
  ready: boolean;
  answers: Record<number, string>;
  me: number;
  send: (text: string) => Promise<void>;
  regenerate: () => Promise<void>;
  ask: (question: string) => Promise<number>;
  vote: (conflictId: number, v: "accept" | "reject") => Promise<void>;
  toggleItem: (id: number, done: boolean) => Promise<void>;
  addItem: (label: string, category: ChecklistItem["category"]) => Promise<void>;
  refresh: { trip: () => Promise<void>; all: () => Promise<void> };
}
const Ctx = createContext<TripCtx | null>(null);

const orNull = async <T,>(p: Promise<T>): Promise<T | null> => {
  try { return await p; } catch (e) { if (e instanceof ApiError && (e.status === 404 || e.status === 0)) return null; throw e; }
};

export function TripProvider({ id, children }: { id: number; children: ReactNode }) {
  const { user, logout } = useAuth();
  const [trip, setTrip] = useState<TripDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [plan, setPlan] = useState<ItineraryOut | null>(null);
  const [versions, setVersions] = useState<VersionOut[]>([]);
  const [budget, setBudget] = useState<Budget | null>(null);
  const [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [checklist, setChecklist] = useState<ChecklistItem[]>([]);
  const [weather, setWeather] = useState<Weather | null>(null);
  const [aiStatus, setAiStatus] = useState<string | null>(null);
  const [conn, setConn] = useState<ConnState>("connecting");
  const [ready, setReady] = useState(false);
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const prefTimer = useRef<ReturnType<typeof setTimeout>>();

  const addMessages = useCallback((incoming: Message[]) => {
    setMessages((cur) => {
      const byId = new Map(cur.map((m) => [m.id, m]));
      incoming.forEach((m) => byId.set(m.id, m));
      return [...byId.values()].sort((a, b) => a.id - b.id);
    });
  }, []);

  const loadTrip = useCallback(async () => {
    try { setTrip(await api.trips.get(id)); setLoadError(null); }
    catch (e) { setLoadError(e instanceof ApiError ? e.message : "Couldn't load this trip."); }
  }, [id]);
  const loadPlan = useCallback(async () => {
    try {
      const [p, v, b] = await Promise.all([orNull(api.plan.itinerary(id)), api.plan.versions(id).catch(() => []), orNull(api.plan.budget(id))]);
      setPlan(p); setVersions(v); setBudget(b);
    } catch {
      // 403 (not a member) or a server error: keep what we already show rather than flashing "no itinerary".
      // Trip-level access problems are reported once, by loadTrip, through `loadError`.
    }
  }, [id]);
  const loadConflicts = useCallback(async () => setConflicts(await api.plan.conflicts(id).catch(() => [])), [id]);
  const loadPrefs = useCallback(async () => setPrefs(await api.plan.preferences(id).catch(() => null)), [id]);
  const loadChecklist = useCallback(async () => setChecklist(await api.checklist.list(id).catch(() => [])), [id]);
  const loadWeather = useCallback(async () => setWeather(await orNull(api.plan.weather(id)).catch(() => null)), [id]);
  const loadMessages = useCallback(async () => addMessages(await api.chat.list(id).catch(() => [])), [id, addMessages]);

  const refreshAll = useCallback(async () => {
    await Promise.all([loadTrip(), loadMessages(), loadPlan(), loadConflicts(), loadPrefs(), loadChecklist(), loadWeather()]);
  }, [loadTrip, loadMessages, loadPlan, loadConflicts, loadPrefs, loadChecklist, loadWeather]);

  const refreshPrefsSoon = useCallback(() => {  // extraction runs in the background and emits no event of its own
    clearTimeout(prefTimer.current);
    prefTimer.current = setTimeout(() => { void loadPrefs(); void loadConflicts(); }, 1200);
  }, [loadPrefs, loadConflicts]);

  useEffect(() => { // initial load
    let alive = true;
    setReady(false);
    void refreshAll().catch(() => undefined).finally(() => alive && setReady(true));
    return () => { alive = false; clearTimeout(prefTimer.current); };
  }, [refreshAll]);

  useEffect(() => { // live updates
    const token = tokenStore.get();
    if (!token) return;
    const onEvent = (e: WsEvent) => {
      switch (e.type) {
        case "message.new":
          addMessages([e.data]);
          if (e.data.sender_type === "ai" && e.data.reply_to_id) setAnswers((a) => ({ ...a, [e.data.reply_to_id!]: e.data.text }));
          if (e.data.sender_type !== "system") refreshPrefsSoon();
          break;
        case "ai.status": setAiStatus(e.data.text); break;
        case "itinerary.updated": void loadPlan(); break;
        case "budget.updated": setBudget(e.data); break;
        case "conflict.new": case "conflict.updated": case "conflict.resolved": void loadConflicts(); void loadPrefs(); break;
        case "member.joined": case "trip.updated": void loadTrip(); break;
        case "checklist.updated": void loadChecklist(); break;
      }
    };
    const sock = new TripSocket(id, token, {
      onEvent,
      // Resync whenever the socket goes live, including the first time: anything that happened between the
      // initial load and the socket opening (a Telegram message, say) is not replayed, so it would be missed.
      onState: (s) => { setConn(s); if (s === "live") void refreshAll(); },
      onUnauthorized: () => void logout(),
    });
    sock.connect();
    return () => sock.close();
  }, [id, addMessages, loadPlan, loadConflicts, loadPrefs, loadTrip, loadChecklist, refreshAll, refreshPrefsSoon, logout]);

  const value = useMemo<TripCtx>(() => ({
    id, trip, loadError, messages, plan, versions, budget, conflicts, prefs, checklist, weather, aiStatus, conn, ready, answers,
    me: user?.id ?? 0,
    send: async (text) => { addMessages([await api.chat.send(id, text)]); },
    regenerate: async () => { addMessages([await api.plan.regenerate(id)]); },
    ask: async (q) => { const m = await api.plan.explain(id, q); addMessages([m]); return m.id; },
    vote: async (cid, v) => { const c = await api.plan.vote(id, cid, v); setConflicts((cur) => cur.map((x) => (x.id === c.id ? c : x))); void loadConflicts(); },
    toggleItem: async (iid, done) => {
      setChecklist((c) => c.map((x) => (x.id === iid ? { ...x, done } : x)));  // optimistic; reverted by the refetch on failure
      try { await api.checklist.toggle(id, iid, done); } catch (e) { void loadChecklist(); throw e; }
    },
    addItem: async (label, category) => { await api.checklist.add(id, label, category); await loadChecklist(); },
    refresh: { trip: loadTrip, all: refreshAll },
  }), [id, trip, loadError, messages, plan, versions, budget, conflicts, prefs, checklist, weather, aiStatus, conn, ready, answers,
    user, addMessages, loadConflicts, loadChecklist, loadTrip, refreshAll]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useTrip(): TripCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useTrip must be used inside TripProvider");
  return c;
}
