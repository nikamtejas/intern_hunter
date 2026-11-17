import { useEffect, useState } from "react";
import { api, Dashboard, dateShort, EmailConfig, Track, TRACK } from "../api";
import { Timeline } from "./ApplicationsPage";
import Journey from "./Journey";
import { Empty, Icon, PageHeader, SOURCE_LABEL, Spinner, TrackSelect, useToast } from "../ui";

const COLUMNS: Track[] = ["not_applied", "applied", "assessment", "interview", "offer", "rejected"];

export default function TrackerPage({ openApp, goSearch }: { openApp: (id: number) => void; goSearch: () => void }) {
  const toast = useToast();
  const [d, setD] = useState<Dashboard | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [journey, setJourney] = useState<number | null>(null);
  const load = () => api.dashboard().then(setD).catch((e) => toast(e.message, "err"));
  useEffect(() => { load(); }, []);

  async function move(id: number, t: Track) {
    await api.setTrack(id, { track: t });
    toast(`Moved to ${TRACK[t].label}`);
    load();
  }

  async function sync() {
    setSyncing(true);
    try {
      const r = await api.syncEmail();
      const n = r.updated?.length || 0;
      toast(n ? `Email checked — ${n} application${n > 1 ? "s" : ""} updated` : `Email checked — ${r.job_related || 0} job emails, no status changes`);
      load();
    } catch (e: any) {
      toast(e.message, "err");
    } finally {
      setSyncing(false);
    }
  }

  if (!d) return <div className="page"><Spinner /></div>;
  const c = d.counts;
  return (
    <div className="page wide">
      <PageHeader title="Application tracker" subtitle="Where every application stands. Change a status from its card, or let your inbox do it.">
        {d.email.address && d.email.has_password &&
          <button className="btn" onClick={sync} disabled={syncing}>{syncing ? <><Spinner /> Checking email</> : <><Icon name="mail" /> Check email now</>}</button>}
      </PageHeader>

      <GoalCard d={d} onChange={load} />
      {d.followups.length > 0 && (
        <section className="card followups">
          <h3><Icon name="mail" /> {d.followups.length} application{d.followups.length > 1 ? "s" : ""} waiting 7+ days — time to follow up</h3>
          <div className="chips">
            {d.followups.map((f) => (
              <button key={f.id} className="chip pick" onClick={() => setJourney(f.id)}>
                {f.job_company || f.job_title} · {f.days}d
              </button>
            ))}
          </div>
        </section>
      )}

      <div className="kpis">
        <Kpi label="Applied" value={d.applied} sub={`${d.applied_this_week} this week`} />
        <Kpi label="Response rate" value={`${d.response_rate}%`} sub="any reply: test, interview, offer or rejection" />
        <Kpi label="Interviews" value={c.interview + c.offer} sub={`${d.interview_rate}% of applications`} tone="accent" />
        <Kpi label="Offers" value={c.offer} tone="ok" />
        <Kpi label="Rejected" value={c.rejected} tone="err" />
        <Kpi label="Avg ATS score" value={d.avg_score ?? "—"} sub={`${d.total} resumes made`} />
      </div>

      {!d.total ? (
        <Empty icon="board" title="Nothing to track yet">
          Generate a resume for a job, apply, then mark it as Applied here.<br /><br />
          <button className="btn primary" onClick={goSearch}><Icon name="search" /> Find internships</button>
        </Empty>
      ) : (
        <div className="board">
          {COLUMNS.map((col) => {
            const items = d.apps.filter((a) => a.track === col || (col === "rejected" && a.track === "withdrawn"));
            return (
              <section key={col} className={`col t-${TRACK[col].tone}`}>
                <header><i />{col === "rejected" ? "Closed" : TRACK[col].label}<em>{items.length}</em></header>
                {items.map((a) => (
                  <article key={a.id} className="bcard" onClick={() => setJourney(a.id)} title="Open the journey">
                    <b>{a.job_title}</b>
                    <span className="muted small">{[a.job_company, a.job_location].filter(Boolean).join(" · ") || "—"}</span>
                    <div className="bcard-foot">
                      <TrackSelect value={a.track} onChange={(t) => move(a.id, t)} />
                      {a.score != null && <span className="badge">{Math.round(a.score)}</span>}
                    </div>
                    <small className="muted">
                      {a.applied_at ? `Applied ${dateShort(a.applied_at)}` : `Resume ${dateShort(a.created_at)}`}
                      {a.job_source ? ` · ${SOURCE_LABEL[a.job_source] || a.job_source}` : ""}
                    </small>
                  </article>
                ))}
                {!items.length && <p className="col-empty">—</p>}
              </section>
            );
          })}
        </div>
      )}

      <div className="ats-grid">
        <EmailCard cfg={d.email} onSaved={load} />
        <section className="card">
          <h3>Recent activity</h3>
          {!d.events.length && <p className="muted small">Status changes and notes appear here.</p>}
          <Timeline events={d.events.slice(0, 12)} withJob onOpen={(id) => setJourney(id)} />
        </section>
      </div>
      {journey && <Journey id={journey} onClose={() => { setJourney(null); load(); }} openFull={(id) => { setJourney(null); openApp(id); }} />}
    </div>
  );
}

function Kpi({ label, value, sub, tone = "" }: { label: string; value: string | number; sub?: string; tone?: string }) {
  return (
    <div className={`kpi ${tone}`}>
      <span>{label}</span>
      <b>{value}</b>
      {sub && <small>{sub}</small>}
    </div>
  );
}

