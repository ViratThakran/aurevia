"use client";

import { useCallback, useEffect, useState } from "react";

import { api, errorMessage, type RequestOptions } from "./api";

/** GET a resource; `path === null` waits (e.g. until an id is known). */
export function useApi<T>(path: string | null, query?: RequestOptions["query"]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(path !== null);
  const queryKey = JSON.stringify(query ?? {});

  const reload = useCallback(async () => {
    if (path === null) return;
    setLoading(true);
    try {
      setData(await api<T>(path, { query: JSON.parse(queryKey) }));
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }, [path, queryKey]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, error, loading, reload, setData };
}

/** Run a mutation with pending and error state. Resolves to the result, or null on error. */
export function useAction() {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async <T,>(action: () => Promise<T>): Promise<T | null> => {
    setPending(true);
    setError(null);
    try {
      return await action();
    } catch (e) {
      setError(errorMessage(e));
      return null;
    } finally {
      setPending(false);
    }
  }, []);

  return { pending, error, setError, run };
}
