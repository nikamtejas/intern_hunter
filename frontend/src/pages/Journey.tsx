import { ReactNode, useEffect, useState } from "react";
import { api, AppEvent, Application, dateShort, FollowUp, TRACK, Track } from "../api";
import { Icon, Spinner, TrackSelect, useToast } from "../ui";

type Node = {
  id: string; col: number; row: number; title: string; sub?: string; tone: string; dashed?: boolean;
  detail: () => ReactNode;
};

const W = 172, H = 60, GX = 210, GY = 92, PAD = 24;
const STAGE_ICON: Record<string, string> = { applied: "📨", assessment: "🧪", interview: "🎤", offer: "🎉", rejected: "✖", withdrawn: "↩" };

/** The application as a tree: a trunk of milestones (job → resume → applied → stages) with branches hanging off each
 *  milestone (cover letter, prep, emails, notes) and dashed "next step" suggestions at the end. */
export default function Journey({ id, onClose, openFull }: { id: number; onClose: () => void; openFull: (id: number) => void }) {
  const toast = useToast();
  const [a, setA] = useState<Application | null>(null);
  const [sel, setSel] = useState<string>("job");
  const [busy, setBusy] = useState("");
  const load = () => api.app(id).then(setA);
  useEffect(() => { load(); }, [id]);

  if (!a) return <Modal onClose={onClose}><Spinner /></Modal>;

  const events = [...(a.events || [])].sort((x, y) => x.created_at - y.created_at);
  const stages = events.filter((e) => e.kind === "status" && e.new && e.new !== "not_applied" && e.new !== "applied");
  const daysSinceApplied = a.applied_at ? Math.floor((Date.now() / 1000 - a.applied_at) / 86400) : 0;
  const ats = a.ats;

  const trunk: Node[] = [];
  const branches: Node[] = [];
  const addTrunk = (n: Omit<Node, "col" | "row">) => trunk.push({ ...n, col: trunk.length, row: 0 });
  const addBranch = (col: number, n: Omit<Node, "col" | "row">) =>
    branches.push({ ...n, col, row: 1 + branches.filter((b) => b.col === col).length });

  addTrunk({ id: "job", title: a.job?.company || "Job", sub: a.job?.title, tone: "idle", detail: () => (
    <>
      <h4>{a.job?.title}</h4>
      <p className="muted">{[a.job?.company, a.job?.location].filter(Boolean).join(" · ")}</p>
      {a.job?.url && <a className="btn sm" href={a.job.url} target="_blank" rel="noreferrer"><Icon name="external" size={14} /> Original posting</a>}
      <div className="jd small">{(a.job?.description || "").slice(0, 900)}{(a.job?.description || "").length > 900 ? "…" : ""}</div>
    </>
  ) });
  if (a.status === "done" && ats) {
    addTrunk({ id: "resume", title: `Resume · ${Math.round(ats.ats.score)}`, sub: ats.checks?.ready ? "Ready to send ✓" : "Needs fixes",
               tone: ats.checks?.ready ? "ok" : "warn", detail: () => (
      <>
        <h4>Tailored resume — ATS {Math.round(ats.ats.score)}</h4>
        <ul className="clean small">{(ats.checks?.rules || []).map((r) => <li key={r.id}><Icon name={r.ok ? "check" : "x"} size={13} />{r.label}: {r.detail}</li>)}</ul>
        <div className="row tight">
          <a className="btn sm primary" href={`/api/applications/${a.id}/resume.pdf`} download><Icon name="download" size={14} /> PDF</a>
          <a className="btn sm" href={`/api/applications/${a.id}/resume.pdf`} target="_blank" rel="noreferrer">Preview</a>
          <button className="btn sm ghost" onClick={() => openFull(a.id)}>Open full report</button>
        </div>
      </>
    ) });
    const rc = trunk.length - 1;
    if (a.cover_letter) addBranch(rc, { id: "cover", title: "Cover letter", sub: "PDF · DOCX", tone: "idle", detail: () => (
      <>
        <h4>{a.cover_letter!.subject}</h4>
        <p className="small">{a.cover_letter!.paragraphs[0]}</p>
        <a className="btn sm" href={`/api/applications/${a.id}/cover.pdf`} download>Download letter</a>
      </>
    ) });
    if (ats.auto_learning?.length) addBranch(rc, { id: "learn", title: "Currently learning", sub: ats.auto_learning.slice(0, 3).join(", "), tone: "accent",
      detail: () => <><h4>Skills to learn for this job</h4><p className="small">{ats.auto_learning!.join(", ")}</p><p className="muted small">Generate interview prep for a 7-day plan with free resources.</p></> });
    addBranch(rc, { id: "prep", title: a.prep ? "Interview prep ✓" : "Interview prep", sub: a.prep ? `${a.prep.questions.length} questions` : "click to create",
                    tone: a.prep ? "ok" : "idle", dashed: !a.prep, detail: () => <PrepView a={a} busy={busy === "prep"} make={makePrep} /> });
  }
  if (a.applied_at) {
    addTrunk({ id: "applied", title: `${STAGE_ICON.applied} Applied`, sub: dateShort(a.applied_at), tone: "info", detail: () => (
      <><h4>Applied {dateShort(a.applied_at)}</h4><p className="muted small">{daysSinceApplied} day{daysSinceApplied === 1 ? "" : "s"} ago</p></>
    ) });
  } else {
    addTrunk({ id: "apply", title: "📨 Apply", sub: "mark when sent", tone: "idle", dashed: true, detail: () => (
      <><h4>Not applied yet</h4><p className="small">Send the resume, then mark it here — the tracker and follow-up reminders start from that date.</p>
        <button className="btn sm primary" onClick={() => setTrack("applied")}>I applied today</button></>
    ) });
  }
  stages.forEach((e, i) => {
    addTrunk({ id: `st${i}`, title: `${STAGE_ICON[e.new!] || "•"} ${TRACK[e.new as Track]?.label}`, sub: dateShort(e.created_at) + (e.source === "email" ? " · 📧" : ""),
               tone: TRACK[e.new as Track]?.tone || "idle", detail: () => <EventView e={e} /> });
    if (e.source === "email" && e.detail.subject)
      addBranch(trunk.length - 1, { id: `em${i}`, title: "📧 " + (e.detail.from || "Email").split("<")[0].trim().slice(0, 22), sub: e.detail.subject, tone: "info", detail: () => <EventView e={e} /> });
  });
  // notes hang under the milestone that was current when they were written
  events.filter((e) => e.kind === "note").forEach((e, i) => {
    const col = Math.max(0, ...trunk.map((t, k) => (stageTime(t, a, stages) <= e.created_at ? k : 0)));
    addBranch(col, { id: `note${i}`, title: "📝 Note", sub: e.detail.text, tone: "idle", detail: () => <><h4>Note · {dateShort(e.created_at)}</h4><p>{e.detail.text}</p></> });
  });
  // what could come next
  const t = a.track;
  if (t === "applied" && daysSinceApplied >= 5)
    addTrunk({ id: "fu", title: "📨 Follow up", sub: `${daysSinceApplied} days, no reply`, tone: "warn", dashed: true, detail: () => <FollowUpView a={a} busy={busy === "fu"} make={makeFollowUp} /> });
  const next: Partial<Record<Track, Track>> = { applied: "interview", assessment: "interview", interview: "offer" };
  if (next[t]) addTrunk({ id: "next", title: `${STAGE_ICON[next[t]!]} ${TRACK[next[t]!].label}?`, sub: "next step", tone: "idle", dashed: true,
    detail: () => <><h4>Waiting for the next step</h4><p className="small">Move it forward when you hear back — or connect your inbox on the Tracker so replies update it automatically.</p>
      <TrackSelect value={a.track} onChange={setTrack} /></> });

  const nodes = [...trunk, ...branches];
  const cols = Math.max(...nodes.map((n) => n.col)) + 1;
  const rows = Math.max(...nodes.map((n) => n.row)) + 1;
  const pos = (n: Node) => ({ x: PAD + n.col * GX, y: PAD + n.row * GY });
  const selNode = nodes.find((n) => n.id === sel) || nodes[0];

  async function setTrack(tr: Track) {
    setA(await api.setTrack(a!.id, { track: tr }));
    toast(`Marked as ${TRACK[tr].label}`);
  }
  async function makePrep() {
    setBusy("prep");
    try { await api.prep(a!.id); await load(); toast("Interview prep ready"); } catch (e: any) { toast(e.message, "err"); } finally { setBusy(""); }
  }
  async function makeFollowUp() {
    setBusy("fu");
    try { const f = await api.followup(a!.id); setA({ ...a!, followup: f }); } catch (e: any) { toast(e.message, "err"); } finally { setBusy(""); }
  }

  return (
    <Modal onClose={onClose} wide>
      <div className="journey-head">
        <div>
          <span className="eyebrow">Application journey</span>
          <h2>{a.job?.title}</h2>
          <p className="muted">{a.job?.company}{a.applied_at ? ` · applied ${dateShort(a.applied_at)}` : ""}</p>
        </div>
        <div className="row tight"><TrackSelect value={a.track} onChange={setTrack} />
          <button className="btn ghost icon-only" onClick={onClose} aria-label="Close"><Icon name="x" /></button></div>
      </div>
      <div className="tree-scroll">
        <div className="tree" style={{ width: PAD * 2 + (cols - 1) * GX + W, height: PAD * 2 + (rows - 1) * GY + H }}>
          <svg className="tree-lines" width="100%" height="100%">
            {trunk.slice(1).map((n, i) => {
              const p = pos(trunk[i]), q = pos(n);
              return <path key={n.id} d={`M${p.x + W} ${p.y + H / 2} L${q.x} ${q.y + H / 2}`} className={n.dashed ? "dashed" : ""} />;
            })}
            {branches.map((b) => {
              const p = pos(trunk[b.col]), q = pos(b);
              const sx = p.x + 22, sy = p.y + H;
              return <path key={b.id} d={`M${sx} ${sy} L${sx} ${q.y + H / 2} L${q.x} ${q.y + H / 2}`} className={b.dashed ? "dashed" : ""} />;
            })}
          </svg>
          {nodes.map((n) => {
            const p = pos(n);
            return (
              <button key={n.id} className={`tnode t-${n.tone} ${n.dashed ? "dashed" : ""} ${n.row ? "branch" : ""} ${sel === n.id ? "sel" : ""}`}
                      style={{ left: p.x + (n.row ? 14 : 0), top: p.y, width: W - (n.row ? 14 : 0), height: H }} onClick={() => setSel(n.id)}>
                <b>{n.title}</b>
                {n.sub && <small>{n.sub}</small>}
              </button>
            );
          })}
        </div>
      </div>
      <div className="tree-detail">{selNode.detail()}</div>
    </Modal>
  );
}

