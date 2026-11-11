"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { errorMessage } from "./api/client";

export type Loaded<T> = {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => Promise<void>;
};

/** Load data on mount (and every pollMs). Keeps the last data while refreshing or on poll error. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[], pollMs?: number): Loaded<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const reload = useCallback(async () => {
    try {
      const d = await fnRef.current();
      setData(d);
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    const run = async () => {
      if (alive) await reload();
    };
    void run();
    if (!pollMs) return () => void (alive = false);
    const id = setInterval(() => void run(), pollMs);
    return () => {
      alive = false;
      clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, pollMs, reload]);

  return { data, error, loading, reload };
}
