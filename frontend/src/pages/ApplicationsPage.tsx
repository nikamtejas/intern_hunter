import { useEffect, useState } from "react";
import { api, Application, AppEvent, CheckItem, dateShort, Meta, Profile, Track, TRACK } from "../api";
import { MissingPanel, ProfileEditor } from "./ProfilePage";
import { FollowUpView, PrepView } from "./Journey";
import { Empty, Icon, PageHeader, ScoreRing, SOURCE_LABEL, Spinner, TrackSelect, useToast } from "../ui";

const LABELS: Record<string, [string, number]> = {
  hard_skills: ["Hard-skill keywords", 40], keywords: ["Tools & other keywords", 15], soft_skills: ["Soft skills", 5],
  title_match: ["Job-title match", 10], sections: ["Sections & contact", 10], formatting: ["ATS-safe format & length", 10],
  impact: ["Action verbs & numbers", 10],
};

export default function ApplicationsPage({ openId, setOpenId, goProfile, goSearch }:
  { openId: number | null; setOpenId: (n: number | null) => void; goProfile: () => void; goSearch: () => void }) {
  const toast = useToast();
  const [apps, setApps] = useState<Application[] | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  useEffect(() => { api.meta().then(setMeta); }, []);
  const place = (k?: string) => { const c = meta?.countries.find((x) => x.key === k); return c ? `${c.flag} ${c.name}` : ""; };
  const load = () => api.apps().then(setApps);
  const pending = (apps || []).some((a) => a.status === "queued" || a.status === "running");

  useEffect(() => { load(); }, [openId]);
  useEffect(() => {
    if (!pending) return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [pending]);

  if (openId) return <AppDetail id={openId} back={() => setOpenId(null)} goProfile={goProfile} />;
  if (!apps) return <div className="page"><Spinner /></div>;

  return (
    <div className="page">
      <PageHeader title="My resumes" subtitle="Every tailored resume and cover letter you've generated. Set the status once you apply — the Tracker picks it up." />
      {!apps.length && (
        <Empty icon="file" title="No resumes yet">
          Find internships, tick the ones you like and hit Generate — or use Resume Studio.<br /><br />
          <button className="btn primary" onClick={goSearch}><Icon name="search" /> Find internships</button>
        </Empty>
      )}
      <div className="app-list">
        {apps.map((a) => {
          const ready = a.status === "done";
          const working = a.status === "queued" || a.status === "running";
          return (
            <article key={a.id} className={`app ${ready ? "ready" : ""}`} onClick={() => ready && setOpenId(a.id)}>
              {ready ? <ScoreRing score={a.score || 0} target={a.target || 98} size={54} /> : <div className="app-state">{working ? <Spinner /> : <Icon name="x" />}</div>}
              <div className="app-main">
                <h4>{a.job_title}{ready && (a.ready ? <span className="badge ok ready-b"><Icon name="check" size={12} /> Ready to send</span>
                                                     : a.ready === false ? <span className="badge warn ready-b">Needs fixes</span> : null)}</h4>
                <div className="job-meta">
                  {a.job_company && <span><Icon name="building" size={14} />{a.job_company}</span>}
                  <span>{place(a.job_country)} · {a.options?.language === "de" ? "Deutsch" : "English"}</span>
                  {a.job_source && <span className={`badge src-${a.job_source}`}>{SOURCE_LABEL[a.job_source] || a.job_source}</span>}
                </div>
                {working && <div className="app-progress"><i />{a.error || "Queued"}…</div>}
                {a.status === "error" && <div className="app-error">{a.error}</div>}
              </div>
              <div className="app-actions" onClick={(e) => e.stopPropagation()}>
                {ready && <>
                  <TrackSelect value={a.track} onChange={(t) => api.setTrack(a.id, { track: t }).then(load)} />
                  <a className="btn sm" href={`/api/applications/${a.id}/resume.pdf`} download><Icon name="download" size={15} /> PDF</a>
                  <a className="btn sm ghost" href={`/api/applications/${a.id}/resume.docx`} download>DOCX</a>
                </>}
                {a.status === "error" && <button className="btn sm" onClick={() => api.regenerate(a.id).then(load)}><Icon name="refresh" size={15} /> Retry</button>}
                <button className="btn sm ghost icon-only danger" title="Delete"
                        onClick={() => api.deleteApp(a.id).then(() => { load(); toast("Deleted"); })}><Icon name="trash" size={15} /></button>
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}

function AppDetail({ id, back, goProfile }: { id: number; back: () => void; goProfile: () => void }) {
  const toast = useToast();
  const [a, setA] = useState<Application | null>(null);
  const [edit, setEdit] = useState<Profile | null>(null);
  const [tab, setTab] = useState<"ats" | "status" | "prep" | "resume" | "cover" | "jd">("ats");
  const [prepBusy, setPrepBusy] = useState(false);
  const [gapSel, setGapSel] = useState<Set<string>>(new Set());
  const [check, setCheck] = useState<{ score: number; items: CheckItem[] } | null>(null);

  useEffect(() => { if (a?.job?.country) api.checkProfile(a.job.country).then(setCheck).catch(() => {}); }, [a?.job?.country]);

  async function load() {
    const x = await api.app(id);
    setA(x);
    if (x.status === "queued" || x.status === "running") setTimeout(load, 1500);
  }
  useEffect(() => { load(); }, [id]);

  if (!a) return <div className="page"><Spinner /></div>;
  if (a.status !== "done" || !a.ats || !a.resume)
    return (
      <div className="page">
        <button className="btn ghost" onClick={back}><Icon name="back" /> All resumes</button>
        <div className="working card">
          {a.status === "error" ? <Icon name="x" size={28} /> : <Spinner />}
          <h3>{a.status === "error" ? "Something went wrong" : a.error || "Queued"}</h3>
          <p className="muted">{a.status === "error" ? a.error : "Analysing the job, writing, scoring and humanizing — usually 20–60 seconds."}</p>
          {a.status === "error" && <button className="btn primary" onClick={() => api.regenerate(id).then(load)}>Try again</button>}
        </div>
      </div>
    );

  const r = a.ats.ats;
  const target = a.ats.target;
  const style = a.ats.style;
  const studio = a.job?.source === "studio";

  async function addGapsAndRegen(category: "technical" | "learning") {
    await api.addSkills([...gapSel], category);
    await api.regenerate(id);
    setGapSel(new Set());
    toast(category === "learning" ? "Added as “Currently learning” — regenerating" : "Added to your skills — regenerating");
    load();
  }
  const pot = a.ats.potential;

  return (
    <div className="page">
      <button className="btn ghost" onClick={back}><Icon name="back" /> All resumes</button>
      <section className="card detail-head">
        <ScoreRing score={r.score} target={target} size={120} />
        <div className="grow">
          <span className={`badge src-${a.job?.source}`}>{SOURCE_LABEL[a.job?.source || ""] || a.job?.source}</span>
          <h2>{a.job?.title}</h2>
          <p className="muted">{[a.job?.company, a.job?.location].filter(Boolean).join(" · ")}
            {a.job?.url && <> · <a href={a.job.url} target="_blank" rel="noreferrer">posting ↗</a></>}</p>
          <div className="row tight">
            <TrackSelect value={a.track} onChange={async (t) => { setA(await api.setTrack(id, { track: t })); toast(`Marked as ${TRACK[t].label}`); }} />
            {a.applied_at && <span className="badge">Applied {dateShort(a.applied_at)}</span>}
            {a.ats.reached_target ? <span className="badge ok"><Icon name="check" size={13} /> Target {target} reached</span>
                                  : <span className="badge warn">Below target {target}</span>}
            <span className="badge">{a.ats.history.length} AI pass{a.ats.history.length > 1 ? "es" : ""}</span>
            <span className="badge">{r.word_count} words</span>
            {style && <span className={`badge ${style.count ? "warn" : "ok"}`}>{style.count ? `${style.count} style notes` : "Human-sounding ✓"}</span>}
          </div>
          {!studio && a.ats.description_chars < 300 && <p className="hint">⚠ The job description was short — paste the full posting (Find internships → Paste a job) for a sharper match.</p>}
        </div>
        <div className="dl">
          <a className="btn primary" href={`/api/applications/${id}/resume.pdf`} download><Icon name="download" /> Resume PDF</a>
          <a className="btn" href={`/api/applications/${id}/resume.docx`} download><Icon name="download" /> Resume DOCX</a>
          <a className="btn ghost sm" href={`/api/applications/${id}/resume.pdf`} target="_blank" rel="noreferrer"><Icon name="external" size={15} /> Preview one-pager</a>
          {a.cover_letter && <div className="row tight">
            <a className="btn sm" href={`/api/applications/${id}/cover.pdf`}>Letter PDF</a>
            <a className="btn sm" href={`/api/applications/${id}/cover.docx`}>Letter DOCX</a>
          </div>}
          <button className="btn ghost sm" onClick={() => api.regenerate(id).then(() => { toast("Regenerating…"); load(); })}><Icon name="refresh" size={15} /> Regenerate</button>
        </div>
      </section>

      <div className="tabs">
        {([["ats", "ATS report"], ["status", "Status & notes"], ["prep", "Interview prep"], ["resume", "Edit resume"], ["cover", "Cover letter"], ["jd", studio ? "Target role" : "Job description"]] as const).map(([k, l]) => (
          <button key={k} className={tab === k ? "active" : ""} onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>

      {tab === "ats" && a.ats.checks && (
        <section className={`card checks ${a.ats.checks.ready ? "is-ready" : ""}`}>
          <div className="checks-head">
            <h3>{a.ats.checks.ready ? <><Icon name="check" /> Ready to send</> : "Shortlist rules"}</h3>
            <span className="muted small">{a.ats.checks.passed}/{a.ats.checks.total} rules met · core rules decide “ready”</span>
          </div>
          <ul className="rules">
            {a.ats.checks.rules.map((rl) => (
              <li key={rl.id} className={rl.ok ? "ok" : rl.core ? "fail" : "warn"}>
                <Icon name={rl.ok ? "check" : rl.core ? "x" : "warn"} size={15} />
                <span><b>{rl.label}</b>{!rl.core && <em> optional</em>}<small>{rl.detail}</small></span>
              </li>
            ))}
          </ul>
          {!!a.ats.auto_learning?.length && (
            <div className="banner info small">
              <b>Added to “Currently learning” for this job:</b> {a.ats.auto_learning.join(", ")}. They lift the ATS match and are
              never claimed as experience. Start a short course on each before interviews — recruiters may ask what you've done so far.
            </div>
          )}
        </section>
      )}

      {tab === "ats" && (
        <div className="ats-grid">
          <section className="card">
            <h3>Score breakdown</h3>
            <div className="bars">
              {Object.entries(LABELS).map(([k, [label, max]]) => {
                const v = r.breakdown[k] ?? 0;
                return (
                  <div key={k} className="bar">
                    <span>{label}</span>
                    <div><i className={v / max >= 0.95 ? "full" : ""} style={{ width: `${(v / max) * 100}%` }} /></div>
                    <b>{v}<small>/{max}</small></b>
                  </div>
                );
              })}
            </div>
            {r.tips.length > 0 && <>
              <h4>How to push it higher</h4>
              <ul className="clean">{r.tips.map((t, i) => <li key={i}><Icon name="arrow" size={14} />{t}</li>)}</ul>
            </>}
            {pot && r.score < 90 && (
              <div className="banner info">
                <b>Path to 90+:</b> now {Math.round(r.score)} → about <b>{Math.round(pot.with_missing_skills)}</b> once the missing skills are on the
                resume (as skills you have, or “Currently learning”) → about <b>{Math.round(pot.with_skills_and_numbers)}</b> with real numbers
                in your bullets (users, %, time saved, dataset size — add them on My profile).
                {pot.with_skills_and_numbers < 90 && <> Even then this job stays below 90 — it asks for a lot your profile doesn't cover, so prioritise closer matches.</>}
              </div>
            )}
            {a.ats.note && <div className="banner warn">{a.ats.note}</div>}
            {!!a.ats.removed_claims?.length && (
              <div className="banner warn">
                <b>Kept honest:</b> the AI tried to claim things your profile doesn't mention, so these were removed.
                If you genuinely have any of them, add them to your profile and regenerate.
                <ul className="clean small">{a.ats.removed_claims.slice(0, 8).map((t, i) => <li key={i}>{t}</li>)}</ul>
              </div>
            )}
            {!!a.ats.trimmed?.length && (
              <div className="banner info">
                <b>Cut to fit one page:</b> the least job-relevant items were removed ({a.ats.trimmed.length}).
                <ul className="clean small">{a.ats.trimmed.map((t, i) => <li key={i}>{t}</li>)}</ul>
              </div>
            )}
            <p className="hint">This is the app's ATS model. Each company's system scores differently — treat it as a strong guide, not a guarantee.</p>
          </section>
          <section className="card">
            <h3>Keywords</h3>
            <h4 className="okc">Matched</h4>
            <div className="chips">{[...r.matched.hard_skills, ...r.matched.keywords, ...r.matched.soft_skills].map((k) => <span key={k} className="chip ok">{k}</span>)}</div>
            <h4 className="errc">Missing</h4>
            <div className="chips">{[...r.missing.hard_skills, ...r.missing.keywords, ...r.missing.soft_skills].map((k) => <span key={k} className="chip miss">{k}</span>)}
              {!r.missing.hard_skills.length && !r.missing.keywords.length && !r.missing.soft_skills.length && <span className="muted">None 🎉</span>}</div>
            {a.ats.gaps.length > 0 && (
              <div className="gapbox">
                <b>Not in your profile</b>
                <p className="muted small">The AI never claims skills you don't have. Tick some, then choose: <b>I have these</b> (added as skills)
                  or <b>I'm learning these</b> (a separate “Currently learning” row — ATS scanners count it, and it stays honest if you've started).</p>
                <div className="chips">
                  {a.ats.gaps.map((g) => (
                    <button key={g} className={`chip pick ${gapSel.has(g) ? "on" : ""}`}
                            onClick={() => { const s = new Set(gapSel); s.has(g) ? s.delete(g) : s.add(g); setGapSel(s); }}>
                      {gapSel.has(g) ? <Icon name="check" size={13} /> : <Icon name="plus" size={13} />}{g}
                    </button>
                  ))}
                </div>
                <div className="row tight">
                  <button className="btn primary sm" disabled={!gapSel.size} onClick={() => addGapsAndRegen("technical")}>I have these ({gapSel.size})</button>
                  <button className="btn sm" disabled={!gapSel.size} onClick={() => addGapsAndRegen("learning")}>I'm learning these</button>
                  <button className="btn ghost sm" onClick={() => setGapSel(new Set(a.ats!.gaps))}>Select all</button>
                  <button className="btn ghost sm" onClick={goProfile}>Edit profile</button>
                </div>
              </div>
            )}
            {style && style.count > 0 && <>
              <h4>Writing-quality notes</h4>
              <ul className="clean small">
                {style.cliches.length > 0 && <li>Generic words left: {style.cliches.join(", ")}</li>}
                {style.repeated_verbs.length > 0 && <li>Repeated openers: {style.repeated_verbs.join(", ")}</li>}
                {style.short_bullets.length > 0 && <li>{style.short_bullets.length} short bullet(s) could use more detail</li>}
                {style.thin_entries.length > 0 && <li>Thin entries: {style.thin_entries.join(", ")}</li>}
              </ul>
            </>}
          </section>
        </div>
      )}

      {tab === "ats" && check && check.items.length > 0 && <MissingPanel check={check} title="Missing from your profile" />}

      {tab === "status" && <StatusPanel a={a} onChange={setA} />}

      {tab === "prep" && (
        <section className="card">
          <PrepView a={a} busy={prepBusy} make={async () => {
            setPrepBusy(true);
            try { await api.prep(id); await load(); toast("Interview prep ready"); } catch (e: any) { toast(e.message, "err"); } finally { setPrepBusy(false); }
          }} />
        </section>
      )}

      {tab === "resume" && (
        <section className="card">
          <p className="hint">Edit the tailored resume directly. Saving fits it to one page and re-scores it instantly — downloads use the saved version.</p>
          <ProfileEditor value={edit || a.resume} onChange={setEdit} />
          {edit && (
            <div className="dock">
              <span>Unsaved edits</span>
              <button className="btn ghost" onClick={() => setEdit(null)}>Discard</button>
              <button className="btn primary" onClick={async () => { setA(await api.editResume(id, edit)); setEdit(null); toast("Saved & re-scored"); setTab("ats"); }}>Save & re-score</button>
            </div>
          )}
        </section>
      )}

      {tab === "cover" && (
        <section className="card letter">
          {a.cover_letter ? <>
            <b>{a.cover_letter.subject}</b>
            <p>{a.cover_letter.greeting}</p>
            {a.cover_letter.paragraphs.map((p, i) => <p key={i}>{p}</p>)}
            <p>{a.cover_letter.closing}<br />{a.resume.name}</p>
          </> : <p className="muted">No cover letter was requested for this one. Turn on “Cover letter” when generating.</p>}
        </section>
      )}

      {tab === "jd" && <section className="card"><div className="jd">{a.job?.description}</div></section>}
    </div>
  );
}

function StatusPanel({ a, onChange }: { a: Application; onChange: (a: Application) => void }) {
  const toast = useToast();
  const [notes, setNotes] = useState(a.notes || "");
  const [fuBusy, setFuBusy] = useState(false);
  const events = a.events || [];
  return (
    <div className="ats-grid">
      <section className="card">
        <h3>Status</h3>
        <div className="stage-row">
          {(["applied", "assessment", "interview", "offer", "rejected", "withdrawn"] as Track[]).map((t) => (
            <button key={t} className={`stage t-${TRACK[t].tone} ${a.track === t ? "on" : ""}`}
                    onClick={async () => { onChange(await api.setTrack(a.id, { track: t })); toast(`Marked as ${TRACK[t].label}`); }}>
              {TRACK[t].label}
            </button>
          ))}
        </div>
        <label className="lbl">Notes (contact person, interview date, referral…)
          <textarea rows={5} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </label>
        <div className="row tight">
          <button className="btn primary sm" disabled={notes === (a.notes || "")}
                  onClick={async () => { onChange(await api.setTrack(a.id, { notes })); toast("Notes saved"); }}>Save notes</button>
        </div>
      </section>
      <section className="card">
        {a.track === "applied" && <div className="fu-box"><FollowUpView a={a} busy={fuBusy} make={async () => {
          setFuBusy(true);
          try { const f = await api.followup(a.id); onChange({ ...a, followup: f }); } catch (e: any) { toast(e.message, "err"); } finally { setFuBusy(false); }
        }} /></div>}
        <h3>Timeline</h3>
        {!events.length && <p className="muted small">No updates yet. Changes you make — and ones found in your email — show up here.</p>}
        <Timeline events={events} />
      </section>
    </div>
  );
}

export function Timeline({ events, withJob = false, onOpen }: { events: AppEvent[]; withJob?: boolean; onOpen?: (id: number) => void }) {
  return (
    <ul className="timeline">
      {events.map((e) => (
        <li key={e.id} className={e.source === "email" ? "from-email" : ""}>
          <i className={`dot t-${e.new ? TRACK[e.new]?.tone : "idle"}`} />
          <div>
            <div className="tl-head">
              {e.kind === "status"
                ? <span>{e.old ? `${TRACK[e.old]?.label} → ` : ""}<b>{e.new ? TRACK[e.new]?.label : ""}</b></span>
                : <span><b>Note</b></span>}
              {withJob && e.job_title && <button className="link" onClick={() => onOpen?.(e.app_id)}>{e.job_title}{e.job_company ? ` · ${e.job_company}` : ""}</button>}
              <small>{new Date(e.created_at * 1000).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</small>
              {e.source === "email" && <span className="badge mailb"><Icon name="mail" size={12} /> from email</span>}
            </div>
            {e.kind === "note" && <p className="small">{e.detail.text}</p>}
            {e.source === "email" && (
              <p className="small muted">“{e.detail.subject}” — {e.detail.from}{e.detail.reason ? <><br />Why: {e.detail.reason}</> : null}</p>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
