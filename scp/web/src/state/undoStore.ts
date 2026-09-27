// Undo that survives a reload (R19): the undo and redo steps are kept in this browser's IndexedDB with a fingerprint
// of the working copy they lead back from, and taken back only when the reloaded working copy is that one. Anything
// failing here (private window, storage full) costs only the undo after a reload.

const DB = "scp";
const STORE = "undo";
const KEY = "steps";
const KEEP = 30;               // steps kept each way across a reload (in memory there are more)

export interface UndoSteps { at: string; past: unknown[]; future: unknown[] }

/** A fingerprint of a working copy (FNV-1a over its JSON text, and its length). */
export function fingerprint(doc: unknown): string {
  const s = JSON.stringify(doc) ?? "";
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return `${s.length}:${h.toString(16)}`;
}

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") { reject(new Error("no IndexedDB")); return; }
    const r = indexedDB.open(DB, 1);
    r.onupgradeneeded = () => { r.result.createObjectStore(STORE); };
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}

let timer: ReturnType<typeof setTimeout> | undefined;

/** Keep the steps a moment after the last change (a burst of edits writes once); `now` gives the working copy and
 *  its steps as they are then. */
export function keepSteps(now: () => [unknown, unknown[], unknown[]]) {
  clearTimeout(timer);
  timer = setTimeout(() => {
    const [current, past, future] = now();
    const p = past.slice(-KEEP), f = future.slice(-KEEP);
    void (async () => {
      try {
        const db = await open();
        const tx = db.transaction(STORE, "readwrite");
        if (!current || (!p.length && !f.length)) tx.objectStore(STORE).delete(KEY);
        else tx.objectStore(STORE).put({ at: fingerprint(current), past: p, future: f } satisfies UndoSteps, KEY);
        tx.oncomplete = () => db.close();
      } catch {
        /* undo after a reload is lost, nothing else */
      }
    })();
  }, 800);
}

/** The steps kept for this working copy, or null. */
export async function stepsFor(current: unknown): Promise<UndoSteps | null> {
  try {
    const db = await open();
    const got = await new Promise<UndoSteps | undefined>((resolve, reject) => {
      const r = db.transaction(STORE, "readonly").objectStore(STORE).get(KEY);
      r.onsuccess = () => resolve(r.result as UndoSteps | undefined);
      r.onerror = () => reject(r.error);
    });
    db.close();
    return got && got.at === fingerprint(current) ? got : null;
  } catch {
    return null;
  }
}
