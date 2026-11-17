import { useEffect, useState } from "react";
import { api, CheckItem, Profile } from "../api";
import { Icon, PageHeader, Spinner, useToast } from "../ui";

const csv = (a: string[]) => a.join(", ");
const uncsv = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);
const lines = (a: string[]) => a.join("\n");
const unlines = (s: string) => s.split("\n").map((x) => x.replace(/^[•\-*]\s*/, "").trim()).filter(Boolean);

export function ProfileEditor({ value, onChange }: { value: Profile; onChange: (p: Profile) => void }) {
  const p = value;
  const set = (patch: Partial<Profile>) => onChange({ ...p, ...patch });
  function listEditor<K extends keyof Profile>(key: K, blank: any, render: (item: any, upd: (patch: any) => void) => JSX.Element, label: string) {
    const items = p[key] as any[];
    return (
      <fieldset>
        <legend>{label}<em>{items.length}</em></legend>
        {items.map((it, i) => (
          <div key={i} className="item">
            {render(it, (patch) => set({ [key]: items.map((x, j) => (j === i ? { ...x, ...patch } : x)) } as any))}
            <div className="row item-actions">
              <button className="btn ghost sm" disabled={i === 0} onClick={() => { const a = [...items]; [a[i - 1], a[i]] = [a[i], a[i - 1]]; set({ [key]: a } as any); }}>Move up</button>
              <button className="btn ghost sm danger" onClick={() => set({ [key]: items.filter((_, j) => j !== i) } as any)}><Icon name="trash" size={14} /> Remove</button>
            </div>
          </div>
        ))}
        <button className="btn add" onClick={() => set({ [key]: [...items, structuredClone(blank)] } as any)}><Icon name="plus" size={15} /> Add {label.split(" ")[0].toLowerCase()}</button>
      </fieldset>
    );
  }

  return (
    <div className="editor">
      <fieldset>
        <legend>Contact</legend>
        <div className="grid2">
          <input placeholder="Full name" value={p.name} onChange={(e) => set({ name: e.target.value })} />
          <input placeholder="Headline (e.g. Computer Science Student)" value={p.headline} onChange={(e) => set({ headline: e.target.value })} />
          <input placeholder="Email" value={p.email} onChange={(e) => set({ email: e.target.value })} />
          <input placeholder="Phone (with country code)" value={p.phone} onChange={(e) => set({ phone: e.target.value })} />
          <input placeholder="City, Country" value={p.location} onChange={(e) => set({ location: e.target.value })} />
        </div>
        <div className="grid2 links-grid">
          <label className="lbl">LinkedIn<input placeholder="linkedin.com/in/your-name" value={p.linkedin} onChange={(e) => set({ linkedin: e.target.value })} /></label>
          <label className="lbl">GitHub<input placeholder="github.com/your-username" value={p.github} onChange={(e) => set({ github: e.target.value })} /></label>
          <label className="lbl">Portfolio / website<input placeholder="yourname.dev (optional)" value={p.portfolio} onChange={(e) => set({ portfolio: e.target.value })} /></label>
          <label className="lbl">Other links<input placeholder="kaggle.com/you, leetcode.com/you (comma separated)" value={p.links.map((l) => l.url).join(", ")}
                 onChange={(e) => set({ links: uncsv(e.target.value).map((url) => ({ label: "", url })) })} /></label>
        </div>
        <p className="hint">Links appear on the resume as clickable text recruiters can also read on paper.</p>
        <textarea rows={3} placeholder="Summary" value={p.summary} onChange={(e) => set({ summary: e.target.value })} />
      </fieldset>

      {listEditor("education", { institution: "", degree: "", field: "", location: "", start: "", end: "", grade: "", details: [] }, (e, u) => (
        <>
          <div className="grid3">
            <input placeholder="Degree (B.Tech, M.Sc…)" value={e.degree} onChange={(x) => u({ degree: x.target.value })} />
            <input placeholder="Field" value={e.field} onChange={(x) => u({ field: x.target.value })} />
            <input placeholder="Institution" value={e.institution} onChange={(x) => u({ institution: x.target.value })} />
            <input placeholder="Start" value={e.start} onChange={(x) => u({ start: x.target.value })} />
            <input placeholder="End / Expected" value={e.end} onChange={(x) => u({ end: x.target.value })} />
            <input placeholder="CGPA / Grade" value={e.grade} onChange={(x) => u({ grade: x.target.value })} />
          </div>
          <textarea rows={2} placeholder="Coursework / details (one per line)" value={lines(e.details)} onChange={(x) => u({ details: unlines(x.target.value) })} />
        </>
      ), "Education")}

      {listEditor("experience", { title: "", company: "", location: "", start: "", end: "", bullets: [] }, (e, u) => (
        <>
          <div className="grid3">
            <input placeholder="Title" value={e.title} onChange={(x) => u({ title: x.target.value })} />
            <input placeholder="Company" value={e.company} onChange={(x) => u({ company: x.target.value })} />
            <input placeholder="Location" value={e.location} onChange={(x) => u({ location: x.target.value })} />
            <input placeholder="Start" value={e.start} onChange={(x) => u({ start: x.target.value })} />
            <input placeholder="End" value={e.end} onChange={(x) => u({ end: x.target.value })} />
          </div>
          <textarea rows={4} placeholder="What you did — one bullet per line. Include numbers where real." value={lines(e.bullets)} onChange={(x) => u({ bullets: unlines(x.target.value) })} />
        </>
      ), "Experience / Internships")}

      {listEditor("projects", { name: "", tech: [], link: "", live: "", start: "", end: "", bullets: [] }, (e, u) => (
        <>
          <div className="grid2">
            <input placeholder="Project name" value={e.name} onChange={(x) => u({ name: x.target.value })} />
            <input placeholder="Tech (comma separated)" value={csv(e.tech)} onChange={(x) => u({ tech: uncsv(x.target.value) })} />
            <input placeholder="Code link — github.com/you/repo" value={e.link} onChange={(x) => u({ link: x.target.value })} />
            <input placeholder="Live demo link — app.vercel.app (if deployed)" value={e.live || ""} onChange={(x) => u({ live: x.target.value })} />
          </div>
          <textarea rows={3} placeholder="One bullet per line" value={lines(e.bullets)} onChange={(x) => u({ bullets: unlines(x.target.value) })} />
        </>
      ), "Projects")}

      <fieldset>
        <legend>Skills (comma separated) — list everything you genuinely know; the AI picks what fits each job</legend>
        <label>Technical<textarea rows={2} value={csv(p.skills.technical)} onChange={(e) => set({ skills: { ...p.skills, technical: uncsv(e.target.value) } })} /></label>
        <label>Tools<textarea rows={2} value={csv(p.skills.tools)} onChange={(e) => set({ skills: { ...p.skills, tools: uncsv(e.target.value) } })} /></label>
        <label>Soft skills<input value={csv(p.skills.soft)} onChange={(e) => set({ skills: { ...p.skills, soft: uncsv(e.target.value) } })} /></label>
        <label>Currently learning — shown as its own row so ATS scanners see it; never claimed as experience
          <input placeholder="e.g. AWS, Kubernetes (only what you've actually started)" value={csv(p.learning || [])}
                 onChange={(e) => set({ learning: uncsv(e.target.value) })} /></label>
      </fieldset>

      {listEditor("languages", { name: "", level: "" }, (e, u) => (
        <div className="grid2">
          <input placeholder="Language" value={e.name} onChange={(x) => u({ name: x.target.value })} />
          <input placeholder="Level (Native, C1, B2…)" value={e.level} onChange={(x) => u({ level: x.target.value })} />
        </div>
      ), "Languages (important for Germany)")}

      {listEditor("certifications", { name: "", issuer: "", date: "" }, (e, u) => (
        <div className="grid3">
          <input placeholder="Certificate" value={e.name} onChange={(x) => u({ name: x.target.value })} />
          <input placeholder="Issuer" value={e.issuer} onChange={(x) => u({ issuer: x.target.value })} />
          <input placeholder="Date" value={e.date} onChange={(x) => u({ date: x.target.value })} />
        </div>
      ), "Certifications")}

      <fieldset>
        <legend>Achievements (one per line)</legend>
        <textarea rows={3} value={lines(p.achievements)} onChange={(e) => set({ achievements: unlines(e.target.value) })} />
      </fieldset>

      <fieldset>
        <legend>Germany extras (used only for German applications)</legend>
        <div className="grid3">
          <input placeholder="Work permit (e.g. EU Blue Card eligible / Student visa)" value={p.extras.work_permit} onChange={(e) => set({ extras: { ...p.extras, work_permit: e.target.value } })} />
          <input placeholder="Availability (e.g. 6 months from 03/2027)" value={p.extras.availability} onChange={(e) => set({ extras: { ...p.extras, availability: e.target.value } })} />
          <input placeholder="Nationality (optional)" value={p.extras.nationality} onChange={(e) => set({ extras: { ...p.extras, nationality: e.target.value } })} />
        </div>
      </fieldset>
    </div>
  );
}

