/**
 * Live updates over the WebSocket API (design Sections 5.4 and 7.5).
 *
 * Messages are notifications only. The client reconnects with backoff, asks for a fresh
 * token on every connect, and tells listeners when it is back so they can refetch:
 * anything missed while offline is picked up that way.
 */

export type LiveMessage =
  | { type: "claim.created"; incident_id: string; claim_id: string; subject_id: string; at: string }
  | { type: "alert.created"; alert_id: string; subject_id: string; severity: string; message: string }
  | { type: "review.created"; incident_id: string; review_id: string; item_type: string }
  | { type: "subscribed"; incident_id: string }
  | { type: "error"; error: { code: string; message: string } };

export type LiveStatus = "connecting" | "live" | "offline";

/** The parts of the browser WebSocket the client uses. */
export interface SocketLike {
  readonly readyState: number;
  onopen: ((event: unknown) => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
  onclose: ((event: unknown) => void) | null;
  onerror: ((event: unknown) => void) | null;
  send(data: string): void;
  close(): void;
}

const OPEN = 1;
export const BACKOFF_MS = [1000, 2000, 5000, 10000, 30000] as const;

export interface LiveClientOptions {
  url: string;
  idToken: () => Promise<string | null>;
  createSocket?: (url: string) => SocketLike;
  schedule?: (run: () => void, ms: number) => () => void;
}

const KNOWN = new Set(["claim.created", "alert.created", "review.created", "subscribed", "error"]);

export function parseMessage(data: unknown): LiveMessage | null {
  if (typeof data !== "string") return null;
  try {
    const value = JSON.parse(data) as { type?: unknown };
    return value && typeof value.type === "string" && KNOWN.has(value.type)
      ? (value as LiveMessage)
      : null;
  } catch {
    return null;
  }
}

export class LiveClient {
  private socket: SocketLike | null = null;
  private stopped = true;
  private attempt = 0;
  private wasLive = false;
  private cancelRetry: (() => void) | null = null;
  private incidentId: string | null = null;
  private status: LiveStatus = "offline";
  private readonly messageListeners = new Set<(m: LiveMessage) => void>();
  private readonly statusListeners = new Set<(s: LiveStatus) => void>();
  private readonly reconnectListeners = new Set<() => void>();
  private readonly createSocket: (url: string) => SocketLike;
  private readonly schedule: (run: () => void, ms: number) => () => void;
  private readonly options: LiveClientOptions;

  constructor(options: LiveClientOptions) {
    this.options = options;
    this.createSocket = options.createSocket ?? ((url) => new WebSocket(url) as unknown as SocketLike);
    this.schedule =
      options.schedule ??
      ((run, ms) => {
        const timer = setTimeout(run, ms);
        return () => clearTimeout(timer);
      });
  }

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    void this.connect();
  }

  stop(): void {
    this.stopped = true;
    this.cancelRetry?.();
    this.cancelRetry = null;
    const socket = this.socket;
    this.socket = null;
    socket?.close();
    this.setStatus("offline");
  }

  /** Follow one incident's feed. Kept across reconnects. */
  setIncident(incidentId: string | null): void {
    if (incidentId === this.incidentId) return;
    this.incidentId = incidentId;
    this.sendSubscribe();
  }

  onMessage(listener: (m: LiveMessage) => void): () => void {
    this.messageListeners.add(listener);
    return () => this.messageListeners.delete(listener);
  }

  onStatus(listener: (s: LiveStatus) => void): () => void {
    this.statusListeners.add(listener);
    listener(this.status);
    return () => this.statusListeners.delete(listener);
  }

  /** Called after a dropped connection comes back, so views can refetch what they missed. */
  onReconnect(listener: () => void): () => void {
    this.reconnectListeners.add(listener);
    return () => this.reconnectListeners.delete(listener);
  }

  private setStatus(status: LiveStatus): void {
    if (status === this.status) return;
    this.status = status;
    for (const listener of this.statusListeners) listener(status);
  }

  private sendSubscribe(): void {
    if (this.incidentId && this.socket?.readyState === OPEN) {
      this.socket.send(JSON.stringify({ action: "subscribe", incident_id: this.incidentId }));
    }
  }

  private async connect(): Promise<void> {
    this.setStatus("connecting");
    const token = await this.options.idToken().catch(() => null);
    if (this.stopped) return;
    if (!token) {
      this.retry();
      return;
    }
    const separator = this.options.url.includes("?") ? "&" : "?";
    const socket = this.createSocket(
      `${this.options.url}${separator}token=${encodeURIComponent(token)}`,
    );
    this.socket = socket;
    socket.onopen = () => {
      if (socket !== this.socket) return;
      this.attempt = 0;
      this.setStatus("live");
      this.sendSubscribe();
      if (this.wasLive) for (const listener of this.reconnectListeners) listener();
      this.wasLive = true;
    };
    socket.onmessage = (event) => {
      const message = parseMessage(event.data);
      if (message) for (const listener of this.messageListeners) listener(message);
    };
    socket.onclose = () => {
      if (socket !== this.socket) return;
      this.socket = null;
      this.retry();
    };
    socket.onerror = () => {
      // A close event always follows; reconnecting happens there.
    };
  }

  private retry(): void {
    if (this.stopped) return;
    this.setStatus("offline");
    const delay = BACKOFF_MS[Math.min(this.attempt, BACKOFF_MS.length - 1)]!;
    this.attempt += 1;
    this.cancelRetry = this.schedule(() => {
      this.cancelRetry = null;
      void this.connect();
    }, delay);
  }
}
