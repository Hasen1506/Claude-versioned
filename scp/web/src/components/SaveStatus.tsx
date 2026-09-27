// Where the working copy is kept, and whether the latest change is saved (Phase I, Q14). The chip sits in the top
// bar on every page; the banner under it speaks up only when something needs the planner: a colleague saved in
// between, a save failed, a viewer tried to change something, a plan version is open instead of the live data, or
// this browser could not keep a company that exists only here.
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Clash } from "../api/types";
import { href, go } from "../lib/router";
import { store, unsaved, useStore } from "../state/store";

/** "Mon 28 Sep, 10:42" in the viewer's time from the server's UTC time. */
export function when(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const today = new Date();
  const time = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === today.toDateString()) return `today ${time}`;
  return `${d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })}, ${time}`;
}

export function SaveChip() {
  const company = useStore((s) => s.company);
  const save = useStore((s) => s.save);
  const dirty = useStore(unsaved);
  const version = useStore((s) => s.version);
  const label = (long: string, short: string) => <><span className="save-long">{long}</span><span className="save-short" aria-hidden>{short}</span></>;
  if (!company) {
    return <a className={`save-chip ${save.localError ? "bad" : ""}`} href={href("account")}
      title="This company is kept only in this browser. Sign in to keep it on the server, where colleagues can work on it too.">
      {save.localError ? label("Not kept · this browser's storage failed", "Not kept") : label("In this browser only", "Local")}</a>;
  }
  if (!company.live) {
    return <a className="save-chip warn" href={href("versions")} title="A plan version is open, not the company's live data">
      {label(version ? `${version.id} open · not the live data` : "Not the live data", version?.id ?? "Version")}</a>;
  }
  const [cls, text, short, title] =
    save.status === "readonly" ? ["", "View only", "View only", "You are a viewer of this company: you can look at everything but not change it"]
    : save.status === "conflict" ? ["bad", "Not saved · saved by someone else", "Not saved", "Someone else saved this company after your changes began"]
    : save.status === "failed" ? ["bad", "Not saved", "Not saved", save.error ?? "The last save failed"]
    : save.status === "saving" ? ["", "Saving…", "Saving…", "Saving your changes to the server"]
    : dirty || save.status === "pending" ? ["", "Unsaved changes", "Unsaved", "Saved to the server a moment after your last change"]
    : ["ok", save.at ? `Saved ${save.at}` : "Saved", "Saved", `${company.name} is kept on the server: every change is saved as you go`];
  return <a className={`save-chip ${cls}`} href={href("history")} title={title} aria-live="polite">
    <span className="save-dot" aria-hidden />{label(text, short)}</a>;
}