export default function ProfilePage() {
  const toast = useToast();
  const [p, setP] = useState<Profile | null>(null);
  const [uploading, setUploading] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [check, setCheck] = useState<{ score: number; items: CheckItem[] } | null>(null);
  const refreshCheck = () => api.checkProfile().then(setCheck).catch(() => {});

  useEffect(() => { api.profile().then(setP); refreshCheck(); }, []);

  async function upload(f: File) {
    setUploading(true);
    try {
      setP(await api.uploadResume(f));
      setDirty(true);
      toast("Resume read — review the details, then Save");
    } catch (e: any) {
      toast(e.message, "err");
    } finally {
      setUploading(false);
    }
  }

  async function save() {
    if (!p) return;
    try {
      setP(await api.saveProfile(p));
      setDirty(false);
      refreshCheck();
      toast("Profile saved");
    } catch (e: any) {
      toast(e.message, "err");
    }
  }

  if (!p) return <div className="page"><Spinner /></div>;
  return (
    <div className="page">
      <PageHeader title="My profile" subtitle={<>Your <b>master profile</b> — the only source of facts the AI uses. Add everything; it picks what fits each job.</>}>
        <label className="btn">
          <input type="file" hidden accept=".pdf,.docx,.txt" disabled={uploading} onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
          {uploading ? <><Spinner /> Reading…</> : <><Icon name="upload" /> Import from resume</>}
        </label>
      </PageHeader>
      {check && <MissingPanel check={check} />}
      <section className="card">
        <ProfileEditor value={p} onChange={(v) => { setP(v); setDirty(true); }} />
      </section>
      {dirty && (
        <div className="dock">
          <span>Unsaved changes</span>
          <button className="btn primary" onClick={save}><Icon name="check" /> Save profile</button>
        </div>
      )}
    </div>
  );
}

