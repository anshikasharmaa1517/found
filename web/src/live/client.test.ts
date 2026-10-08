import { describe, expect, it } from "vitest";

import { BACKOFF_MS, LiveClient, parseMessage, type LiveStatus, type SocketLike } from "./client";

class FakeSocket implements SocketLike {
  readyState = 0;
  sent: string[] = [];
  closed = false;
  onopen: SocketLike["onopen"] = null;
  onmessage: SocketLike["onmessage"] = null;
  onclose: SocketLike["onclose"] = null;
  onerror: SocketLike["onerror"] = null;
  constructor(readonly url: string) {}
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.closed = true;
  }
  open() {
    this.readyState = 1;
    this.onopen?.({});
  }
  receive(data: unknown) {
    this.onmessage?.({ data: typeof data === "string" ? data : JSON.stringify(data) });
  }
  drop() {
    this.readyState = 3;
    this.onclose?.({});
  }
}

function setup(tokens: (string | null)[] = ["t1", "t2", "t3", "t4"]) {
  const sockets: FakeSocket[] = [];
  const timers: { run: () => void; ms: number; cancelled: boolean }[] = [];
  const client = new LiveClient({
    url: "wss://ws.example.org/prod",
    idToken: async () => (tokens.length ? tokens.shift()! : "later"),
    createSocket: (url) => {
      const socket = new FakeSocket(url);
      sockets.push(socket);
      return socket;
    },
    schedule: (run, ms) => {
      const timer = { run, ms, cancelled: false };
      timers.push(timer);
      return () => {
        timer.cancelled = true;
      };
    },
  });
  const statuses: LiveStatus[] = [];
  client.onStatus((s) => statuses.push(s));
  return { client, sockets, timers, statuses };
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("parseMessage", () => {
  it("accepts known messages and ignores the rest", () => {
    expect(parseMessage(JSON.stringify({ type: "alert.created", alert_id: "a" }))).toMatchObject({
      type: "alert.created",
    });
    expect(parseMessage(JSON.stringify({ type: "unknown" }))).toBeNull();
    expect(parseMessage("not json")).toBeNull();
    expect(parseMessage(42)).toBeNull();
  });
});

describe("LiveClient", () => {
  it("connects with the token, subscribes to the incident and delivers messages", async () => {
    const { client, sockets, statuses } = setup();
    const got: unknown[] = [];
    client.onMessage((m) => got.push(m));
    client.setIncident("inc_1");
    client.start();
    await flush();
    expect(sockets[0]!.url).toBe("wss://ws.example.org/prod?token=t1");
    sockets[0]!.open();
    expect(sockets[0]!.sent).toEqual([JSON.stringify({ action: "subscribe", incident_id: "inc_1" })]);
    sockets[0]!.receive({ type: "claim.created", incident_id: "inc_1", claim_id: "c", subject_id: "p", at: "x" });
    sockets[0]!.receive("garbage");
    expect(got).toHaveLength(1);
    expect(statuses).toEqual(["offline", "connecting", "live"]);
  });

  it("switches incidents on the open connection", async () => {
    const { client, sockets } = setup();
    client.start();
    await flush();
    sockets[0]!.open();
    client.setIncident("inc_2");
    client.setIncident("inc_2");
    expect(sockets[0]!.sent).toEqual([JSON.stringify({ action: "subscribe", incident_id: "inc_2" })]);
  });

  it("reconnects with backoff and a fresh token, then reports it is back", async () => {
    const { client, sockets, timers } = setup();
    let back = 0;
    client.onReconnect(() => back++);
    client.setIncident("inc_1");
    client.start();
    await flush();
    sockets[0]!.open();
    expect(back).toBe(0);

    sockets[0]!.drop();
    expect(timers.at(-1)!.ms).toBe(BACKOFF_MS[0]);
    timers.at(-1)!.run();
    await flush();
    expect(sockets[1]!.url).toContain("token=t2");
    sockets[1]!.drop();
    expect(timers.at(-1)!.ms).toBe(BACKOFF_MS[1]);
    timers.at(-1)!.run();
    await flush();
    sockets[2]!.open();
    expect(back).toBe(1);
    expect(sockets[2]!.sent).toEqual([JSON.stringify({ action: "subscribe", incident_id: "inc_1" })]);

    sockets[2]!.drop();
    expect(timers.at(-1)!.ms).toBe(BACKOFF_MS[0]);
  });

  it("waits and retries when there is no token yet", async () => {
    const { client, sockets, timers } = setup([null, "t2"]);
    client.start();
    await flush();
    expect(sockets).toHaveLength(0);
    timers.at(-1)!.run();
    await flush();
    expect(sockets[0]!.url).toContain("token=t2");
  });

  it("stops cleanly: closes, cancels retries and never reconnects", async () => {
    const { client, sockets, timers, statuses } = setup();
    client.start();
    await flush();
    sockets[0]!.open();
    sockets[0]!.drop();
    client.stop();
    expect(timers.at(-1)!.cancelled).toBe(true);
    expect(statuses.at(-1)).toBe("offline");

    const fresh = setup();
    fresh.client.start();
    await flush();
    fresh.client.stop();
    expect(fresh.sockets[0]!.closed).toBe(true);
    fresh.sockets[0]!.drop();
    expect(fresh.timers).toHaveLength(0);
  });
});
