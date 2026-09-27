// Sign-in and the companies kept on the server (Phase I, Q14): sign in or make an account, open a company, keep the
// company in this browser on the server, and (for an owner) say who may see and change it.
import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { AuthConfig, CompanyMeta, Member } from "../api/types";
import { Badge, Empty, Panel, StageHeader } from "../components/ui";
import { when } from "../components/SaveStatus";
import { go, href } from "../lib/router";
import { store, unsaved, useStore } from "../state/store";

const ROLE_TEXT: Record<string, string> = {
  owner: "changes the data and who may see it",
  planner: "changes the data",
  viewer: "looks, changes nothing",
};

const kb = (n: number) => n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1e3))} KB`;

export function useAuthConfig(): AuthConfig | null {
  const [cfg, setCfg] = useState<AuthConfig | null>(null);
  useEffect(() => { api.authConfig().then(setCfg).catch(() => setCfg(null)); }, []);
  return cfg;
}

/** Sign in, or make an account. */
export function SignIn({ config, onDone }: { config: AuthConfig | null; onDone?: () => void }) {
  const canSignUp = !config || config.signup === "open" || config.first_account || config.signup === "invite";
  const [mode, setMode] = useState<"in" | "up">(config?.first_account ? "up" : "in");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (config?.first_account) setMode("up"); }, [config?.first_account]);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const s = mode === "in" ? await api.signIn(email, password) : await api.signUp(email, name, password);
      store.signedIn({ token: s.token, user: s.user });
      setPassword("");
      onDone?.();
    } catch (x) {
      setErr(x instanceof Error ? x.message : String(x));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="signin stack" onSubmit={submit} aria-label={mode === "in" ? "Sign in" : "Make an account"}>
      <div className="row wrap" style={{ gap: 6 }} role="tablist">
        <button type="button" role="tab" aria-selected={mode === "in"} className={`btn sm ${mode === "in" ? "primary" : "ghost"}`} onClick={() => setMode("in")}>Sign in</button>
        {canSignUp && <button type="button" role="tab" aria-selected={mode === "up"} className={`btn sm ${mode === "up" ? "primary" : "ghost"}`} onClick={() => setMode("up")}>Make an account</button>}
      </div>
      {mode === "up" && config?.signup === "invite" && !config.first_account && <p className="small muted" style={{ margin: 0 }}>
        This server takes new accounts by invitation: use the e-mail a company owner invited.</p>}
      {mode === "up" && config?.first_account && <p className="small muted" style={{ margin: 0 }}>Nobody has an account on this server yet: yours is the first.</p>}
      <label className="stack-field"><span>E-mail</span>
        <input className="input" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></label>
      {mode === "up" && <label className="stack-field"><span>Your name</span>
        <input className="input" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} placeholder="as colleagues see it in the history" /></label>}
      <label className="stack-field"><span>Password{mode === "up" && <span className="faint"> (at least 8 characters)</span>}</span>
        <input className="input" type="password" autoComplete={mode === "in" ? "current-password" : "new-password"} required minLength={mode === "up" ? 8 : undefined}
          value={password} onChange={(e) => setPassword(e.target.value)} /></label>
      {err && <div className="banner error" role="alert" style={{ margin: 0 }}>{err}</div>}
      <div><button className="btn accent" disabled={busy}>{busy ? "…" : mode === "in" ? "Sign in" : "Make the account"}</button></div>
    </form>
  );
}

/** The companies this account may open. */
export function CompanyList({ onOpened }: { onOpened?: () => void }) {
  const session = useStore((s) => s.session);
  const open = useStore((s) => s.company);
  const openId = open?.id;
  const dirty = useStore(unsaved);
  const [list, setList] = useState<CompanyMeta[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const refresh = useCallback(() => {
    if (!session) return;
    api.companies().then(setList).catch((e) => setErr(e instanceof Error ? e.message : String(e)));
  }, [session]);
  useEffect(() => { refresh(); }, [refresh, openId]);
  if (!session) return null;
  const openIt = async (c: CompanyMeta) => {
    if (dirty && !window.confirm(`${open?.name} has changes that are not saved yet. Open ${c.name} anyway?`)) return;
    try {
      store.openCompany(await api.company(c.id));
      onOpened?.();
      go("home");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };
  if (err) return <div className="banner error">{err}</div>;
  if (!list) return <div className="faint">Loading…</div>;
  if (!list.length) return <p className="muted small" style={{ margin: 0 }}>No company is kept on the server for you yet.</p>;
  return (
    <ul className="company-list">
      {list.map((c) => (
        <li key={c.id}>
          <button className="example" onClick={() => openIt(c)} aria-label={`Open ${c.name}`}>
            <b>{c.name}{open?.id === c.id && open.live && <span className="faint"> · open</span>}</b>
            <span className="faint small">{c.role} · saved {when(c.updated_at)} by {c.updated_by} · {kb(c.size)}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function Members({ id, role }: { id: string; role: string }) {
  const me = useStore((s) => s.session?.user);
  const [list, setList] = useState<Member[] | null>(null);
  const [email, setEmail] = useState("");
  const [newRole, setNewRole] = useState("planner");
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => { api.members(id).then(setList).catch((e) => setErr(String(e))); }, [id]);
  const owner = role === "owner";
  const act = async (f: () => Promise<Member[]>, done: string) => {
    setErr(null);
    setMsg(null);
    try { setList(await f()); setMsg(done); } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };
  return (
    <div className="stack" style={{ gap: 10 }}>
      {!list ? <div className="faint">Loading…</div> : (
        <div className="table-wrap">
          <table className="t">
            <thead><tr><th>Who</th><th>Role</th><th>Since</th>{owner && <th />}</tr></thead>
            <tbody>
              {list.map((m) => (
                <tr key={m.email}>
                  <td><b>{m.name || m.email}</b>{m.name && <div className="faint small">{m.email}</div>}
                    {!m.user_id && <div><Badge sev="info">invited</Badge> <span className="faint small">joins on signing up with this e-mail</span></div>}</td>
                  <td>{owner && m.email !== me?.email ? (
                    <select className="select" aria-label={`Role of ${m.email}`} value={m.role}
                      onChange={(e) => act(() => api.setMember(id, m.email, e.target.value), `${m.name || m.email} is now ${e.target.value === "owner" ? "an" : "a"} ${e.target.value}.`)}>
                      <option value="owner">owner</option><option value="planner">planner</option><option value="viewer">viewer</option>
                    </select>) : <>{m.role}{m.email === me?.email && <span className="faint"> (you)</span>}</>}
                    <div className="faint small">{ROLE_TEXT[m.role]}</div></td>
                  <td className="small">{when(m.since)}</td>
                  {owner && <td>{m.email !== me?.email && <button className="btn sm ghost" aria-label={`Remove ${m.email}`}
                    onClick={() => { if (window.confirm(`Remove ${m.name || m.email} from this company?`)) void act(() => api.removeMember(id, m.email), `${m.name || m.email} removed.`); }}>Remove</button>}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {owner && <form className="row wrap inline-form" style={{ gap: 8 }} onSubmit={(e) => {
        e.preventDefault();
        const who = email.trim();
        void act(() => api.setMember(id, who, newRole), `${who} added as ${newRole}; if they have no account yet, they join on signing up with that e-mail.`).then(() => setEmail(""));
      }}>
        <input className="input" type="email" required placeholder="colleague@company.com" aria-label="Colleague's e-mail" value={email}
          onChange={(e) => setEmail(e.target.value)} />
        <select className="select" aria-label="Their role" value={newRole} onChange={(e) => setNewRole(e.target.value)}>
          <option value="planner">planner</option><option value="viewer">viewer</option><option value="owner">owner</option>
        </select>
        <button className="btn">Add</button>
      </form>}
      {!owner && <p className="small muted" style={{ margin: 0 }}>Only an owner adds people or changes their role.</p>}
      {msg && <div className="banner ok" style={{ margin: 0 }}>{msg}</div>}
      {err && <div className="banner error" style={{ margin: 0 }}>{err}</div>}
    </div>
  );
}

function Password() {
  const [old, setOld] = useState("");
  const [next, setNext] = useState("");
  const [msg, setMsg] = useState<[string, boolean] | null>(null);
  return (
    <form className="row wrap inline-form" style={{ gap: 8 }} onSubmit={async (e) => {
      e.preventDefault();
      try { await api.changePassword(old, next); setMsg(["Password changed.", true]); setOld(""); setNext(""); }
      catch (x) { setMsg([x instanceof Error ? x.message : String(x), false]); }
    }}>
      <input className="input" type="password" autoComplete="current-password" placeholder="Current password" aria-label="Current password" required value={old} onChange={(e) => setOld(e.target.value)} />
      <input className="input" type="password" autoComplete="new-password" placeholder="New password (8+ characters)" aria-label="New password" required minLength={8} value={next} onChange={(e) => setNext(e.target.value)} />
      <button className="btn">Change password</button>
      {msg && <span className={`small ${msg[1] ? "" : "banner error"}`}>{msg[0]}</span>}
    </form>
  );
}

export function Account() {
  const session = useStore((s) => s.session);
  const company = useStore((s) => s.company);
  const ds = useStore((s) => s.dataset);
  const dirty = useStore(unsaved);
  const config = useAuthConfig();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const keepOnServer = async () => {
    if (!ds) return;
    setBusy(true);
    setErr(null);
    try {
      const m = await api.createCompany(ds, "moved from a browser");
      store.openCompany(await api.company(m.id));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const signOut = async () => {
    if (company && dirty) {
      await store.saveNow();
      if (unsaved(store.get()) && !window.confirm(`${company.name} has changes that could not be saved. Sign out and lose them?`)) return;
    }
    await store.signOut();
  };

  return (
    <div>
      <StageHeader title="Your company on the server" kicker={<>Keep the company on the server instead of only in this browser:
        colleagues can open it, every change is saved as you go, and the history shows who changed what.</>}
        how={<>Each save is a revision. A save made on top of an older revision than the latest is refused, so nobody overwrites
          a colleague's work unseen. The document of each person's run of saves within ten minutes is kept, so the company can be
          put back to an earlier state.</>} />
      <div className="content">
        {!session ? (
          <div className="welcome-grid">
            <section className="hcard">
              <h2 className="q">Sign in</h2>
              {config?.require_signin && <p className="muted small">This server keeps companies only for signed-in people.</p>}
              <SignIn config={config} />
            </section>
            <section className="hcard">
              <h2 className="q">Why sign in</h2>
              <ul className="small" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.6 }}>
                <li>The company is not lost when this browser's data is cleared, and it is not limited to what a browser can hold.</li>
                <li>Colleagues work on the same company: owners, planners who change it, viewers who only look.</li>
                <li>Every save is recorded with who made it and what changed; an earlier state can be put back.</li>
              </ul>
              {ds && !company && <p className="small muted">After signing in you can keep <b>{ds.settings.company_name}</b>, open in this browser now, on the server.</p>}
            </section>
          </div>
        ) : (
          <>
            <Panel title={`Signed in as ${session.user.name}`} actions={<button className="btn sm" onClick={signOut}>Sign out</button>}>
              <p className="small muted" style={{ marginTop: 0 }}>{session.user.email}{company && <> · signing out closes {company.name} on this browser; it stays on the server</>}</p>
              <Password />
            </Panel>
            {ds && !company && (
              <Panel title="This browser's company">
                <div className="row wrap" style={{ gap: 10 }}>
                  <span><b>{ds.settings.company_name}</b> is kept only in this browser.</span>
                  <button className="btn accent" disabled={busy} onClick={keepOnServer}>{busy ? "Keeping it…" : "Keep it on the server"}</button>
                </div>
                <p className="small muted" style={{ marginBottom: 0 }}>You become its owner and can then invite colleagues. From then on every change is saved to the server.</p>
                {err && <div className="banner error">{err}</div>}
              </Panel>
            )}
            {company && (
              <Panel title={`${company.name}: who may see and change it`} actions={<a className="small" href={href("history")}>History →</a>}>
                <Members id={company.id} role={company.role} />
              </Panel>
            )}
            <Panel title="Your companies on the server">
              <CompanyList />
            </Panel>
          </>
        )}
        {!session && !ds && <Empty title="No company open">Sign in to open a company kept on the server, or go back to <a href="#/">the start</a>.</Empty>}
      </div>
    </div>
  );
}
