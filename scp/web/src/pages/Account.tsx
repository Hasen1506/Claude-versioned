// Sign-in and the companies kept on the server (Phase I, Q14): sign in or make an account, open a company, keep the
// company in this browser on the server, and (for an owner) say who may see and change it.
import { useEffect, useRef, useState } from "react";
import { api, ApiError, SSO_START } from "../api/client";
import type { AuthConfig, CompanyMeta, DeletionPlan, Member, TwoStepKey, TwoStepState } from "../api/types";
import { Badge, Empty, Panel, StageHeader } from "../components/ui";
import { when } from "../components/SaveStatus";
import { useLatest } from "../lib/latest";
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
  // read again on signing in or out: "first account" stops being true once one is made (AUTH-01)
  const token = useStore((s) => s.session?.token);
  useEffect(() => { api.authConfig().then(setCfg).catch(() => setCfg(null)); }, [token]);
  return cfg;
}

/** What a new password must be (roadmap D): the server says the length; the rest is checked when it is set. */
export const policyHint = (config: AuthConfig | null) =>
  `at least ${config?.password_min ?? 12} characters, not a common or breached one, not your address`;

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
  const [ticket, setTicket] = useState<string | null>(null);   // the password was right: the app's code next (1.3)
  const [code, setCode] = useState("");
  const wasFirst = useRef(config?.first_account);
  useEffect(() => {
    if (config?.first_account) setMode("up");
    else if (wasFirst.current && config) setMode((m) => m === "up" ? "in" : m);   // the first account exists now
    wasFirst.current = config?.first_account;
  }, [config?.first_account]);
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
      if (ticket) {
        const s = await api.signInSecond(ticket, code);
        setTicket(null);
        setCode("");
        store.signedIn({ user: s.user });
        onDone?.();
        return;
      }
      const s = mode === "in" ? await api.signIn(email, password) : await api.signUp(email, name, password);
      setPassword("");
      if (s.second_step) { setTicket(s.second_step); return; }
      store.signedIn({ user: s.user });
      onDone?.();
    } catch (x) {
      setErr(x instanceof Error ? x.message : String(x));
      if (ticket && x instanceof ApiError && x.status === 401 && !x.body.two_step) { setTicket(null); setCode(""); }   // the ticket ran out
    } finally {
      setBusy(false);
    }
  };
  if (ticket) return (
    <form className="signin stack" onSubmit={submit} aria-label="Second step">
      <p className="small" style={{ margin: 0 }}>The password is right. Enter the six-digit code your authenticator app shows for
        <b> {email}</b> now.</p>
      <label className="stack-field"><span>Code from the app</span>
        <input className="input" inputMode="numeric" autoComplete="one-time-code" required autoFocus value={code}
          onChange={(e) => setCode(e.target.value)} placeholder="123 456" aria-label="Code from the app" /></label>
      <span className="faint small">Lost the phone? Enter one of your recovery codes instead (each works once).</span>
      {err && <div className="banner error" role="alert" style={{ margin: 0 }}>{err}</div>}
      <div className="row wrap" style={{ gap: 10 }}>
        <button className="btn accent" disabled={busy}>{busy ? "…" : "Sign in"}</button>
        <button type="button" className="btn ghost sm" onClick={() => { setTicket(null); setCode(""); setErr(null); }}>Start again</button>
      </div>
    </form>
  );
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
      {mode !== "forgot" && <label className="stack-field"><span>Password{mode === "up" && <span className="faint"> ({policyHint(config)})</span>}</span>
        <input className="input" type="password" autoComplete={mode === "in" ? "current-password" : "new-password"} required minLength={mode === "up" ? (config?.password_min ?? 12) : undefined}
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
      store.openCompany(doc, before);
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
            {c.needs_two_step && <span className="small"><Badge sev="warning">needs two-step sign-in</Badge> turn it on below to open it</span>}
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
    {link === null ? <button className="linkish" onClick={async () => {
      try {
        const r = await api.memberResetLink(id, m.email);
        setLink(r.mailed ? "" : r.link);
      } catch (x) { setErr(x instanceof Error ? x.message : String(x)); }
    }}>Link to set a new password</button>
      : link === "" ? <span>A link to set a new password went to {m.email} (it works once, for a day).</span>
      : <span>Give {m.name || m.email} this link (works once, for a day): <input className="input" readOnly value={link} aria-label="Link to set a new password"
          onFocus={(e) => e.target.select()} style={{ width: "100%", maxWidth: 420 }} /></span>}
    {err && <span className="banner error">{err}</span>}
  </div>;
}

