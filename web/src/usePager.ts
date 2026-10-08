import { useState } from "react";

import type { ApiError } from "./api/client";
import { asApiError } from "./useLoad";

interface PagerState<T> {
  key: string;
  items: T[];
  /** undefined until the first "load more": then the first page's cursor applies. */
  next: string | null | undefined;
  busy: boolean;
  error: ApiError | null;
}

/** Further pages after a first page loaded elsewhere. Resets whenever `key` changes. */
export function usePager<T>(
  key: string,
  firstNext: string | null,
  fetchPage: (cursor: string) => Promise<{ items: T[]; next: string | null }>,
) {
  const [state, setState] = useState<PagerState<T>>({
    key,
    items: [],
    next: undefined,
    busy: false,
    error: null,
  });
  const current: PagerState<T> =
    state.key === key ? state : { key, items: [], next: undefined, busy: false, error: null };
  const next = current.next === undefined ? firstNext : current.next;

  async function loadMore() {
    if (!next || current.busy) return;
    setState({ ...current, next, busy: true, error: null });
    try {
      const page = await fetchPage(next);
      setState((s) =>
        s.key === key
          ? { key, items: [...s.items, ...page.items], next: page.next, busy: false, error: null }
          : s,
      );
    } catch (err) {
      setState((s) => (s.key === key ? { ...s, busy: false, error: asApiError(err) } : s));
    }
  }

  return { items: current.items, hasMore: Boolean(next), busy: current.busy, error: current.error, loadMore };
}