function stageTime(t: Node, a: Application, stages: AppEvent[]): number {
  if (t.id === "job" || t.id === "resume") return a.created_at;
  if (t.id === "applied") return a.applied_at || 0;
  if (t.id.startsWith("st")) return stages[Number(t.id.slice(2))]?.created_at || 0;
  return Number.MAX_SAFE_INTEGER;
}

function EventView({ e }: { e: AppEvent }) {
  return (
    <>
      <h4>{e.old ? `${TRACK[e.old]?.label} → ` : ""}{e.new ? TRACK[e.new]?.label : ""} · {dateShort(e.created_at)}</h4>
      {e.source === "email" ? (
        <>
          <p className="small"><b>{e.detail.subject}</b><br /><span className="muted">{e.detail.from}</span></p>
          {e.detail.snippet && <p className="small muted">“{e.detail.snippet}…”</p>}
          {e.detail.reason && <p className="small">Why it moved: {e.detail.reason}</p>}
        </>
      ) : <p className="muted small">Changed by you.</p>}
    </>
  );
}

export function PrepView({ a, busy, make }: { a: Application; busy: boolean; make: () => void }) {
  const p = a.prep;
  if (!p)
    return (
      <>
        <h4>Interview prep for this job</h4>
        <p className="small">Likely questions with answer outlines built from your own resume, smart questions to ask, and a 7-day plan with
          free resources for the skills you're still learning.</p>
        <button className="btn primary sm" disabled={busy} onClick={make}>{busy ? <><Spinner /> Preparing…</> : <><Icon name="spark" size={14} /> Create interview prep</>}</button>
      </>
    );
  return (
    <div className="prep">
      <div className="row tight" style={{ justifyContent: "space-between" }}>
        <h4>Your pitch</h4>
        <button className="btn ghost sm" disabled={busy} onClick={make}>{busy ? <Spinner /> : <><Icon name="refresh" size={14} /> Redo</>}</button>
      </div>
      <p className="small">{p.elevator_pitch}</p>
      <h4>Likely questions</h4>
      {p.questions.map((q, i) => (
        <details key={i} className="q">
          <summary><span className={`qtype ${q.type}`}>{q.type}</span>{q.question}</summary>
          {q.why_they_ask && <p className="small muted">Why they ask: {q.why_they_ask}</p>}
          <p className="small">{q.answer_outline}</p>
          {q.based_on && <p className="small muted">From: {q.based_on}</p>}
        </details>
      ))}
      {!!p.brush_up.length && <>
        <h4>7-day brush-up</h4>
        <div className="brush">
          {p.brush_up.map((b, i) => (
            <div key={i} className="brush-card">
              <b>{b.skill}</b>
              <p className="small muted">{b.why}</p>
              <ol className="small">{b.days.map((d, k) => <li key={k}>{d}</li>)}</ol>
              {!!b.free_resources.length && <p className="small"><b>Free:</b> {b.free_resources.join(" · ")}</p>}
            </div>
          ))}
        </div>
      </>}
      {!!p.questions_to_ask.length && <><h4>Ask them</h4><ul className="small">{p.questions_to_ask.map((q, i) => <li key={i}>{q}</li>)}</ul></>}
      {!!p.red_flags.length && <><h4>Be ready for</h4><ul className="small">{p.red_flags.map((q, i) => <li key={i}>{q}</li>)}</ul></>}
    </div>
  );
}