const SEV_LABEL = { high: "Fix first", medium: "Recommended", low: "Nice to have" } as const;

export function MissingPanel({ check, title = "What's missing" }: { check: { score: number; items: CheckItem[] }; title?: string }) {
  const [all, setAll] = useState(false);
  if (!check.items.length)
    return <div className="banner ok"><Icon name="check" size={15} /> Profile complete — contact, links, projects and metrics are all there.</div>;
  const shown = all ? check.items : check.items.slice(0, 6);
  return (
    <section className="card missing">
      <div className="missing-head">
        <div>
          <h3>{title}</h3>
          <p className="muted small">Recruiters look for these. The AI only uses what's in your profile, so gaps here cap every resume.</p>
        </div>
        <div className={`complete ${check.score >= 85 ? "ok" : check.score >= 60 ? "warn" : "err"}`}><b>{check.score}%</b><small>complete</small></div>
      </div>
      <ul className="missing-list">
        {shown.map((i, k) => (
          <li key={k} className={`sev-${i.severity}`}><span>{SEV_LABEL[i.severity]}</span>{i.message}</li>
        ))}
      </ul>
      {check.items.length > 6 && <button className="btn ghost sm" onClick={() => setAll(!all)}>{all ? "Show less" : `Show all ${check.items.length}`}</button>}
    </section>
  );
}
