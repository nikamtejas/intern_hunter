import { FormEvent, useEffect, useState } from "react";
import { api, applyTheme, Me, savedTheme, setSignedOutHandler, Theme, User } from "./api";
import { Icon, Spinner, ToastProvider, useToast } from "./ui";
import HomePage from "./pages/HomePage";
import SearchPage from "./pages/SearchPage";
import StudioPage from "./pages/StudioPage";
import ProfilePage from "./pages/ProfilePage";
import ApplicationsPage from "./pages/ApplicationsPage";
import TrackerPage from "./pages/TrackerPage";
import SettingsPage from "./pages/SettingsPage";

export type Tab = "home" | "search" | "studio" | "profile" | "applications" | "tracker" | "settings";

// [tab, label, icon, what it's for — shown as a tooltip]
const NAV: [Tab, string, string, string][] = [
  ["home", "Today", "home", "What to do next, and new internships for you"],
  ["search", "Find internships", "search", "Search India and Europe; star a search to watch it"],
  ["applications", "My resumes", "file", "Your tailored resumes, ATS reports and interview prep"],
  ["tracker", "Tracker", "board", "Where every application stands — click one for its journey"],
  ["studio", "Resume Studio", "studio", "Get any resume reviewed and improved"],
  ["profile", "My profile", "user", "The facts every resume is built from"],
];

applyTheme(savedTheme());

export default function App() {
  return (
    <ToastProvider>
      <Gate />
    </ToastProvider>
  );
}

/** Nothing personal is shown until a profile is signed in. */
function Gate() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  useEffect(() => {
    setSignedOutHandler(() => setMe(null));
    api.me().then(setMe).catch(() => setMe(null));
  }, []);
  if (me === undefined) return <div className="signin-wrap"><Spinner /></div>;
  if (me === null) return <SignIn onIn={setMe} />;
  return <Shell me={me} setMe={setMe} />;
}

