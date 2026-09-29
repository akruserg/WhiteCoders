import { useCallback, useEffect, useRef, useState } from "react";

export interface Loaded<T> { data: T | null; error: Error | null; loading: boolean; reload: () => void }

/** Загрузка данных с перезапросом по deps и опциональным опросом (poll, мс). */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = [], poll?: number): Loaded<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    let alive = true;
    const run = (first: boolean) => {
      if (first) setLoading(true);
      fnRef.current()
        .then((d) => { if (alive) { setData(d); setError(null); } })
        .catch((e) => { if (alive) setError(e); })
        .finally(() => { if (alive && first) setLoading(false); });
    };
    run(true);
    const id = poll ? setInterval(() => run(false), poll) : undefined;
    return () => { alive = false; if (id) clearInterval(id); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick, poll]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}

/** Секундомер обратного отсчёта до момента deadline (мс с эпохи). */
export function useCountdown(deadline: number | null) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (deadline == null) return;
    const id = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(id);
  }, [deadline]);
  return deadline == null ? null : Math.round((deadline - now) / 1000);
}
