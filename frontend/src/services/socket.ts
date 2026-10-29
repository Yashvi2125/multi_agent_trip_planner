import type { WsEvent } from "@/types/api";
import { config } from "./api";

export type ConnState = "connecting" | "live" | "offline";

interface Handlers {
  onEvent: (e: WsEvent) => void;
  onState: (s: ConnState, reconnected: boolean) => void;
  onUnauthorized: () => void;
}

export function wsUrl(tripId: number, token: string): string {
  const base = config.origin || window.location.origin;
  return `${base.replace(/^http/, "ws")}/ws/trips/${tripId}?token=${encodeURIComponent(token)}`;
}

/** Live trip updates. Reconnects with backoff; the caller refetches state after a reconnect because
 *  events missed while offline are not replayed. */
export class TripSocket {
  private ws: WebSocket | null = null;
  private attempt = 0;
  private closed = false;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private everOpened = false;

  constructor(private tripId: number, private token: string, private h: Handlers) {}

  connect(): void {
    if (this.closed) return;
    this.h.onState("connecting", false);
    const ws = new WebSocket(wsUrl(this.tripId, this.token));
    this.ws = ws;
    ws.onopen = () => {
      const reconnected = this.everOpened;
      this.everOpened = true;
      this.attempt = 0;
      this.h.onState("live", reconnected);
    };
    ws.onmessage = (m) => {
      try { this.h.onEvent(JSON.parse(m.data as string) as WsEvent); } catch { /* ignore malformed frame */ }
    };
    ws.onclose = (e) => {
      if (this.closed) return;
      if (e.code === 4401) { this.h.onUnauthorized(); return; }
      this.h.onState("offline", false);
      const delay = Math.min(15000, 1000 * 2 ** this.attempt++);
      this.timer = setTimeout(() => this.connect(), delay);
    };
  }

  close(): void {
    this.closed = true;
    if (this.timer) clearTimeout(this.timer);
    this.ws?.close();
  }
}
