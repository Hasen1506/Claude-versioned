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

let conn: Promise<IDBDatabase> | null = null;
let ready: IDBDatabase | null = null;        // the open connection, once open: a reload can write through it at once
function open(): Promise<IDBDatabase> {
  conn ??= new Promise<IDBDatabase>((resolve, reject) => {
    if (typeof indexedDB === "undefined") { reject(new Error("no IndexedDB")); return; }
    const r = indexedDB.open(DB, 1);
    r.onupgradeneeded = () => { r.result.createObjectStore(STORE); };
    r.onsuccess = () => {
      ready = r.result;
      ready.onclose = () => { ready = null; conn = null; };
      ready.onversionchange = () => { ready?.close(); ready = null; conn = null; };
      resolve(r.result);
    };
    r.onerror = () => { conn = null; reject(r.error); };
  });
  return conn;
}

let timer: ReturnType<typeof setTimeout> | undefined;
let pending: (() => [unknown, unknown[], unknown[]]) | null = null;

function write(db: IDBDatabase, [current, past, future]: [unknown, unknown[], unknown[]]) {
  const p = past.slice(-KEEP), f = future.slice(-KEEP);
  const tx = db.transaction(STORE, "readwrite");
  if (!current || (!p.length && !f.length)) tx.objectStore(STORE).delete(KEY);
  else tx.objectStore(STORE).put({ at: fingerprint(current), past: p, future: f } satisfies UndoSteps, KEY);
  tx.commit?.();
}

/** Keep the steps a moment after the last change (a burst of edits writes once); `now` gives the working copy and
 *  its steps as they are then. A reload or a closed tab before that moment writes them at once (UNDO-03: an edit
 *  followed by a quick reload lost its undo). */
export function keepSteps(now: () => [unknown, unknown[], unknown[]]) {
  clearTimeout(timer);
  pending = now;
  void open().catch(() => undefined);           // opened ahead, so a reload can write synchronously
  timer = setTimeout(() => {
    const take = pending;
    pending = null;
    if (!take) return;
    void (async () => {
      try { write(await open(), take()); } catch { /* undo after a reload is lost, nothing else */ }
    })();
  }, 800);
}

/** Write steps still waiting for their moment now (the page is going away). */
export function flushSteps() {
  if (!pending) return;
  clearTimeout(timer);
  const take = pending;
  pending = null;
  try {
    if (ready) write(ready, take());
    else void open().then((db) => write(db, take())).catch(() => undefined);
  } catch { /* lost, as before */ }
}

if (typeof window !== "undefined") window.addEventListener("pagehide", flushSteps);

/** The steps kept for this working copy, or null. */
export async function stepsFor(current: unknown): Promise<UndoSteps | null> {
  try {
    const db = await open();
    const got = await new Promise<UndoSteps | undefined>((resolve, reject) => {
      const r = db.transaction(STORE, "readonly").objectStore(STORE).get(KEY);
      r.onsuccess = () => resolve(r.result as UndoSteps | undefined);
      r.onerror = () => reject(r.error);
    });
    return got && got.at === fingerprint(current) ? got : null;
  } catch {
    return null;
  }
}
