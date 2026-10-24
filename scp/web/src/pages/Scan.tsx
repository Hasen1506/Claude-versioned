// Enterprise 6.1: the phone page a warehouse hand works from. One task at a time in walk order: go to the bin, read
// the bin's label, read the product's, say how many were moved. A hand-held scanner types the code and Enter into
// the field that has the focus; a phone with a camera can read the code itself (BarcodeDetector, where the browser
// has it). Every read is checked again by the server when the task is confirmed (scp/warehouse confirm_task).
import { useEffect, useMemo, useRef, useState } from "react";
import type { Dataset, WarehouseTask } from "../api/types";
import { Badge, Edits, Empty } from "../components/ui";
import { qty } from "../lib/format";
import { Msg, useNames } from "../lib/names";
import { go, href } from "../lib/router";
import { useStore } from "../state/store";
import { binPlaces, whAct } from "./Warehouse";

type Step = "bin" | "product" | "qty";

/** The open tasks of a place (a wave's only, when one is named) in walk order. */
function queue(ds: Dataset, loc: string, wave?: string): WarehouseTask[] {
  const walk = new Map((ds.bins ?? []).filter((b) => b.location === loc).map((b) => [b.id, b.walk ?? 0]));
  const at = (t: WarehouseTask) => walk.get((t.kind === "pick" ? t.from_bin : t.to_bin) ?? "") ?? 1e9;
  return (ds.warehouse_tasks ?? []).filter((t) => t.location === loc && t.status === "open" && (!wave || t.wave === wave))
    .sort((a, b) => at(a) - at(b) || a.id.localeCompare(b.id));
}

/** The bin a task is read at: the one picked from, or put into. */
const binOf = (t: WarehouseTask) => (t.kind === "pick" ? t.from_bin : t.to_bin) ?? null;

function useCamera(onCode: (code: string) => void) {
  const video = useRef<HTMLVideoElement>(null);
  const [on, setOn] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const has = typeof window !== "undefined" && "BarcodeDetector" in window && !!navigator.mediaDevices?.getUserMedia;
  useEffect(() => {
    if (!on) return;
    let stream: MediaStream | null = null;
    let timer = 0;
    let live = true;
    (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
        if (!live || !video.current) return;
        video.current.srcObject = stream;
        await video.current.play();
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const det = new (window as any).BarcodeDetector();
        const look = async () => {
          if (!live || !video.current) return;
          const found = await det.detect(video.current).catch(() => []);
          if (found.length) { onCode(String(found[0].rawValue)); setOn(false); return; }
          timer = window.setTimeout(look, 250);
        };
        look();
      } catch (e) {
        setErr(`The camera could not be opened: ${String(e)}`);
        setOn(false);
      }
    })();
    return () => { live = false; window.clearTimeout(timer); stream?.getTracks().forEach((t) => t.stop()); };
  }, [on, onCode]);
  return { has, on, setOn, err, video };
}

