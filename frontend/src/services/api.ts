import type {
  Budget, ChecklistItem, Conflict, Destination, DestinationLookup, ItineraryOut, LinkCode, Message, Preferences, TelegramStatus,
  TokenOut, Trip, TripCreate, TripDetail, TripUpdate, User, VersionOut, Weather, Member,
} from "@/types/api";

const TOKEN_KEY = "wayfare.token";

export const config = { origin: "" }; // "" = same origin (Vite proxies /api and /ws in dev)

export const tokenStore = {
  get: (): string | null => { try { return localStorage.getItem(TOKEN_KEY); } catch { return null; } },
  set: (t: string) => { try { localStorage.setItem(TOKEN_KEY, t); } catch { /* private mode: stay signed in for this tab only */ } },
  clear: () => { try { localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ } },
};

export class ApiError extends Error {
  constructor(message: string, public code: string, public status: number, public fields: { field: string; issue: string }[] = []) {
    super(message);
  }
}

let onUnauthorized: (() => void) | null = null;
export const setUnauthorizedHandler = (fn: (() => void) | null) => { onUnauthorized = fn; };

async function request<T>(path: string, opts: { method?: string; body?: unknown; auth?: boolean } = {}): Promise<T> {
  const { method = "GET", body, auth = true } = opts;
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const token = tokenStore.get();
  if (auth && token) headers.Authorization = `Bearer ${token}`;
  let res: Response;
  try {
    res = await fetch(`${config.origin}/api${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError("We can't reach Wayfare right now. Check your connection and try again.", "network", 0);
  }
  if (res.status === 204) return undefined as T;
  let data: any = null;
  try { data = await res.json(); } catch { /* non-JSON error body */ }
  if (!res.ok) {
    const e = data?.error;
    if (res.status === 401 && auth && e?.code === "unauthorized") onUnauthorized?.();
    throw new ApiError(e?.message ?? "Something went wrong. Please try again.", e?.code ?? "error", res.status, e?.details ?? []);
  }
  return data as T;
}

const json = (body: unknown) => ({ method: "POST", body });
const t = (id: number) => `/trips/${id}`;

export const api = {
  auth: {
    register: (b: { name: string; email: string; password: string }) => request<TokenOut>("/auth/register", { ...json(b), auth: false }),
    login: (b: { email: string; password: string }) => request<TokenOut>("/auth/login", { ...json(b), auth: false }),
    me: () => request<User>("/auth/me"),
    logout: () => request<void>("/auth/logout", { method: "POST" }),
  },
  destinations: () => request<Destination[]>("/destinations", { auth: false }),
  lookupDestination: (q: string) => request<DestinationLookup>(`/destinations/lookup?q=${encodeURIComponent(q)}`),
  trips: {
    list: () => request<Trip[]>("/trips"),
    create: (b: TripCreate) => request<Trip>("/trips", json(b)),
    join: (code: string) => request<Trip>("/trips/join", json({ code })),
    get: (id: number) => request<TripDetail>(t(id)),
    update: (id: number, b: TripUpdate) => request<Trip>(t(id), { method: "PATCH", body: b }),
    members: (id: number) => request<Member[]>(`${t(id)}/members`),
  },
  chat: {
    list: (id: number, before?: number) => request<Message[]>(`${t(id)}/messages?limit=100${before ? `&before=${before}` : ""}`),
    send: (id: number, text: string) => request<Message>(`${t(id)}/messages`, json({ text })),
  },
  plan: {
    itinerary: (id: number, version?: number) => request<ItineraryOut>(`${t(id)}/itinerary${version ? `?version=${version}` : ""}`),
    versions: (id: number) => request<VersionOut[]>(`${t(id)}/itinerary/versions`),
    budget: (id: number) => request<Budget>(`${t(id)}/budget`),
    regenerate: (id: number) => request<Message>(`${t(id)}/regenerate`, { method: "POST" }),
    explain: (id: number, question: string) => request<Message>(`${t(id)}/explain`, json({ question })),
    conflicts: (id: number) => request<Conflict[]>(`${t(id)}/conflicts`),
    vote: (id: number, cid: number, vote: "accept" | "reject") => request<Conflict>(`${t(id)}/conflicts/${cid}/vote`, json({ vote })),
    preferences: (id: number) => request<Preferences>(`${t(id)}/preferences`),
    weather: (id: number) => request<Weather>(`${t(id)}/weather`),
  },
  checklist: {
    list: (id: number) => request<ChecklistItem[]>(`${t(id)}/checklist`),
    add: (id: number, label: string, category: ChecklistItem["category"]) => request<ChecklistItem>(`${t(id)}/checklist`, json({ label, category })),
    toggle: (id: number, item: number, done: boolean) => request<ChecklistItem>(`${t(id)}/checklist/${item}`, { method: "PATCH", body: { done } }),
  },
  telegram: {
    status: () => request<TelegramStatus>("/telegram/status", { auth: false }),
    linkCode: () => request<LinkCode>("/telegram/link-code", { method: "POST" }),
  },
};