/** Speaks up when saving needs the planner. */
export function SaveBanner() {
  const company = useStore((s) => s.company);
  const save = useStore((s) => s.save);
  const ds = useStore((s) => s.dataset);
  const version = useStore((s) => s.version);
  const [busy, setBusy] = useState(false);
  const [merged, setMerged] = useState<string | null>(null);
  const [clashes, setClashes] = useState<Clash[] | null>(null);
  const [refusedShown, setRefusedShown] = useState(false);
  const revision = company?.revision;
  useEffect(() => { setMerged(null); setClashes(null); }, [revision]);   // what a merge did is news until the next save
  useEffect(() => {
    if (!save.refused) return;
    setRefusedShown(true);
    const t = setTimeout(() => setRefusedShown(false), 6000);
    return () => clearTimeout(t);
  }, [save.refused]);
  if (!ds) return null;
  const reopen = async () => {
    if (!company) return;
    setBusy(true);
    try { store.openCompany(await api.company(company.id)); } finally { setBusy(false); }
  };
  const download = () => {
    const blob = new Blob([JSON.stringify(ds, null, 1)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${(ds.settings.company_name || "company").replace(/[^\w-]+/g, "_")}-my-changes.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  if (!company) {
    if (!save.localError) return null;
    return <div className="banner error save-banner" role="alert">
      <b>{save.localError}.</b> A company kept only in this browser is lost if the browser's data is cleared.
      <a href={href("account")}>Keep it on the server</a> or <button className="btn sm" onClick={download}>Download a copy</button>
    </div>;
  }
  if (!company.live) {
    return <div className="banner info save-banner">
      <span>You are looking at {version ? <b>plan version {version.id} “{version.name}”</b> : "a plan version"}, not {company.name}'s live data.
        Changes here are saved in <a href={href("versions")}>Versions</a>, not to the company.</span>
      <span className="spacer" />
      <button className="btn sm" disabled={busy} onClick={reopen}>Back to the live data</button>
      {company.role !== "viewer" && <button className="btn sm" disabled={busy} onClick={async () => {
        if (!window.confirm(`Make ${version ? version.id : "this version"} ${company.name}'s live data? Everyone then works on it. The data it replaces stays in the company's history.`)) return;
        setBusy(true);
        try {
          const m = (await api.companies()).find((x) => x.id === company.id);
          if (m) store.useAsCompanyData(m.revision, version ? `from plan version ${version.id} “${version.name}”` : "from a plan version");
        } finally { setBusy(false); }
      }}>Make this the live data</button>}
    </div>;
  }
  if (save.status === "conflict" && save.conflict && clashes) {
    return <ClashChooser by={save.conflict.by} clashes={clashes} busy={busy}
      onCancel={() => setClashes(null)}
      onMerge={async (choose) => {
        setBusy(true);
        try { setMerged(await store.mergeMine(choose)); setClashes(null); }
        catch (e) { setMerged(e instanceof Error ? e.message : String(e)); setClashes(null); }
        finally { setBusy(false); }
      }} />;
  }
  if (save.status === "conflict" && save.conflict) {
    const c = save.conflict;
    return <div className="banner error save-banner" role="alert">
      <span><b>Not saved: {c.by} saved {company.name} {when(c.at)}</b>, after your changes began. Your changes are still here,
        on this screen only. <b>Merge</b> keeps both: what only one of you changed is taken, an order you both took
        under the same number gets the next number, and where you both changed a record you choose whose to keep.</span>
      <span className="spacer" />
      <button className="btn sm accent" disabled={busy} onClick={async () => {
        setBusy(true);
        try {
          const rep = await store.previewMerge();
          if (rep.clashes?.length) setClashes(rep.clashes);
          else setMerged(await store.mergeMine());
        } catch (e) { setMerged(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
      }}>Merge both</button>
      <button className="btn sm" disabled={busy} onClick={async () => {
        if (!window.confirm(`Drop your unsaved changes and open ${c.by}'s save?`)) return;
        await reopen();
      }}>Open {c.by}'s (drop mine)</button>
      <button className="btn sm" disabled={busy} title={`Your copy becomes the latest and what ${c.by} changed is undone; their save stays in the history and can be put back`}
        onClick={async () => {
          if (!window.confirm(`Replace ${c.by}'s save with yours? What ${c.by} changed is undone (it stays in the history).`)) return;
          setBusy(true); try { await store.keepMine(); } finally { setBusy(false); }
        }}>Replace theirs with mine</button>
      <button className="btn sm ghost" onClick={download}>Download mine</button>
    </div>;
  }
  const news = merged ?? save.merged;
  if (news) {
    return <div className="banner ok save-banner" role="status">
      <span>{news}</span><span className="spacer" />
      <a href={href("history")}>History</a>
      <button className="btn sm ghost" onClick={() => { setMerged(null); store.clearMerged(); }}>OK</button>
    </div>;
  }
  if (save.status === "failed") {
    const signIn = save.error?.includes("sign in");
    return <div className="banner error save-banner" role="alert">
      <span><b>Not saved.</b> {save.error}. Your changes are still here.</span>
      <span className="spacer" />
      {signIn ? <button className="btn sm" onClick={() => go("account")}>Sign in</button>
        : <button className="btn sm" onClick={() => { void store.saveNow(); }}>Try again</button>}
      <button className="btn sm ghost" onClick={download}>Download a copy</button>
    </div>;
  }
  if (save.newer) {
    return <div className="banner info save-banner">
      <span><b>{save.newer.by}</b> saved {company.name} {when(save.newer.at)}.</span>
      <button className="btn sm" disabled={busy} onClick={reopen}>Show their changes</button>
      <a href={href("history")}>What changed</a>
    </div>;
  }
  if (refusedShown && company.role === "viewer") {
    return <div className="banner warning save-banner" role="status">
      <b>Nothing was changed:</b> you are a viewer of {company.name}. Ask an owner to make you a planner to change it.
    </div>;
  }
  return null;
}

/** A value as it reads in the side-by-side choice. */
function shown(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") return v.toLocaleString("en-IN", { maximumFractionDigits: 4 });
  if (typeof v === "boolean") return v ? "yes" : "no";
  const s = typeof v === "string" ? v : JSON.stringify(v);
  return s.length > 60 ? `${s.slice(0, 57)}…` : s;
}

/** Each record both people changed, their two versions side by side, and whose to keep (N65). Records that belong
 *  together (an order and its promises) are chosen as one, so an order never keeps one person's quantity and its
 *  promise the other's. */
function ClashChooser({ by, clashes, busy, onMerge, onCancel }: {
  by: string; clashes: Clash[]; busy: boolean;
  onMerge: (choose: Record<string, "mine" | "theirs">) => void; onCancel: () => void;
}) {
  const groups = [...new Set(clashes.map((c) => c.group || c.id))];
  const [pick, setPick] = useState<Record<string, "mine" | "theirs">>(() =>
    Object.fromEntries(groups.map((g) => [g, clashes.find((c) => (c.group || c.id) === g)!.kept as "mine" | "theirs"])));
  const all = (w: "mine" | "theirs") => setPick(Object.fromEntries(groups.map((g) => [g, w])));
  const nMine = Object.values(pick).filter((w) => w === "mine").length;
  const choose = () => Object.fromEntries(clashes.map((c) => [c.id, pick[c.group || c.id]]));
  const pretty = (r: string) => r.replace(/ \| /g, " · ").replace(/_/g, " ");
  return <div className="banner warning save-banner clash-chooser" role="alertdialog" aria-label="Choose whose change to keep">
    <div className="clash-head">
      <b>You and {by} both changed {groups.length === 1 ? "one record" : `${groups.length} records`}.</b> Everything
      else is merged. Choose whose version to keep for each:
      <span className="spacer" />
      <button className="btn sm ghost" disabled={busy} onClick={() => all("mine")}>All mine</button>
      <button className="btn sm ghost" disabled={busy} onClick={() => all("theirs")}>All {by}'s</button>
    </div>
    <div className="clash-list">
      {groups.map((g) => {
        const cs = clashes.filter((c) => (c.group || c.id) === g);
        const order = cs.some((c) => c.list === "orders and forecasts") && cs.length > 1;
        const title = order ? `Order ${g} and its promise${cs.length > 2 ? "s" : ""}`
          : cs.length > 1 ? `${g}: ${[...new Set(cs.map((c) => c.list))].join(", ")}`
          : `${cs[0].list}${cs[0].record ? ":" : ""} ${pretty(cs[0].record)}`;
        return <fieldset key={g} className="clash">
          <legend>{title}</legend>
          <div className="table-wrap"><table className="t small">
            <thead><tr><th>Field</th><th>Before</th>
              <th><label><input type="radio" name={`k-${g}`} checked={pick[g] === "mine"} disabled={busy}
                onChange={() => setPick({ ...pick, [g]: "mine" })} /> Yours</label></th>
              <th><label><input type="radio" name={`k-${g}`} checked={pick[g] === "theirs"} disabled={busy}
                onChange={() => setPick({ ...pick, [g]: "theirs" })} /> {by}'s</label></th></tr></thead>
            <tbody>
              {cs.map((c) => [
                c.mine_removed || c.theirs_removed
                  ? <tr key={`${c.id}-rm`}><td>{cs.length > 1 ? `${c.list}: ` : ""}the record</td><td>—</td>
                    <td>{c.mine_removed ? <i>removed</i> : "changed"}</td><td>{c.theirs_removed ? <i>removed</i> : "changed"}</td></tr>
                  : null,
                ...c.fields.map((f) => <tr key={`${c.id}-${f.path}`}>
                  <td>{cs.length > 1 ? `${c.list}: ` : ""}{f.path.replace(/_/g, " ") || "value"}</td><td className="muted">{shown(f.base)}</td>
                  <td className={pick[g] === "mine" ? "strong" : ""}>{shown(f.mine)}</td>
                  <td className={pick[g] === "theirs" ? "strong" : ""}>{shown(f.theirs)}</td></tr>),
              ])}
            </tbody>
          </table></div>
        </fieldset>;
      })}
    </div>
    <div className="clash-head">
      <span className="spacer" />
      <button className="btn sm" disabled={busy} onClick={onCancel}>Back</button>
      <button className="btn sm accent" disabled={busy} onClick={() => onMerge(choose())}>
        Merge, keeping {nMine === 0 ? `${by}'s` : nMine === groups.length ? "mine" : `mine for ${nMine}, ${by}'s for ${groups.length - nMine}`}</button>
    </div>
  </div>;
}