function EmailCard({ cfg, onSaved }: { cfg: EmailConfig; onSaved: () => void }) {
  const toast = useToast();
  const connected = !!(cfg.address && cfg.has_password);
  const [editing, setEditing] = useState(!connected);
  const [f, setF] = useState({ address: cfg.address, app_password: "", host: cfg.host || "imap.gmail.com", auto: cfg.auto });
  const [busy, setBusy] = useState(false);
  const last = cfg.last_result;

  async function save() {
    setBusy(true);
    try {
      await api.saveEmail(f);
      toast("Email connected — checking your inbox…");
      setEditing(false);
      try { await api.syncEmail(); } catch (e: any) { toast(e.message, "err"); }
      onSaved();
    } catch (e: any) {
      toast(e.message, "err");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card email-card">
      <h3><Icon name="mail" /> Auto-update from email</h3>
      {connected && !editing ? (
        <>
          <p className="small">Connected: <b>{cfg.address}</b> {cfg.auto ? "· checks every 30 min while the app runs" : "· manual checks only"}</p>
          {cfg.last_sync > 0 && <p className="muted small">Last checked {new Date(cfg.last_sync * 1000).toLocaleString()}
            {last && !last.error && <> — {last.checked} emails scanned, {last.job_related} about jobs, {last.updated?.length || 0} status change(s)</>}</p>}
          {last?.error && <div className="banner err">{last.error}</div>}
          {!!last?.updated?.length && (
            <ul className="clean small">{last.updated.map((u, i) => (
              <li key={i}><Icon name="arrow" size={13} />{u.company}: {TRACK[u.from]?.label} → <b>{TRACK[u.to]?.label}</b> <span className="muted">(“{u.subject}”)</span></li>
            ))}</ul>
          )}
          <div className="row tight">
            <button className="btn sm" onClick={() => setEditing(true)}>Change</button>
            <button className="btn ghost sm danger" onClick={async () => { await api.disconnectEmail(); onSaved(); toast("Email disconnected"); }}>Disconnect</button>
          </div>
        </>
      ) : (
        <>
          <p className="small muted">
            Reads your inbox (read-only — nothing is marked read, moved or sent) for replies from companies you applied to:
            confirmations, tests, interview invites, offers and rejections. Statuses only ever move forward, and every change shows
            the email it came from so you can undo it.
          </p>
          <div className="grid2">
            <label className="lbl">Email address<input value={f.address} placeholder="you@gmail.com" onChange={(e) => setF({ ...f, address: e.target.value })} /></label>
            <label className="lbl">App password<input type="password" value={f.app_password} placeholder={cfg.has_password ? "•••••••• (saved)" : "16-character app password"}
                                                     onChange={(e) => setF({ ...f, app_password: e.target.value })} /></label>
            <label className="lbl">IMAP server<input value={f.host} onChange={(e) => setF({ ...f, host: e.target.value })} /></label>
            <label className="switch inline"><input type="checkbox" checked={f.auto} onChange={(e) => setF({ ...f, auto: e.target.checked })} /><i />Check every 30 minutes</label>
          </div>
          <details className="howto">
            <summary>How to get a Gmail app password (2 minutes)</summary>
            <ol className="small">
              <li>Turn on 2-Step Verification: myaccount.google.com → Security.</li>
              <li>Open <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noreferrer">myaccount.google.com/apppasswords</a>, name it “Intern Hunter”, click Create.</li>
              <li>Paste the 16-character password here. Your normal Gmail password won't work, and this one can be revoked any time.</li>
              <li>Outlook / other providers: use their IMAP server (e.g. outlook.office365.com) and an app password if they offer one.</li>
            </ol>
            <p className="small muted">The password stays in the local database on this computer. Job-related emails are sent to Groq to classify them when a Groq key is set.</p>
          </details>
          <div className="row tight">
            <button className="btn primary sm" disabled={busy || !f.address || (!f.app_password && !cfg.has_password)} onClick={save}>
              {busy ? <><Spinner /> Connecting</> : "Connect & check inbox"}
            </button>
            {connected && <button className="btn ghost sm" onClick={() => setEditing(false)}>Cancel</button>}
          </div>
        </>
      )}
    </section>
  );
}

function GoalCard({ d, onChange }: { d: Dashboard; onChange: () => void }) {
  const g = d.goal;
  const pct = Math.min(100, Math.round((100 * g.this_week) / g.weekly));
  const max = Math.max(g.weekly, ...g.history.map((h) => h.count), 1);
  return (
    <section className="card goal">
      <div className="goal-main">
        <div className="goal-ring" style={{ ["--p" as any]: pct }}>
          <b>{g.this_week}<small>/{g.weekly}</small></b>
        </div>
        <div>
          <h3>{pct >= 100 ? "Weekly goal smashed 🎯" : `${g.weekly - g.this_week} more to hit this week's goal`}</h3>
          <p className="muted small">
            {g.streak > 0 ? <>🔥 <b>{g.streak}-week streak</b> — keep it alive.</> : "Hit your goal this week to start a streak."}
            {" "}Goal: <select value={g.weekly} onChange={(e) => api.setGoal(Number(e.target.value)).then(onChange)}>
              {[2, 3, 5, 7, 10, 15, 20].map((n) => <option key={n} value={n}>{n} / week</option>)}
            </select>
          </p>
        </div>
      </div>
      <div className="spark" aria-label="Applications per week, last 8 weeks">
        {g.history.map((h, i) => (
          <div key={h.week} className={`bar-w ${h.count >= g.weekly ? "hit" : ""} ${i === g.history.length - 1 ? "now" : ""}`} title={`${h.week}: ${h.count}`}>
            <i style={{ height: `${Math.max(4, (h.count / max) * 100)}%` }} />
          </div>
        ))}
      </div>
    </section>
  );
}
