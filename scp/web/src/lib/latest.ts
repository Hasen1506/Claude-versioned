import { useCallback, useEffect, useRef, useState, type DependencyList } from "react";

/** A panel that reads its list when it opens and then replaces it with the answer of each change made on it (an
 *  invitation, a new key, a saved import): the newest answer shown wins. A read asked before a change and delivered
 *  after it (the server answered it first, the browser handed it over late) is dropped instead of putting back the
 *  list without the change (scp run 37731060982: an invited person vanished from the members). A read asked for
 *  other `deps` (another company, another filter) is dropped too.
 *
 *  `read` null: nothing to read (e.g. not allowed). `show(v)`: a change's answer, the newest from now on.
 *  `reload()`: read again (that read is newer than every change shown so far). */
export function useLatest<T>(read: (() => Promise<T>) | null, deps: DependencyList) {
  const [value, setValue] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const shown = useRef(0);
  const [tick, setTick] = useState(0);
  const show = useCallback((v: T) => { shown.current += 1; setValue(v); setError(null); }, []);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  useEffect(() => {
    if (!read) return;
    const asked = shown.current;
    let live = true;
    read().then((v) => { if (live && shown.current === asked) show(v); })
      .catch((e) => { if (live && shown.current === asked) setError(e instanceof Error ? e.message : String(e)); });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `read` is a new closure each render; `deps` say when it changes
  }, [...deps, tick]);
  return { value, error, show, reload };
}
