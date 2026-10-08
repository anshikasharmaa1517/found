import { useCallback, useEffect, useState } from "react";

import { ApiError } from "./api/client";

export type Load<T> =
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "error"; error: ApiError };

function asApiError(err: unknown): ApiError {
  return err instanceof ApiError
    ? err
    : new ApiError(0, "INTERNAL", "Something went wrong. Try again.");
}

/**
 * Runs `load` when `key` changes and ignores answers that arrive after a newer request,
 * so fast typing or navigation never shows stale results.
 */
export function useLoad<T>(
  key: string,
  load: () => Promise<T>,
): [Load<T>, () => void] {
  const [state, setState] = useState<{ key: string; load: Load<T> }>({
    key,
    load: { status: "loading" },
  });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let current = true;
    load().then(
      (data) => current && setState({ key, load: { status: "ready", data } }),
      (err: unknown) => current && setState({ key, load: { status: "error", error: asApiError(err) } }),
    );
    return () => {
      current = false;
    };
    // `load` is rebuilt every render; `key` and `attempt` say when to really fetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, attempt]);

  const retry = useCallback(() => {
    setState((s) => ({ ...s, load: { status: "loading" } }));
    setAttempt((n) => n + 1);
  }, []);

  return [state.key === key ? state.load : { status: "loading" }, retry];
}

export { asApiError };