function SignIn({ onIn }: { onIn: (m: Me) => void }) {
  const toast = useToast();
  const [users, setUsers] = useState<User[] | null>(null);
  const [pick, setPick] = useState<User | null>(null);
  const [creating, setCreating] = useState(false);
  const [pw, setPw] = useState("");
  const [name, setName] = useState("");
  const [pw2, setPw2] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.users().then((u) => { setUsers(u); if (!u.length) setCreating(true); }); }, []);

  async function signIn(e: FormEvent) {
    e.preventDefault();
    if (!pick) return;
    setBusy(true);
    try { onIn(await api.login(pick.id, pw)); } catch (err: any) { toast(err.message, "err"); setPw(""); } finally { setBusy(false); }
  }
  async function create(e: FormEvent) {
    e.preventDefault();
    if (pw !== pw2) return toast("Passwords don't match", "err");
    setBusy(true);
    try { onIn(await api.createUser(name.trim(), pw)); toast("Profile created — add your resume on My profile"); }
    catch (err: any) { toast(err.message.includes("at least") || err.message.includes("422") ? "Use a password of at least 6 characters" : err.message, "err"); }
    finally { setBusy(false); }
  }

  return (
    <div className="signin-wrap">
      <div className="signin card">
        <div className="logo"><div className="logo-mark"><Icon name="spark" size={18} /></div><div><b>Intern Hunter</b><small>India · Europe</small></div></div>
        {creating ? (
          <form onSubmit={create}>
            <h2>Create your profile</h2>
            <p className="muted small">Your resumes, searches, tracker and inbox link stay in this profile, behind your password.</p>
            <label className="lbl">Your name<input autoFocus value={name} onChange={(e) => setName(e.target.value)} required /></label>
            <label className="lbl">Password (6+ characters)<input type="password" value={pw} onChange={(e) => setPw(e.target.value)} minLength={6} required /></label>
            <label className="lbl">Repeat password<input type="password" value={pw2} onChange={(e) => setPw2(e.target.value)} minLength={6} required /></label>
            <div className="row">
              <button className="btn primary" disabled={busy}>{busy ? <Spinner /> : "Create profile"}</button>
              {!!users?.length && <button type="button" className="btn ghost" onClick={() => setCreating(false)}>Back</button>}
            </div>
          </form>
        ) : pick ? (
          <form onSubmit={signIn}>
            <button type="button" className="btn ghost sm" onClick={() => { setPick(null); setPw(""); }}><Icon name="back" size={14} /> All profiles</button>
            <div className="who"><span className="avatar lg">{pick.name.slice(0, 1).toUpperCase()}</span><h2>{pick.name}</h2></div>
            {pick.locked ? (
              <label className="lbl">Password<input type="password" autoFocus value={pw} onChange={(e) => setPw(e.target.value)} required /></label>
            ) : <div className="banner warn small">This profile has no password yet. Open it, then set one from the account menu.</div>}
            <div className="row"><button className="btn primary" disabled={busy}>{busy ? <Spinner /> : pick.locked ? "Sign in" : "Open profile"}</button></div>
          </form>
        ) : (
          <>
            <h2>Who's hunting today?</h2>
            <div className="who-grid">
              {(users || []).map((u) => (
                <button key={u.id} className="who-card" onClick={() => setPick(u)}>
                  <span className="avatar lg">{u.name.slice(0, 1).toUpperCase()}</span>
                  <b>{u.name}</b>
                  <small>{u.locked ? "🔒 Password protected" : "Open — no password"}</small>
                </button>
              ))}
              <button className="who-card add" onClick={() => setCreating(true)}><span className="avatar lg add"><Icon name="plus" /></span><b>New profile</b><small>For another person</small></button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Shell({ me, setMe }: { me: Me; setMe: (m: Me | null) => void }) {
  const [tab, setTab] = useState<Tab>("home");
  const [groqOk, setGroqOk] = useState<boolean | null>(null);
  const [openApp, setOpenApp] = useState<number | null>(null);
  const [running, setRunning] = useState(0);
  const [badges, setBadges] = useState({ fresh: 0, followups: 0 });
  const [theme, setTheme] = useState<Theme>(savedTheme());

  useEffect(() => {
    api.settings().then((s) => setGroqOk(!!s.groq_configured)).catch(() => setGroqOk(false));
  }, [tab]);

  // live badges + "(3) Intern Hunter" in the browser tab, so a background tab still tells you something happened
  const refreshBadges = () => api.today().then((t) => setBadges({ fresh: t.new_total, followups: t.followups_due })).catch(() => {});
  useEffect(() => {
    refreshBadges();
    const i = setInterval(refreshBadges, 60_000);
    return () => clearInterval(i);
  }, [me.id]);
  useEffect(() => {
    const n = badges.fresh + badges.followups;
    document.title = n ? `(${n}) Intern Hunter` : "Intern Hunter";
  }, [badges]);

  useEffect(() => {
    const tick = () => api.apps().then((a) => setRunning(a.filter((x) => x.status === "queued" || x.status === "running").length)).catch(() => {});
    tick();
    const t = setInterval(tick, 3000);
    return () => clearInterval(t);
  }, [me.id]);

  const go = (t: Tab, appId: number | null = null) => {
    setTab(t);
    setOpenApp(appId);
    window.scrollTo(0, 0);
  };

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="logo">
          <div className="logo-mark"><Icon name="spark" size={18} /></div>
          <div>
            <b>Intern Hunter</b>
            <small>India · Europe</small>
          </div>
        </div>
        <AccountMenu me={me} setMe={setMe} />
        <nav>
          {NAV.map(([k, label, icon, hint]) => (
            <button key={k} className={tab === k ? "active" : ""} onClick={() => go(k)} title={hint}>
              <Icon name={icon} />
              <span>{label}</span>
              {k === "applications" && running > 0 && <em className="pulse" title="Resumes being written">{running}</em>}
              {k === "home" && badges.fresh > 0 && <em className="new" title="New internships">{badges.fresh}</em>}
              {k === "tracker" && badges.followups > 0 && <em className="warn" title="Follow-ups due">{badges.followups}</em>}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="theme-toggle" role="group" aria-label="Theme">
            {([["light", "sun"], ["system", "settings"], ["dark", "moon"]] as const).map(([k, ic]) => (
              <button key={k} className={theme === k ? "on" : ""} title={k === "system" ? "Follow system" : `${k} mode`}
                      onClick={() => { setTheme(k); applyTheme(k); }}><Icon name={ic} size={15} /></button>
            ))}
          </div>
          <button className={tab === "settings" ? "active" : ""} onClick={() => go("settings")}>
            <Icon name="settings" />
            <span>Settings</span>
          </button>
          <div className={`status ${groqOk ? "on" : "off"}`} onClick={() => go("settings")}>
            <i />
            {groqOk ? "Groq AI connected" : "Groq key missing"}
          </div>
        </div>
      </aside>
      {/* key: everything below re-mounts (and re-fetches) when the profile changes */}
      <main className="content" key={me.id}>
        {!me.locked && <div className="lock-nudge"><Icon name="key" size={15} /> Anyone on this computer can open “{me.name}”. Set a password from the account menu (top left) to keep it private.</div>}
        {tab === "home" && <HomePage go={go} groqOk={!!groqOk} name={me.name} onSeen={refreshBadges} />}
        {tab === "search" && <SearchPage onGenerated={() => go("applications")} openApp={(id) => go("applications", id)} />}
        {tab === "studio" && <StudioPage openApp={(id) => go("applications", id)} />}
        {tab === "profile" && <ProfilePage />}
        {tab === "applications" && <ApplicationsPage openId={openApp} setOpenId={setOpenApp} goProfile={() => go("profile")} goSearch={() => go("search")} />}
        {tab === "tracker" && <TrackerPage openApp={(id) => go("applications", id)} goSearch={() => go("search")} />}
        {tab === "settings" && <SettingsPage onSaved={(ok) => setGroqOk(ok)} />}
      </main>
    </div>
  );
}

function AccountMenu({ me, setMe }: { me: Me; setMe: (m: Me | null) => void }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);

  async function lock() {
    const current = me.locked ? prompt("Current password:") ?? "" : "";
    if (me.locked && !current) return;
    const pw = prompt(me.locked ? "New password (6+ characters):" : "Choose a password (6+ characters):")?.trim();
    if (!pw) return;
    if (pw.length < 6) return toast("Use at least 6 characters", "err");
    try { setMe(await api.setPassword(pw, current)); toast("Password set — this profile is now private"); setOpen(false); }
    catch (e: any) { toast(e.message, "err"); }
  }
  async function rename() {
    const name = prompt("Rename profile:", me.name)?.trim();
    if (name) setMe(await api.renameMe(name));
  }
  async function remove() {
    const pw = me.locked ? prompt(`Type your password to delete “${me.name}” with all its resumes and tracker. This can't be undone.`) : "";
    if (me.locked && !pw) return;
    if (!me.locked && !confirm(`Delete “${me.name}” with all its resumes and tracker? This can't be undone.`)) return;
    try { await api.deleteMe(me.id, pw || ""); setMe(null); } catch (e: any) { toast(e.message, "err"); }
  }

  return (
    <div className="profile-switch">
      <button className="ps-current" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="avatar">{me.name.slice(0, 1).toUpperCase()}</span>
        <span className="ps-name"><small>{me.locked ? "🔒 Signed in" : "Open profile"}</small>{me.name}</span>
        <Icon name="chevron" size={16} />
      </button>
      {open && (
        <div className="ps-menu">
          <button className="ps-pick" onClick={lock}><Icon name="key" size={15} /> {me.locked ? "Change password" : "Set a password"}</button>
          <button className="ps-pick" onClick={rename}><Icon name="paste" size={15} /> Rename</button>
          <button className="ps-pick" onClick={async () => { await api.logout(); setMe(null); }}><Icon name="user" size={15} /> Switch profile / sign out</button>
          <button className="ps-pick danger" onClick={remove}><Icon name="trash" size={15} /> Delete this profile</button>
        </div>
      )}
    </div>
  );
}
