import { useEffect, useState } from "react";
import { api, celebrate, dateShort, Meta, Mission, timeAgo, Today, TRACK } from "../api";
import type { Tab } from "../App";
import { Icon, SOURCE_LABEL, Spinner, useToast, WorkModeBadge } from "../ui";
import Journey from "./Journey";

const MISSION_ICON: Record<string, string> = { prep: "🎤", followup: "📨", send: "🚀", profile: "🧩", goal: "🎯", watch: "⭐" };

function greeting(): string {
  const h = new Date().getHours();
  return h < 5 ? "Burning the midnight oil" : h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

/** "Today": everything that needs you, in order, plus what's new — the page to keep open. */
export default function HomePage({ go, groqOk, name, onSeen }:
  { go: (t: Tab, id?: number | null) => void; groqOk: boolean; name: string; onSeen: () => void }) {
  const toast = useToast();
  const [t, setT] = useState<Today | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [journey, setJourney] = useState<number | null>(null);
  const [making, setMaking] = useState<string | null>(null);
  const load = () => api.today().then(setT);
  useEffect(() => {
    load();
    api.meta().then(setMeta);
    const i = setInterval(load, 60_000);
    return () => clearInterval(i);
  }, []);

  // one celebration per week when the goal is reached
  useEffect(() => {
    if (!t || t.goal.this_week < t.goal.weekly) return;
    const key = `ih_goal_${t.goal.history[t.goal.history.length - 1]?.week}`;
    try { if (!localStorage.getItem(key)) { localStorage.setItem(key, "1"); celebrate(); } } catch {}
  }, [t?.goal.this_week]);

  if (!t) return <div className="page"><Spinner /></div>;
  const first = name.split(" ")[0];
  const g = t.goal;
  const pct = Math.min(100, Math.round((100 * g.this_week) / g.weekly));
  const flag = (k: string) => meta?.countries.find((c) => c.key === k)?.flag || "";
  const pipeline = (["applied", "assessment", "interview", "offer"] as const).map((k) => [k, t.counts[k] || 0] as const);

  function act(m: Mission) {
    if (m.action === "journey" && m.target) setJourney(m.target);
    else if (m.action === "app" && m.target) go("applications", m.target);
    else go(m.action === "profile" ? "profile" : "search");
  }
  async function makeResume(jobId: string) {
    setMaking(jobId);
    try {
      const r = await api.createApps([jobId], "en", true);
      toast("Tailoring your resume — it'll appear in My resumes");
      go("applications", r.created[0] ?? null);
    } catch (e: any) { toast(e.message, "err"); } finally { setMaking(null); }
  }

  return (
    <div className="page today">
      <section className="today-hero">
        <div>
          <span className="eyebrow">{new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}</span>
          <h1>{greeting()}, {first} 👋</h1>
          <p>{t.missions.length ? <>You have <b>{t.missions.length} thing{t.missions.length > 1 ? "s" : ""}</b> to move forward today
            {t.new_total ? <> and <b>{t.new_total} new internship{t.new_total > 1 ? "s" : ""}</b> waiting</> : null}.</>
            : "All caught up — nice. Find a few more roles to keep the pipeline full."}</p>
        </div>
        <div className="hero-goal" title="Applications this week">
          <div className="goal-ring big" style={{ ["--p" as any]: pct }}><b>{g.this_week}<small>/{g.weekly}</small></b></div>
          <div>
            <b className="streak">{g.streak ? <>🔥 {g.streak}-week streak</> : "Start a streak"}</b>
            <small>{pct >= 100 ? "Goal reached this week 🎯" : `${g.weekly - g.this_week} to go this week`}</small>
          </div>
        </div>
      </section>

      {!groqOk && <div className="banner warn">Connect Groq AI in <button className="link" onClick={() => go("settings")}>Settings</button> so the app can write resumes.</div>}

      <div className="today-grid">
        <section className="card missions">
          <h3><Icon name="target" /> Your next moves</h3>
          {!t.missions.length && <p className="muted">Nothing urgent. 🎉</p>}
          <ol>
            {t.missions.map((m, i) => (
              <li key={i}>
                <button className={`mission ${m.urgent ? "urgent" : ""}`} onClick={() => act(m)}>
                  <span className="m-ico">{MISSION_ICON[m.kind] || "•"}</span>
                  <span className="m-txt"><b>{m.title}</b><small>{m.sub}</small></span>
                  <Icon name="arrow" size={16} />
                </button>
              </li>
            ))}
          </ol>
        </section>

        <section className="card pipeline-card">
          <h3><Icon name="board" /> Your pipeline</h3>
          <div className="pipe">
            {pipeline.map(([k, n]) => (
              <button key={k} className={`pipe-step t-${TRACK[k].tone}`} onClick={() => go("tracker")}>
                <b>{n}</b><small>{TRACK[k].label}</small>
              </button>
            ))}
          </div>
          <div className="mini-stats">
            <span><b>{t.resumes}</b> resumes</span>
            <span><b>{t.ready_not_sent}</b> ready to send</span>
            <span><b>{t.profile_score}%</b> profile</span>
          </div>
          {t.events.length > 0 && <>
            <h4>Latest</h4>
            <ul className="latest">
              {t.events.slice(0, 4).map((e) => (
                <li key={e.id} onClick={() => setJourney(e.app_id)}>
                  <i className={`dot t-${e.new ? TRACK[e.new]?.tone : "idle"}`} />
                  <span>{e.kind === "status" ? <>{e.job_company || e.job_title} → <b>{e.new ? TRACK[e.new]?.label : ""}</b></>
                                             : e.kind === "note" ? <>Note on {e.job_company || e.job_title}</> : <>Prep for {e.job_company}</>}
                    {e.source === "email" && " 📧"}</span>
                  <small>{dateShort(e.created_at)}</small>
                </li>
              ))}
            </ul>
          </>}
        </section>
      </div>

      <section className="card fresh">
        <div className="fresh-head">
          <h3><Icon name="star" /> New for you {t.new_total > 0 && <em className="count">{t.new_total}</em>}</h3>
          <div className="row tight">
            {t.watched.map((w) => (
              <span key={w.id} className="chip watched" title={w.last_run ? `Checked ${timeAgo(new Date(w.last_run * 1000).toISOString())}` : ""}>
                ⭐ {flag(w.params.country)} {w.params.keywords || "all internships"}
              </span>
            ))}
            {t.new_total > 0 && <button className="btn ghost sm" onClick={async () => { await api.todaySeen(); onSeen(); load(); }}>Mark all seen</button>}
          </div>
        </div>
        {!t.watched.length ? (
          <div className="fresh-empty">
            <p><b>Let the jobs come to you.</b> Run a search, then tap ⭐ <b>Watch</b> on it — the app re-checks it every 3 hours
              while it's open and drops new internships here, sorted by how well they fit your profile.</p>
            <button className="btn primary" onClick={() => go("search")}><Icon name="search" /> Find internships</button>
          </div>
        ) : !t.new_jobs.length ? (
          <p className="muted">No new postings since your last look — the next check runs automatically.</p>
        ) : (
          <div className="fresh-list">
            {t.new_jobs.map((j) => (
              <article key={j.id} className="fresh-job">
                <div className="fj-top">
                  {j.extra?.fit && <span className={`fit-pill ${j.extra.fit.pct >= 70 ? "hi" : j.extra.fit.pct >= 40 ? "mid" : "lo"}`}>{j.extra.fit.pct}%</span>}
                  <span className={`badge src-${j.source}`}>{SOURCE_LABEL[j.source] || j.source}</span>
                  <WorkModeBadge mode={j.extra?.work_mode} />
                </div>
                <b>{j.title}</b>
                <small className="muted">{flag(j.country)} {[j.company, j.location].filter(Boolean).join(" · ")}</small>
                <small className="muted">{timeAgo(j.posted_at)}</small>
                <div className="row tight">
                  <button className="btn primary sm" disabled={making === j.id} onClick={() => makeResume(j.id)}>
                    {making === j.id ? <Spinner /> : <><Icon name="spark" size={14} /> Tailor resume</>}
                  </button>
                  {j.url && <a className="btn ghost sm" href={j.url} target="_blank" rel="noreferrer"><Icon name="external" size={14} /></a>}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      {journey && <Journey id={journey} onClose={() => { setJourney(null); load(); }} openFull={(id) => { setJourney(null); go("applications", id); }} />}
    </div>
  );
}
