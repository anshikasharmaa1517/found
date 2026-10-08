import { createContext, useContext, useEffect, useRef } from "react";

import type { LiveMessage, LiveStatus } from "./client";

export interface LiveContextValue {
  status: LiveStatus | "off";
  onMessage(listener: (m: LiveMessage) => void): () => void;
  onReconnect(listener: () => void): () => void;
}

const NONE = () => () => undefined;

/** Without a provider (or without a WebSocket URL) live updates are simply off. */
export const LiveContext = createContext<LiveContextValue>({
  status: "off",
  onMessage: NONE,
  onReconnect: NONE,
});

export function useLiveStatus(): LiveContextValue["status"] {
  return useContext(LiveContext).status;
}

/** Calls the latest `handler` for every live message, without resubscribing each render. */
export function useLiveMessage(handler: (m: LiveMessage) => void): void {
  const live = useContext(LiveContext);
  const latest = useRef(handler);
  useEffect(() => {
    latest.current = handler;
  });
  useEffect(() => live.onMessage((m) => latest.current(m)), [live]);
}

export function useLiveReconnect(handler: () => void): void {
  const live = useContext(LiveContext);
  const latest = useRef(handler);
  useEffect(() => {
    latest.current = handler;
  });
  useEffect(() => live.onReconnect(() => latest.current()), [live]);
}