export function FollowUpView({ a, busy, make }: { a: Application; busy: boolean; make: () => void }) {
  const toast = useToast();
  const f: FollowUp | null | undefined = a.followup;
  return (
    <>
      <h4>Follow up</h4>
      <p className="small muted">No reply yet. A short, polite follow-up after 7–10 days is normal and often gets a response.</p>
      {!f ? (
        <button className="btn primary sm" disabled={busy} onClick={make}>{busy ? <><Spinner /> Writing…</> : <><Icon name="mail" size={14} /> Draft follow-up email</>}</button>
      ) : (
        <div className="draft">
          <b>{f.subject}</b>
          <pre>{f.body}</pre>
          <div className="row tight">
            <button className="btn sm primary" onClick={() => { navigator.clipboard.writeText(`${f.subject}\n\n${f.body}`); toast("Copied"); }}>Copy</button>
            <a className="btn sm" href={`mailto:?subject=${encodeURIComponent(f.subject)}&body=${encodeURIComponent(f.body)}`}>Open in email app</a>
            <button className="btn sm ghost" disabled={busy} onClick={make}>Rewrite</button>
          </div>
        </div>
      )}
    </>
  );
}

function Modal({ children, onClose, wide }: { children: ReactNode; onClose: () => void; wide?: boolean }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className="modal" onClick={onClose}>
      <div className={`modal-body ${wide ? "journey" : ""}`} onClick={(e) => e.stopPropagation()}>{children}</div>
    </div>
  );
}