/** Master-data changes wait for a second person's approval (an owner turns it on). */
function Approval({ id, owner }: { id: string; owner: boolean }) {
  // a first read that answers after the owner already changed the setting must not put the old value back
  const { value: on, show: setOn } = useLatest(() => api.companies().then((l) => !!l.find((c) => c.id === id)?.approval), [id]);
  const [err, setErr] = useState<string | null>(null);
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

/** Every member signs in with two steps (an owner requires it, having turned it on for themselves). */
function TwoStepRequired({ id, owner }: { id: string; owner: boolean }) {
  const { value: on, show: setOn } = useLatest(() => api.companies().then((l) => !!l.find((c) => c.id === id)?.two_step), [id]);
  const [err, setErr] = useState<string | null>(null);
  if (on === null) return null;
  return <div className="stack" style={{ gap: 4 }}>
    <label className="row small" style={{ gap: 8 }}>
      <input type="checkbox" checked={on} disabled={!owner} onChange={async (e) => {
        const want = e.target.checked;
        setErr(null);
        setOn(want);
        try { setOn((await api.setTwoStep(id, want)).two_step ?? false); } catch (x) { setOn(!want); setErr(msgOf(x)); }
      }} />
      <span><b>Every member signs in with two steps</b>: a password and a code from an authenticator app. A member who
        has not turned it on cannot open the company until they do (integration keys and single sign-on are not affected).</span>
    </label>
    {!owner && <span className="faint small">Only an owner changes this.</span>}
    {err && <div className="banner error" style={{ margin: 0 }}>{err}</div>}
  </div>;
}

function Members({ id, role }: { id: string; role: string }) {
  const me = useStore((s) => s.session?.user);
  const [email, setEmail] = useState("");
  const [newRole, setNewRole] = useState("planner");
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  // the first read is shown only if no change (an invitation, a new role, a removal, new limits) answered since it was
  // asked: the change's answer is the newer list (scp run 37731060982: the invited row vanished)
  const { value: list, show, error: readErr } = useLatest(() => api.members(id), [id]);
  const owner = role === "owner";
  const [invite, setInvite] = useState<{ email: string; link: string } | null>(null);
  const act = async (f: () => Promise<Member[]>, done: string) => {
    setErr(null);
    setMsg(null);
    setInvite(null);
    try {
      const l = await f();
      show(l);
      setMsg(done);
      const made = l.find((m) => m.invite_link);
      if (made?.invite_link) setInvite({ email: made.email, link: made.invite_link });
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
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
                    {!m.user_id && <div><Badge sev="info">invited</Badge> <span className="faint small">joins when they open the invitation and sign in with this e-mail</span></div>}</td>
                  <td>{owner && m.email !== me?.email ? (
                    <select className="select" aria-label={`Role of ${m.email}`} value={m.role}
                      onChange={(e) => act(() => api.setMember(id, m.email, e.target.value), `${m.name || m.email} is now ${e.target.value === "owner" ? "an" : "a"} ${e.target.value}.`)}>
                      <option value="owner">owner</option><option value="planner">planner</option><option value="viewer">viewer</option>
                    </select>) : <>{m.role}{m.email === me?.email && <span className="faint"> (you)</span>}</>}
                    <div className="faint small">{ROLE_TEXT[m.role]}</div>
                    <Limits key={`${m.email}-${m.places.join()}-${m.families.join()}`} m={m} id={id} owner={owner} onSaved={(l, done) => { show(l); setMsg(done); }} />
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
        void act(() => api.setMember(id, who, newRole), `${who} is invited as ${newRole}: they join when they accept the invitation, signed in with that e-mail.`).then(() => setEmail(""));
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
      {invite && <div className="small">Send {invite.email} this invitation (it works for 14 days, only for that address; a server that
        sends mail has mailed it too): <input className="input" readOnly value={invite.link} aria-label="Invitation link"
          onFocus={(e) => e.target.select()} style={{ width: "100%", maxWidth: 480 }} /></div>}
      {(err ?? readErr) && <div className="banner error" style={{ margin: 0 }}>{err ?? readErr}</div>}
    </div>
  );
}

/** An invitation's link: accept it, signed in with the invited address (CV-C01: nobody joins a company unasked). */
function AcceptInvite({ token }: { token: string }) {
  const session = useStore((s) => s.session);
  const [state, setState] = useState<"ready" | "busy" | "done">("ready");
  const [err, setErr] = useState<string | null>(null);
  const [name, setName] = useState("");
  if (!session) return <div className="banner info" role="status">You are invited to a company. Sign in, or make an account, with
    the address the invitation was sent to; this page then lets you accept it.</div>;
  if (state === "done") return <div className="banner ok" role="status">You joined {name}. Open it from your companies below.</div>;
  return <div className="banner info row wrap" style={{ gap: 10 }} role="status">
    <span>You are invited to a company, as {session.user.email}.</span>
    <button className="btn accent" disabled={state === "busy"} onClick={async () => {
      setState("busy"); setErr(null);
      try { const m = await api.acceptInvite({ token }); setName(m.name); setState("done"); }
      catch (x) { setErr(x instanceof Error ? x.message : String(x)); setState("ready"); }
    }}>Accept the invitation</button>
    {err && <span className="banner error">{err}</span>}
  </div>;
}

/** A link from the mail that confirms the account's address. */
function VerifyEmail({ token }: { token: string }) {
  const [msg, setMsg] = useState<[string, boolean] | null>(null);
  useEffect(() => {
    api.verifyEmail(token).then((u) => setMsg([`${u.email} is confirmed as yours.`, true]))
      .catch((x) => setMsg([x instanceof Error ? x.message : String(x), false]));
  }, [token]);
  return msg ? <div className={`banner ${msg[1] ? "ok" : "error"}`} role="status">{msg[0]}</div> : <div className="faint">Confirming…</div>;
}

/** The account's address (confirmed or not), the invitations waiting for it, and linking the company's sign-on. */
function Identity({ sso }: { sso: string | null | undefined }) {
  const [me, setMe] = useState<Awaited<ReturnType<typeof api.me>> | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const load = () => { api.me().then(setMe).catch(() => setMe(null)); };
  useEffect(load, []);
  if (!me) return null;
  return <div className="stack small" style={{ gap: 6 }}>
    <div className="row wrap" style={{ gap: 8 }}>
      {me.user.verified ? <Badge sev="ok">address confirmed</Badge> : <>
        <Badge sev="warning">address not confirmed</Badge>
        <button className="btn sm" onClick={async () => {
          try { const r = await api.requestEmailCheck(); setMsg(r.mail ? `A link is on its way to ${me.user.email}.` : "This server sends no mail: an invitation's link joins you to a company instead."); }
          catch (x) { setMsg(x instanceof Error ? x.message : String(x)); }
        }}>Confirm my address</button></>}
      {sso && <button className="btn sm ghost" onClick={async () => {
        try { window.location.href = (await api.ssoLink()).url; } catch (x) { setMsg(x instanceof Error ? x.message : String(x)); }
      }}>Link sign-in with {sso}</button>}
    </div>
    {me.invites.map((i) => <div key={i.company} className="row wrap" style={{ gap: 8 }}>
      <span>{i.invited_by} invited you to <b>{i.name}</b> as {i.role}.</span>
      <button className="btn sm accent" onClick={async () => {
        try { await api.acceptInvite({ company: i.company }); setMsg(`You joined ${i.name}.`); load(); }
        catch (x) { setMsg(x instanceof Error ? x.message : String(x)); }
      }}>Accept</button></div>)}
    {msg && <span className="faint">{msg}</span>}
  </div>;
}

const msgOf = (x: unknown) => x instanceof Error ? x.message : String(x);

/** The six digits, or a recovery code, when two-step sign-in is on. */
function CodeField({ value, set, label = "Code from your app" }: { value: string; set: (v: string) => void; label?: string }) {
  return <input className="input" inputMode="numeric" autoComplete="one-time-code" placeholder={label} aria-label={label}
    required value={value} onChange={(e) => set(e.target.value)} style={{ maxWidth: 170 }} />;
}

/** Recovery codes, shown once: to print or keep in a password manager. */
function Codes({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  const [copied, setCopied] = useState(false);
  return <div className="banner warning stack recovery-box" role="status" style={{ gap: 8, margin: 0 }}>
    <b>Keep these recovery codes somewhere safe, away from your phone.</b>
    <span className="small">Each signs you in once instead of the app's code, if the phone is lost. They are shown only now.</span>
    <ol className="recovery-codes" aria-label="Recovery codes">{codes.map((c) => <li key={c}><code>{c}</code></li>)}</ol>
    <div className="row wrap" style={{ gap: 8 }}>
      <button type="button" className="btn sm" onClick={async () => {
        try { await navigator.clipboard.writeText(codes.join("\n")); setCopied(true); } catch { setCopied(false); }
      }}>{copied ? "Copied" : "Copy them"}</button>
      <button type="button" className="btn sm accent" onClick={onDone}>I have kept them</button>
    </div>
  </div>;
}

/** Turning two-step sign-in on (password → key for the app → a code back → recovery codes), off, and new codes. */
function TwoStep({ state, reload }: { state: TwoStepState; reload: () => void }) {
  const [pw, setPw] = useState("");
  const [code, setCode] = useState("");
  const [key, setKey] = useState<TwoStepKey | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [act, setAct] = useState<"off" | "codes" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const run = async (f: () => Promise<void>) => { setErr(null); try { await f(); } catch (x) { setErr(msgOf(x)); } };
  if (!state.password) return <p className="small muted" style={{ margin: 0 }}>You sign in with your company's single sign-on:
    its own second step applies.</p>;
  if (codes) return <Codes codes={codes} onDone={() => { setCodes(null); reload(); }} />;
  return <div className="stack" style={{ gap: 8 }}>
    {state.on ? <>
      <div className="row wrap" style={{ gap: 8 }}><Badge sev="ok">two-step sign-in on</Badge>
        <span className="small muted">{state.recovery_left} recovery code{state.recovery_left === 1 ? "" : "s"} left</span>
        {state.recovery_left <= 3 && <span className="small">· make new ones before they run out</span>}</div>
      {!act ? <div className="row wrap" style={{ gap: 8 }}>
        <button className="btn sm" onClick={() => setAct("codes")}>New recovery codes</button>
        <button className="btn sm ghost" onClick={() => setAct("off")}>Turn it off</button></div>
        : <form className="row wrap inline-form" style={{ gap: 8 }} onSubmit={(e) => {
          e.preventDefault();
          void run(async () => {
            if (act === "codes") setCodes((await api.recoveryCodes(pw, code)).codes);
            else { await api.twoStepDisable(pw, code); reload(); }
            setAct(null); setPw(""); setCode("");
          });
        }}>
          <input className="input" type="password" autoComplete="current-password" placeholder="Your password" aria-label="Your password" required value={pw} onChange={(e) => setPw(e.target.value)} />
          <CodeField value={code} set={setCode} />
          <button className="btn sm">{act === "codes" ? "Make new codes" : "Turn two-step sign-in off"}</button>
          <button type="button" className="btn sm ghost" onClick={() => setAct(null)}>Cancel</button>
        </form>}
    </> : !key ? <>
      <p className="small muted" style={{ margin: 0 }}>Signing in then takes your password and a six-digit code from an
        authenticator app on your phone (Google or Microsoft Authenticator, 1Password, Authy …), so a stolen password alone
        does not open your companies.</p>
      <form className="row wrap inline-form" style={{ gap: 8 }} onSubmit={(e) => {
        e.preventDefault();
        void run(async () => { setKey(await api.twoStepBegin(pw)); setPw(""); });
      }}>
        <input className="input" type="password" autoComplete="current-password" placeholder="Your password" aria-label="Your password" required value={pw} onChange={(e) => setPw(e.target.value)} />
        <button className="btn sm accent">Turn on two-step sign-in</button>
      </form>
    </> : <form className="stack" style={{ gap: 8 }} onSubmit={(e) => {
      e.preventDefault();
      void run(async () => { setCodes((await api.twoStepEnable(code)).codes); setKey(null); setCode(""); });
    }}>
      <ol className="small" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.7 }}>
        <li>In the authenticator app, add an account and type this key (or, on this phone, <a href={key.uri}>open it in the app</a>):
          <div><code className="two-step-key" aria-label="Key for the app">{key.grouped}</code></div></li>
        <li>Enter the six-digit code the app now shows for it:</li>
      </ol>
      <div className="row wrap" style={{ gap: 8 }}>
        <CodeField value={code} set={setCode} />
        <button className="btn sm accent">Turn it on</button>
        <button type="button" className="btn sm ghost" onClick={() => setKey(null)}>Cancel</button>
      </div>
      <span className="faint small">Turning it on signs you out on other browsers and devices.</span>
    </form>}
    {err && <div className="banner error" role="alert" style={{ margin: 0 }}>{err}</div>}
  </div>;
}

function Password({ twoStep }: { twoStep: boolean }) {
  const min = useAuthConfig()?.password_min ?? 12;
  const [old, setOld] = useState("");
  const [next, setNext] = useState("");
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState<[string, boolean] | null>(null);
  return (
    <form className="row wrap inline-form" style={{ gap: 8 }} aria-label="Change password" onSubmit={async (e) => {
      e.preventDefault();
      try { await api.changePassword(old, next, code); setMsg(["Password changed; other sessions are signed out.", true]); setOld(""); setNext(""); setCode(""); }
      catch (x) { setMsg([msgOf(x), false]); }
    }}>
      <input className="input" type="password" autoComplete="current-password" placeholder="Current password" aria-label="Current password" required value={old} onChange={(e) => setOld(e.target.value)} />
      <input className="input" type="password" autoComplete="new-password" placeholder={`New password (${min}+ characters)`} aria-label="New password" required minLength={min} value={next} onChange={(e) => setNext(e.target.value)} />
      {twoStep && <CodeField value={code} set={setCode} />}
      <button className="btn">Change password</button>
      {msg && <span className={`small ${msg[1] ? "" : "banner error"}`}>{msg[0]}</span>}
    </form>
  );
}

/** Another sign-in address: the password (and code) again; the new address is confirmed by a link sent there. */
function EmailChange({ twoStep, onChanged }: { twoStep: boolean; onChanged: (email: string) => void }) {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState<[string, boolean] | null>(null);
  if (!open) return <div className="small">{msg && <span className={msg[1] ? "" : "banner error"}>{msg[0]} </span>}
    <button className="linkish" onClick={() => { setOpen(true); setMsg(null); }}>Change the sign-in address</button></div>;
  return <form className="row wrap inline-form" style={{ gap: 8 }} aria-label="Change the sign-in address" onSubmit={async (e) => {
    e.preventDefault();
    try {
      const u = await api.changeEmail(pw, email, code);
      onChanged(u.email);
      setOpen(false); setPw(""); setCode(""); setEmail("");
      setMsg([`You now sign in as ${u.email}. Confirm it with the link sent there (when this server sends mail); other sessions are signed out.`, true]);
    } catch (x) { setMsg([msgOf(x), false]); }
  }}>
    <input className="input" type="email" autoComplete="email" placeholder="New address" aria-label="New address" required value={email} onChange={(e) => setEmail(e.target.value)} />
    <input className="input" type="password" autoComplete="current-password" placeholder="Your password" aria-label="Your password" required value={pw} onChange={(e) => setPw(e.target.value)} />
    {twoStep && <CodeField value={code} set={setCode} />}
    <button className="btn sm">Change it</button>
    <button type="button" className="btn sm ghost" onClick={() => setOpen(false)}>Cancel</button>
    {msg && !msg[1] && <span className="small banner error">{msg[0]}</span>}
  </form>;
}

/** The password and the code again, or (an account that signs in only through single sign-on) its address typed. */
function Again({ state, pw, setPw, code, setCode, email }: { state: TwoStepState; pw: string; setPw: (v: string) => void;
  code: string; setCode: (v: string) => void; email: string }) {
  return state.password ? <>
    <input className="input" type="password" autoComplete="current-password" placeholder="Your password" aria-label="Your password" required value={pw} onChange={(e) => setPw(e.target.value)} />
    {state.on && <CodeField value={code} set={setCode} />}
  </> : <input className="input" placeholder={email} aria-label="Type your address to confirm" required value={pw} onChange={(e) => setPw(e.target.value)} />;
}

/** Download everything the account holds; delete the account, after saying what happens to each company. */
function YourData({ state }: { state: TwoStepState }) {
  const email = useStore((s) => s.session?.user.email) ?? "";
  const [mode, setMode] = useState<"export" | "delete" | null>(null);
  const [pw, setPw] = useState("");
  const [code, setCode] = useState("");
  const [plan, setPlan] = useState<DeletionPlan | null>(null);
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [sure, setSure] = useState("");
  const [msg, setMsg] = useState<[string, boolean] | null>(null);
  const again = () => state.password ? { password: pw, code } : { confirm: pw };
  const reset = () => { setMode(null); setPw(""); setCode(""); setSure(""); };
  const open = async (m: "export" | "delete") => {
    setMsg(null); setMode(m);
    if (m === "delete") {
      try {
        const p = await api.deletionPlan();
        setPlan(p);
        setChoices(Object.fromEntries(p.alone.map((c) => [c.id, c.members[0]?.email ?? "delete"])));
      } catch (x) { setMsg([msgOf(x), false]); }
    }
  };
  const download = async () => {
    const data = await api.exportAccount(again());
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 1)], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `scp-account-${String(data.exported_at ?? "").slice(0, 10)}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
    setMsg(["The file has everything this account holds: each company's data as last saved, its members, history and plan versions, and what you did there.", true]);
    reset();
  };
  const remove = async () => {
    const out = await api.deleteAccount({ ...again(), choices });
    reset();
    await store.signOut();
    window.alert(`Your account is deleted. ${out.done.length ? out.done.join("; ") + "." : ""}`);
  };
  return <div className="stack" style={{ gap: 8 }}>
    {!mode && <div className="row wrap" style={{ gap: 8 }}>
      <button className="btn sm" onClick={() => open("export")}>Download everything</button>
      <button className="btn sm ghost" onClick={() => open("delete")}>Delete my account…</button></div>}
    {mode === "export" && <form className="row wrap inline-form" style={{ gap: 8 }} aria-label="Download everything" onSubmit={(e) => {
      e.preventDefault(); download().catch((x) => setMsg([msgOf(x), false]));
    }}>
      <Again state={state} pw={pw} setPw={setPw} code={code} setCode={setCode} email={email} />
      <button className="btn sm accent">Download</button>
      <button type="button" className="btn sm ghost" onClick={reset}>Cancel</button>
    </form>}
    {mode === "delete" && plan && <form className="stack delete-account" style={{ gap: 10 }} aria-label="Delete my account" onSubmit={(e) => {
      e.preventDefault(); remove().catch((x) => setMsg([msgOf(x), false]));
    }}>
      <p className="small" style={{ margin: 0 }}><b>Deleting your account</b> signs you out everywhere and erases your address, name,
        password and second step. The companies' histories keep what you did, under "Deleted account". This cannot be undone:
        download everything first if you may want it.</p>
      {plan.alone.length > 0 && <div className="stack" style={{ gap: 6 }}>
        <span className="small">You are the only owner of these. Say what happens to each:</span>
        {plan.alone.map((c) => <label key={c.id} className="row wrap small" style={{ gap: 8 }}>
          <b style={{ minWidth: 140 }}>{c.name}</b>
          <select className="select" aria-label={`What happens to ${c.name}`} value={choices[c.id] ?? "delete"}
            onChange={(e) => setChoices({ ...choices, [c.id]: e.target.value })}>
            {c.members.map((m) => <option key={m.email} value={m.email}>hand it to {m.name || m.email} ({m.role}), who becomes its owner</option>)}
            <option value="delete">delete it, for everyone in it</option>
          </select></label>)}
      </div>}
      {(plan.shared.length > 0 || plan.member.length > 0) && <span className="small">You leave {[...plan.shared, ...plan.member].map((c) => c.name).join(", ")}: they go on without you.</span>}
      <div className="row wrap" style={{ gap: 8 }}>
        <Again state={state} pw={pw} setPw={setPw} code={code} setCode={setCode} email={email} />
        <input className="input" aria-label="Type DELETE to confirm" placeholder="Type DELETE" required value={sure} onChange={(e) => setSure(e.target.value)} />
        <button className="btn sm danger" disabled={sure.trim().toUpperCase() !== "DELETE"}>Delete my account</button>
        <button type="button" className="btn sm ghost" onClick={reset}>Cancel</button>
      </div>
    </form>}
    {msg && <div className={`banner ${msg[1] ? "ok" : "error"}`} role={msg[1] ? "status" : "alert"} style={{ margin: 0 }}>{msg[0]}</div>}
  </div>;
}

/** How the account signs in: two steps, the password, the address. */
function Security() {
  const [state, setState] = useState<TwoStepState | null>(null);
  const load = () => { api.twoStep().then(setState).catch(() => setState(null)); };
  useEffect(load, []);
  if (!state) return null;
  return <div className="stack" style={{ gap: 12, marginTop: 12 }}>
    <h3 className="q" style={{ margin: 0 }}>Two-step sign-in</h3>
    <TwoStep state={state} reload={load} />
    {state.password && <><h3 className="q" style={{ margin: 0 }}>Password and address</h3>
      <Password twoStep={state.on} />
      <EmailChange twoStep={state.on} onChanged={(email) => { const u = store.get().session?.user; if (u) store.signedIn({ user: { ...u, email, verified: false } }); }} /></>}
    <h3 className="q" style={{ margin: 0 }}>Your data</h3>
    <YourData state={state} />
  </div>;
}

/** A link from a reset mail (or an owner): choose a new password, and be signed in. */
function ResetPassword({ token }: { token: string }) {
  const config = useAuthConfig();
  const [pw, setPw] = useState("");
  const [code, setCode] = useState("");
  const [askCode, setAskCode] = useState(false);     // the account signs in with two steps: the app's code too (1.3)
  const [err, setErr] = useState<string | null>(null);
  return <Panel title="Choose a new password">
    <form className="signin stack" onSubmit={async (e) => {
      e.preventDefault();
      setErr(null);
      try {
        const s = await api.resetPassword(token, pw, code);
        store.signedIn({ user: s.user });
        go("account");
      } catch (x) {
        if (x instanceof ApiError && x.body.two_step && !askCode) { setAskCode(true); return; }
        setErr(msgOf(x));
      }
    }}>
      <label className="stack-field"><span>New password <span className="faint">({policyHint(config)})</span></span>
        <input className="input" type="password" autoComplete="new-password" required minLength={config?.password_min ?? 12} value={pw} onChange={(e) => setPw(e.target.value)} /></label>
      {askCode && <label className="stack-field"><span>This account signs in with two steps: the code your app shows now (or a recovery code)</span>
        <CodeField value={code} set={setCode} /></label>}
      {err && <div className="banner error" role="alert" style={{ margin: 0 }}>{err}</div>}
      <div><button className="btn accent">Set it and sign in</button></div>
      <p className="faint small" style={{ margin: 0 }}>Setting it signs this account out everywhere else.</p>
    </form>
  </Panel>;
}

/** Back from the company's identity provider, which set the session cookie (roadmap D: no token in the address). */
function SsoDone() {
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api.me().then((me) => { store.signedIn({ user: me.user }); go("account"); })
      .catch((x) => setErr(x instanceof Error ? x.message : String(x)));
  }, []);
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
      store.openCompany(doc, before);
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
        howLabel="How saving works" how={<>Each save is a revision. A save made on top of an older revision than the latest is refused, so nobody overwrites
          a colleague's work unseen, and when two people changed the same record you choose whose to keep. Every save is kept,
          so the company can be put back to the state just before any of them.</>} />
      <div className="content">
        {route[1] === "reset" && route[2] ? <ResetPassword token={route[2]} />
          : route[1] === "sso" ? <SsoDone />
          : route[1] === "sso-failed" ? <div className="banner error" role="alert">Signing in with the company account did not work: {decodeURIComponent(route[2] ?? "")}</div>
          : route[1] === "invite" && route[2] ? <AcceptInvite token={route[2]} />
          : route[1] === "verify" && route[2] ? <VerifyEmail token={route[2]} />
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
              <Identity sso={config?.sso} />
              <Security />
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
                  <TwoStepRequired id={company.id} owner={company.role === "owner"} />
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

