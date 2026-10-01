// Sign-in and the companies kept on the server (Phase I, Q14): sign in or make an account, open a company, keep the
// company in this browser on the server, and (for an owner) say who may see and change it.
import { useEffect, useRef, useState } from "react";
import { api, SSO_START } from "../api/client";
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
  const [mode, setMode] = useState<"in" | "up" | "forgot">(config?.first_account ? "up" : "in");
  const [sent, setSent] = useState<string | null>(null);
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
      if (mode === "forgot") {
        const r = await api.resetRequest(email);
        setSent(r.mail ? `If ${email} has an account here, a link to set a new password is on its way (it works for an hour).`
          : "This server sends no mail. Ask an owner of your company to make you a link to set a new password (Sign in and companies → people), or the server's administrator.");
        return;
      }
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
    <form className="signin stack" onSubmit={submit} aria-label={mode === "in" ? "Sign in" : mode === "up" ? "Make an account" : "Forgot your password"}>
      {config?.sso && mode !== "forgot" && <>
        <a className="btn accent" href={SSO_START}>Sign in with {config.sso}</a>
        <p className="faint small" style={{ margin: 0 }}>or with an e-mail and a password:</p>
      </>}
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
      {mode !== "forgot" && <label className="stack-field"><span>Password{mode === "up" && <span className="faint"> (at least 8 characters)</span>}</span>
        <input className="input" type="password" autoComplete={mode === "in" ? "current-password" : "new-password"} required minLength={mode === "up" ? 8 : undefined}
          value={password} onChange={(e) => setPassword(e.target.value)} /></label>}
      {err && <div className="banner error" role="alert" style={{ margin: 0 }}>{err}</div>}
      {sent && mode === "forgot" && <div className="banner ok" role="status" style={{ margin: 0 }}>{sent}</div>}
      <div className="row wrap" style={{ gap: 10 }}>
        <button className={`btn ${config?.sso ? "" : "accent"}`} disabled={busy}>{busy ? "…" : mode === "in" ? "Sign in" : mode === "up" ? "Make the account" : "Send me a link"}</button>
        {mode === "in" && <button type="button" className="btn ghost sm" onClick={() => { setMode("forgot"); setErr(null); setSent(null); }}>Forgot your password?</button>}
        {mode === "forgot" && <button type="button" className="btn ghost sm" onClick={() => setMode("in")}>Back to signing in</button>}
      </div>
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
  const openRequest = useRef(0);
  useEffect(() => () => { openRequest.current++; }, [session?.token]);
  useEffect(() => {
    let current = true;
    setList(null);
    setErr(null);
    if (session) api.companies().then((l) => { if (current) setList(l); })
      .catch((e) => { if (current) setErr(e instanceof Error ? e.message : String(e)); });
    return () => { current = false; };
  }, [session, openId]);
  if (!session) return null;
  const openIt = async (c: CompanyMeta) => {
    if (dirty && !window.confirm(`${open?.name} has changes that are not saved yet. Open ${c.name} anyway?`)) return;
    const before = store.captureContext();
    const request = ++openRequest.current;
    setErr(null);
    try {
      const doc = await api.company(c.id);
      if (request !== openRequest.current) return;
      store.assertWorking(before, true);
      store.openCompany(doc);
      onOpened?.();
      go("home");
    } catch (e) {
      if (request === openRequest.current) setErr(e instanceof Error ? e.message : String(e));
    }
  };
  if (!list) return err ? <div className="banner error">{err}</div> : <div className="faint">Loading…</div>;
  if (!list.length) return <p className="muted small" style={{ margin: 0 }}>No company is kept on the server for you yet.</p>;
  return (
    <>{err && <div className="banner error">{err}</div>}<ul className="company-list">
      {list.map((c) => (
        <li key={c.id}>
          <button className="example" onClick={() => openIt(c)} aria-label={`Open ${c.name}`}>
            <b>{c.name}{open?.id === c.id && open.live && <span className="faint"> · open</span>}</b>
            <span className="faint small">{c.role} · saved {when(c.updated_at)} by {c.updated_by} · {kb(c.size)}</span>
          </button>
        </li>
      ))}
    </ul></>
  );
}

