import { useCallback, useEffect, useState } from "react";

export type ApiState<T> = { data: T | undefined; error: unknown; loading: boolean; reload: () => void };

/** Run `load` when `deps` change; `reload()` runs it again. The last data stays visible while reloading. */
export function useApi<T>(load: () => Promise<T>, deps: unknown[]): ApiState<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    setLoading(true);
    load().then(
      (result) => {
        if (!live) return;
        setData(result);
        setError(null);
        setLoading(false);
      },
      (failure: unknown) => {
        if (!live) return;
        setError(failure);
        setLoading(false);
      },
    );
    return () => {
      live = false;
    };
  }, [...deps, tick]); // `deps` are the caller's dependencies of `load`
  const reload = useCallback(() => setTick((n) => n + 1), []);
  return { data, error, loading, reload };
}