export function Scan({ route }: { route: string[] }) {
  const ds = useStore((s) => s.dataset)!;
  const nm = useNames();
  const places = useMemo(() => binPlaces(ds), [ds]);
  const loc = route[1] && places.includes(route[1]) ? route[1] : places[0] ?? "";
  const wave = route[2] || undefined;
  const list = useMemo(() => queue(ds, loc, wave), [ds, loc, wave]);
  const [current, setCurrent] = useState<string | null>(null);
  const task = list.find((t) => t.id === current) ?? list[0] ?? null;
  const [step, setStep] = useState<Step>("bin");
  const [code, setCode] = useState("");
  const [binRead, setBinRead] = useState<string | null>(null);
  const [prodRead, setProdRead] = useState<string | null>(null);
  const [count, setCount] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const field = useRef<HTMLInputElement>(null);
  useEffect(() => { setStep("bin"); setCode(""); setBinRead(null); setProdRead(null); setCount(task ? String(task.qty) : ""); },
    [task?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { field.current?.focus(); }, [step, task?.id]);

  const product = task ? (ds.products ?? []).find((p) => p.id === task.product) : undefined;
  const read = (raw: string) => {
    const s = raw.trim();
    if (!task || !s) return;
    setErr(null);
    if (step === "bin") {
      const want = binOf(task);
      // a put-away may go to another bin with room (the server decides); a pick is read at its own bin only
      if (task.kind === "pick" && s !== (want ?? "")) { setErr(`That is bin ${s}: go to ${want ?? "goods in"}.`); setCode(""); return; }
      setBinRead(s); setStep("product"); setCode("");
    } else if (step === "product") {
      if (s !== task.product && s.toLowerCase() !== (product?.barcode ?? "").toLowerCase()) {
        const other = (ds.products ?? []).find((p) => p.id === s || (p.barcode && p.barcode.toLowerCase() === s.toLowerCase()));
        setErr(other ? `That is ${other.name || other.id}: this task is for ${nm.prod(task.product)}.` : `Code ${s} is none of our products.`);
        setCode(""); return;
      }
      setProdRead(s); setStep("qty"); setCode("");
    }
  };
  const cam = useCamera(read);
  const confirm = async () => {
    if (!task) return;
    const q = Number(count);
    if (!Number.isFinite(q) || q < 0 || q > task.qty) { setErr(`Say between 0 and ${qty(task.qty)}.`); return; }
    setBusy(true); setErr(null);
    try {
      const out = await whAct("confirm", { task: task.id, qty: q, bin: binRead, product: prodRead });
      setMsg(out.report.message);
      setCurrent(out.report.next_task ?? null);
    } catch (e) {
      setErr(String(e).replace(/^Error:\s*/, ""));
    } finally {
      setBusy(false);
    }
  };

  if (!places.length) return <div className="content"><Empty title="No bins yet">This company keeps no bins. <a href={href("warehouse")}>Warehouse</a></Empty></div>;
  const where = task ? binOf(task) ?? (task.kind === "pick" ? "goods in" : "") : "";
  return (
    <div className="content scan">
      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        <select className="select" aria-label="Scan at" value={loc} onChange={(e) => go("scan", e.target.value)}>
          {places.map((p) => <option key={p} value={p}>{nm.loc(p)}</option>)}
        </select>
        {wave && <Badge sev="info">wave {wave}</Badge>}
        <span className="spacer" />
        <span className="faint">{list.length} to do</span>
      </div>
      {msg && <div className="banner info" role="status"><Badge sev="ok">Done</Badge><span><Msg text={msg} /></span></div>}
      {err && <div className="banner error" role="alert"><Badge sev="error">Not that</Badge><span>{err}</span></div>}
      {!task ? <Empty title="Nothing left to do">{wave ? `Every pick of ${wave} is confirmed.` : "No open tasks here."} <a href={href("warehouse", "picking", loc)}>Back to the warehouse</a></Empty> : (
        <section className="scan-card" aria-label={`Task ${task.id}`}>
          <div className="scan-what">{task.kind === "pick" ? `Pick for ${task.delivery}` : task.kind === "putaway" ? "Put away" : "Move"}<span className="faint"> · {task.id}</span></div>
          <div className="scan-bin" aria-label="Go to">{task.kind === "pick" ? "From" : "To"} <strong>{where || "—"}</strong></div>
          <div className="scan-prod"><strong>{qty(task.qty)}</strong> {nm.prod(task.product)}{task.batch && <> · batch <strong>{task.batch}</strong></>}</div>
          <ol className="scan-steps">
            <li className={step === "bin" ? "on" : "done"}>Bin {binRead ? <>✓ {binRead}</> : "—"}</li>
            <li className={step === "product" ? "on" : step === "qty" ? "done" : ""}>Product {prodRead ? "✓" : "—"}</li>
            <li className={step === "qty" ? "on" : ""}>Quantity</li>
          </ol>
          <Edits>
            {step !== "qty" ? (
              <form onSubmit={(e) => { e.preventDefault(); read(code); }} className="stack">
                <input ref={field} className="input scan-input" value={code} onChange={(e) => setCode(e.target.value)} autoComplete="off"
                  inputMode="text" aria-label={step === "bin" ? "Scan the bin" : "Scan the product"}
                  placeholder={step === "bin" ? `Read the label of ${where}` : `Read the label of ${nm.prod(task.product)}`} />
                <div className="row" style={{ gap: 8 }}>
                  <button className="btn primary" type="submit" disabled={!code.trim()}>OK</button>
                  {cam.has && <button className="btn" type="button" onClick={() => cam.setOn(!cam.on)}>{cam.on ? "Stop the camera" : "Use the camera"}</button>}
                </div>
                {cam.on && <video ref={cam.video} className="scan-video" muted playsInline />}
                {cam.err && <p className="faint">{cam.err}</p>}
              </form>
            ) : (
              <form onSubmit={(e) => { e.preventDefault(); confirm(); }} className="stack">
                <label htmlFor="scan-qty">How many did you {task.kind === "pick" ? "pick" : "put there"}?</label>
                <input id="scan-qty" ref={field} className="input scan-input" type="number" inputMode="decimal" min={0} max={task.qty}
                  value={count} onChange={(e) => setCount(e.target.value)} aria-label="Quantity moved" />
                <button className="btn primary" type="submit" disabled={busy}>{busy ? "Confirming…" : "Confirm"}</button>
              </form>
            )}
          </Edits>
          <div className="row" style={{ gap: 8, marginTop: 8 }}>
            {list.length > 1 && <button className="btn sm ghost" onClick={() => {
              const i = list.findIndex((t) => t.id === task.id);
              setCurrent(list[(i + 1) % list.length].id);
            }}>Skip for now</button>}
          </div>
        </section>
      )}
    </div>
  );
}