/** "only Pune cold store, of Paneer" / "every place and product" */
const limitText = (places: string[], groups: string[]) => !places.length && !groups.length ? "every place and product"
  : `only ${places.length ? places.join(", ") : "every place"}${groups.length ? `, in the product group${groups.length > 1 ? "s" : ""} ${groups.join(", ")}` : ""}`;

/** "a, b" → ["a", "b"] */
const listOf = (text: string) => text.split(/[,;\n]/).map((x) => x.trim()).filter(Boolean);

/** A planner's rights limited to places and product groups (an owner edits them; empty: everything). */
function Limits({ m, id, owner, onSaved }: { m: Member; id: string; owner: boolean; onSaved: (l: Member[], msg: string) => void }) {
  const ds = useStore((s) => s.dataset);
  const [open, setOpen] = useState(false);
  const [places, setPlaces] = useState(m.places.join(", "));
  const [families, setFamilies] = useState(m.families.join(", "));
  const [err, setErr] = useState<string | null>(null);
  const placeName = (x: string) => ds?.locations?.find((l) => l.id === x)?.name ?? x;
  const text = limitText(m.places.map(placeName), m.families);
  if (m.role !== "planner") return null;
  if (!owner || !open) return <div className="faint small">Changes {text}{owner && <> · <button className="linkish" onClick={() => setOpen(true)}>limit</button></>}</div>;
  const sites = (ds?.locations ?? []).filter((l) => !["customer", "supplier"].includes(l.type)).map((l) => l.id);
  const groups = [...new Set((ds?.products ?? []).map((p) => p.family).filter(Boolean))];
  return <form className="stack" style={{ gap: 6, marginTop: 6 }} onSubmit={async (e) => {
    e.preventDefault();
    setErr(null);
    try {
      const l = await api.setMember(id, m.email, m.role, { places: listOf(places), families: listOf(families) });
      setOpen(false);
      onSaved(l, `${m.name || m.email} now changes ${limitText(listOf(places).map(placeName), listOf(families))}.`);
    } catch (x) { setErr(x instanceof Error ? x.message : String(x)); }
  }}>
    <label className="stack-field"><span>Only these places <span className="faint">(empty: every place)</span></span>
      <input className="input" value={places} onChange={(e) => setPlaces(e.target.value)} placeholder={sites.slice(0, 2).join(", ")} aria-label={`Places ${m.email} may change`} /></label>
    <label className="stack-field"><span>Only these product groups <span className="faint">(empty: every group)</span></span>
      <input className="input" value={families} onChange={(e) => setFamilies(e.target.value)} placeholder={groups.slice(0, 2).join(", ")} aria-label={`Product groups ${m.email} may change`} /></label>
    <span className="faint small">Places here: {sites.join(", ") || "—"}. Groups: {groups.join(", ") || "none set (a product's group is set in Master data → Products)"}.
      A limited planner also takes orders of the customers those places supply, and changes their suppliers' orders.</span>
    {err && <div className="banner error" style={{ margin: 0 }}>{err}</div>}
    <div className="row" style={{ gap: 6 }}><button className="btn sm">Save limits</button>
      <button type="button" className="btn sm ghost" onClick={() => setOpen(false)}>Cancel</button></div>
  </form>;
}

/** A link for a colleague to set a new password, to hand over (a server that sends no mail). */
function ResetLinkButton({ id, m }: { id: string; m: Member }) {
  const [link, setLink] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  if (!m.user_id || m.role === "owner") return null;
  return <div className="small" style={{ marginTop: 4 }}>
    {!link ? <button className="linkish" onClick={async () => {
      try { setLink((await api.memberResetLink(id, m.email)).link); } catch (x) { setErr(x instanceof Error ? x.message : String(x)); }
    }}>Link to set a new password</button>
      : <span>Give {m.name || m.email} this link (works once, for a day): <input className="input" readOnly value={link} aria-label="Link to set a new password"
          onFocus={(e) => e.target.select()} style={{ width: "100%", maxWidth: 420 }} /></span>}
    {err && <span className="banner error">{err}</span>}
  </div>;
}

