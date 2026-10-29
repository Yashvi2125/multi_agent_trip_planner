import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "@/App";
import { tokenStore } from "@/services/api";
import { AuthProvider } from "@/store/auth";

export const API = () => process.env.E2E_API!;
export const TG = () => process.env.E2E_TG!;

/** Talk to the real API as any user, independently of whoever the UI is signed in as. */
export async function call<T = any>(token: string | null, method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API()}/api${path}`, {
    method, headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = res.status === 204 ? null : await res.json();
  if (!res.ok) throw new Error(`${method} ${path} → ${res.status} ${JSON.stringify(data)}`);
  return data as T;
}

let n = 0;
export async function newUser(name: string) {
  const email = `${name.split(" ")[0]!.toLowerCase()}.${Date.now()}.${n++}@example.com`;
  const r = await call<{ access_token: string; user: { id: number; name: string } }>(null, "POST", "/auth/register", { name, email, password: "goa-trip-2026" });
  return { token: r.access_token, id: r.user.id, name, email, password: "goa-trip-2026" };
}

export const GOA = { name: "Goa with the gang", destination: "Goa", start_date: "2026-12-10", end_date: "2026-12-14", group_budget: "60000" };
export const createTrip = (token: string, body: object = GOA) => call<{ id: number; code: string }>(token, "POST", "/trips", body);

/** Render the real app, signed in as `token` (or signed out), at `path`. */
export function renderApp(path: string, token?: string) {
  if (token) tokenStore.set(token);
  return render(<MemoryRouter initialEntries={[path]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
}

// ---- Telegram: send updates to the real webhook, and read what the bot sent back
let updateId = 1;
export const bot = { username: "WayfareE2EBot", id: 424242 };
export type TgUser = { id: number; first_name: string; username?: string };
export const tgUser = (id: number, first_name: string): TgUser => ({ id, first_name, username: first_name.toLowerCase() });

export async function tgSend(from: TgUser, chat: { id: number; type?: string }, text: string, extra: object = {}) {
  const res = await fetch(`${API()}/api/telegram/webhook`, {
    method: "POST", headers: { "Content-Type": "application/json", "x-telegram-bot-api-secret-token": "e2e-webhook-secret" },
    body: JSON.stringify({ update_id: updateId++, message: { message_id: updateId, from: { ...from, is_bot: false }, chat: { type: "group", ...chat }, text, ...extra } }),
  });
  if (!res.ok) throw new Error(`webhook → ${res.status}`);
}
export async function tgPress(from: TgUser, data: string) {
  await fetch(`${API()}/api/telegram/webhook`, {
    method: "POST", headers: { "Content-Type": "application/json", "x-telegram-bot-api-secret-token": "e2e-webhook-secret" },
    body: JSON.stringify({ update_id: updateId++, callback_query: { id: `cb${updateId}`, from: { ...from, is_bot: false }, data } }),
  });
}
export type TgCall = { method: string; body: Record<string, any> };
export const tgCalls = async (): Promise<TgCall[]> => (await fetch(`${TG()}/__calls`)).json();
export const tgSent = async (chatId: number) => (await tgCalls()).filter((c) => c.method === "sendMessage" && c.body.chat_id === chatId);
export const tgReset = () => fetch(`${TG()}/__reset`, { method: "POST", body: "{}" });
let chatSeq = -1_000_000;
export const newGroup = () => ({ id: chatSeq--, type: "group" });
