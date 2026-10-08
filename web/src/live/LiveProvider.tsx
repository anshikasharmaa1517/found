import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { useAuth } from "../auth/context";
import { LiveClient, type LiveMessage, type LiveStatus, type SocketLike } from "./client";
import { LiveContext, type LiveContextValue } from "./context";

/**
 * One live connection per signed-in session. `incidentId` is the incident whose feed
 * staff see; family accounts pass null because they only get their own alerts.
 *
 * Listeners are kept here, not on the client, because child components subscribe before
 * this provider's effect creates the client.
 */
export function LiveProvider({
  wsUrl,
  createSocket,
  incidentId,
  children,
}: {
  wsUrl?: string;
  createSocket?: (url: string) => SocketLike;
  incidentId: string | null;
  children: ReactNode;
}) {
  const { idToken } = useAuth();
  const [status, setStatus] = useState<LiveStatus>("offline");
  const client = useRef<LiveClient | null>(null);
  const incident = useRef(incidentId);
  const messages = useRef(new Set<(m: LiveMessage) => void>());
  const reconnects = useRef(new Set<() => void>());

  useEffect(() => {
    if (!wsUrl) return;
    const live = new LiveClient({ url: wsUrl, idToken, createSocket });
    client.current = live;
    const stops = [
      live.onStatus(setStatus),
      live.onMessage((m) => messages.current.forEach((listener) => listener(m))),
      live.onReconnect(() => reconnects.current.forEach((listener) => listener())),
    ];
    live.setIncident(incident.current);
    live.start();
    return () => {
      stops.forEach((stop) => stop());
      live.stop();
      client.current = null;
    };
  }, [wsUrl, idToken, createSocket]);

  useEffect(() => {
    incident.current = incidentId;
    client.current?.setIncident(incidentId);
  }, [incidentId]);

  const value = useMemo<LiveContextValue>(
    () => ({
      status: wsUrl ? status : "off",
      onMessage: (listener) => {
        messages.current.add(listener);
        return () => messages.current.delete(listener);
      },
      onReconnect: (listener) => {
        reconnects.current.add(listener);
        return () => reconnects.current.delete(listener);
      },
    }),
    [wsUrl, status],
  );

  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>;
}