/** Master-data changes wait for a second person's approval (an owner turns it on). */
function Approval({ id, owner }: { id: string; owner: boolean }) {
  const [on, setOn] = useState<boolean | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.companies().then((l) => setOn(!!l.find((c) => c.id === id)?.approval)).catch(() => setOn(null)); }, [id]);
  if (on === null) return null;
  return <div className="stack" style={{ gap: 4 }}>
    <label className="row small" style={{ gap: 8 }}>
      <input type="checkbox" checked={on} disabled={!owner} onChange={async (e) => {
        const want = e.target.checked;
        setErr(null);
        setOn(want);
        try { setOn((await api.setApproval(id, want)).approval ?? false); } catch (x) { setOn(!want); setErr(x instanceof Error ? x.message : String(x)); }
      }} />
      <span><b>Master data changes need a second person's approval</b>: places, products, planning policies, machines, ways to make
        and buy, routes, suppliers, prices, calendars and company settings wait until another planner or owner approves them
        (in <a href={href("history")}>History</a>). Orders, stock movements and forecasts are saved at once.</span>
    </label>
    {!owner && <span className="faint small">Only an owner changes this.</span>}
    {err && <div className="banner error" style={{ margin: 0 }}>{err}</div>}
  </div>;
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
                    <div className="faint small">{ROLE_TEXT[m.role]}</div>
                    <Limits key={`${m.email}-${m.places.join()}-${m.families.join()}`} m={m} id={id} owner={owner} onSaved={(l, done) => { setList(l); setMsg(done); }} />
                    {owner && m.email !== me?.email && <ResetLinkButton id={id} m={m} />}</td>
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

/** A link from a reset mail (or an owner): choose a new password, and be signed in. */
function ResetPassword({ token }: { token: string }) {
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  return <Panel title="Choose a new password">
    <form className="signin stack" onSubmit={async (e) => {
      e.preventDefault();
      setErr(null);
      try {
        const s = await api.resetPassword(token, pw);
        store.signedIn({ token: s.token, user: s.user });
        go("account");
      } catch (x) { setErr(x instanceof Error ? x.message : String(x)); }
    }}>
      <label className="stack-field"><span>New password <span className="faint">(at least 8 characters)</span></span>
        <input className="input" type="password" autoComplete="new-password" required minLength={8} value={pw} onChange={(e) => setPw(e.target.value)} /></label>
      {err && <div className="banner error" role="alert" style={{ margin: 0 }}>{err}</div>}
      <div><button className="btn accent">Set it and sign in</button></div>
      <p className="faint small" style={{ margin: 0 }}>Setting it signs this account out everywhere else.</p>
    </form>
  </Panel>;
}

/** Back from the company's identity provider: sign in with the token it brought. */
function SsoDone({ token }: { token: string }) {
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api.meWith(token).then((me) => { store.signedIn({ token, user: me.user }); go("account"); })
      .catch((x) => setErr(x instanceof Error ? x.message : String(x)));
  }, [token]);
  return err ? <div className="banner error">{err}</div> : <div className="faint">Signing in…</div>;
}

export function Account({ route = [] }: { route?: string[] }) {
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
      const before = store.captureWorking();
      const m = await api.createCompany(before.dataset, "moved from a browser");
      store.assertWorking(before, true);
      const doc = await api.company(m.id);
      store.assertWorking(before, true);
      store.openCompany(doc);
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
          a colleague's work unseen, and when two people changed the same record you choose whose to keep. Every save is kept,
          so the company can be put back to the state just before any of them.</>} />
      <div className="content">
        {route[1] === "reset" && route[2] ? <ResetPassword token={route[2]} />
          : route[1] === "sso" && route[2] ? <SsoDone token={route[2]} />
          : route[1] === "sso-failed" ? <div className="banner error" role="alert">Signing in with the company account did not work: {decodeURIComponent(route[2] ?? "")}</div>
          : null}
        {route[1] === "reset" || route[1] === "sso" ? null : !session ? (
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
                <div className="stack" style={{ gap: 14 }}>
                  <Members id={company.id} role={company.role} />
                  <Approval id={company.id} owner={company.role === "owner"} />
                </div>
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

