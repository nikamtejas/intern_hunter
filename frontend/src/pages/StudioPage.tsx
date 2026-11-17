import { useEffect, useRef, useState } from "react";
import { api, Meta, StudioResult } from "../api";
import { CountrySelect, Icon, PageHeader, ScoreRing, Spinner, useToast } from "../ui";

export default function StudioPage({ openApp }: { openApp: (id: number) => void }) {
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const [role, setRole] = useState("");
  const [country, setCountry] = useState<string>("india");
  const [meta, setMeta] = useState<Meta | null>(null);
  useEffect(() => { api.meta().then(setMeta); }, []);
  const region = meta?.countries.find((c) => c.key === country)?.region;
  const [roleDesc, setRoleDesc] = useState("");
  const [lang, setLang] = useState<"en" | "de">("en");
  const [cover, setCover] = useState(false);
  const [saveProfile, setSaveProfile] = useState(true);
  const [res, setRes] = useState<StudioResult | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [improving, setImproving] = useState(false);

  async function analyze(useProfile = false) {
    setAnalyzing(true);
    setRes(null);
    try {
      setRes(await api.studioAnalyze(useProfile ? null : file, role, country));
    } catch (e: any) {
      toast(e.message, "err");
    } finally {
      setAnalyzing(false);
    }
  }

  async function improve() {
    if (!role.trim()) return toast("Enter the role you're targeting first", "err");
    setImproving(true);
    try {
      const r = await api.studioImprove({
        target_role: role, country, language: lang, role_description: roleDesc, cover_letter: cover,
        profile: res?.profile ?? null, save_as_profile: !!res && saveProfile && !!file, raw_text: res?.raw_text,
      });
      toast("Writing your improved resume…");
      openApp(r.created[0]);
    } catch (e: any) {
      toast(e.message, "err");
    } finally {
      setImproving(false);
    }
  }

  const sev = { high: "err", medium: "warn", low: "info" } as const;

  return (
    <div className="page">
      <PageHeader title="Resume Studio" subtitle="Upload any resume. Get a recruiter-style review, then a rewritten, ATS-ready version — tailored to the role you want." />

      <div className="studio-grid">
        <section className="card">
          <h3>1 · Your resume</h3>
          <div className={`drop ${drag ? "drag" : ""} ${file ? "has" : ""}`}
               onClick={() => fileRef.current?.click()}
               onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
               onDragLeave={() => setDrag(false)}
               onDrop={(e) => { e.preventDefault(); setDrag(false); e.dataTransfer.files[0] && setFile(e.dataTransfer.files[0]); }}>
            <input ref={fileRef} type="file" accept=".pdf,.docx,.txt" hidden onChange={(e) => e.target.files?.[0] && setFile(e.target.files[0])} />
            <div className="drop-icon"><Icon name={file ? "file" : "upload"} size={24} /></div>
            {file ? <><b>{file.name}</b><small>{(file.size / 1024).toFixed(0)} KB · click to change</small></>
                  : <><b>Drop your resume here</b><small>PDF, DOCX or TXT — or click to browse</small></>}
          </div>
          <button className="btn link-btn" onClick={() => analyze(true)} disabled={analyzing}>or analyse my saved profile instead</button>

          <h3 className="mt">2 · What are you aiming for?</h3>
          <label className="lbl">Target role
            <input placeholder="e.g. Data Science Intern, Marketing Intern, Werkstudent Software Engineering" value={role} onChange={(e) => setRole(e.target.value)} />
          </label>
          <div className="row">
            {meta && <CountrySelect countries={meta.countries} value={country}
                                    onChange={(c) => { setCountry(c); if (meta.countries.find((x) => x.key === c)?.region !== "germany") setLang("en"); }} />}
            {region === "germany" && (
              <div className="pills">
                <button className={lang === "en" ? "on" : ""} onClick={() => setLang("en")}>English</button>
                <button className={lang === "de" ? "on" : ""} onClick={() => setLang("de")}>Deutsch</button>
              </div>
            )}
          </div>
          <label className="lbl">Job description <span className="muted">(optional — paste one for a sharper match)</span>
            <textarea rows={5} value={roleDesc} onChange={(e) => setRoleDesc(e.target.value)} />
          </label>
          <div className="row">
            <button className="btn primary" disabled={!file || analyzing} onClick={() => analyze(false)}>
              {analyzing ? <><Spinner /> Analysing…</> : <><Icon name="search" /> Analyse resume</>}
            </button>
            <button className="btn" disabled={improving || !role.trim() || (!res && !file)} onClick={improve}
                    title={!res && file ? "Analyse first" : ""}>
              <Icon name="spark" /> Generate improved resume
            </button>
          </div>
        </section>

        <section className="card result-card">
          {!res && !analyzing && (
            <div className="placeholder">
              <div className="ph-ring"><ScoreRing score={0} size={110} label="score" /></div>
              <h3>Your review appears here</h3>
              <p className="muted">You'll get an honest score, the biggest problems ranked by impact, bullet rewrites, and ATS risks.</p>
            </div>
          )}
          {analyzing && <div className="placeholder"><Spinner /><p className="muted">Reading your resume like a recruiter would…</p></div>}
          {res && (
            <>
              <div className="review-head">
                <ScoreRing score={res.ai.overall || 0} size={110} label="quality" target={85} />
                <div>
                  <h3>{res.profile.name || "Your resume"}</h3>
                  <p>{res.ai.verdict}</p>
                  <div className="row tight">
                    <span className="badge">{res.local.word_count} words</span>
                    <span className="badge">{res.local.bullets_with_numbers}/{res.local.bullets} bullets with numbers</span>
                    <span className="badge">{res.local.passed}/{res.local.total} checks passed</span>
                  </div>
                </div>
              </div>

              <div className="checks">
                {res.local.checks.map((c) => (
                  <span key={c.label} className={`check ${c.ok ? "ok" : "bad"}`}><Icon name={c.ok ? "check" : "x"} size={14} />{c.label}</span>
                ))}
              </div>

              {res.local.style.cliches.length > 0 && (
                <div className="banner warn">Generic/AI-sounding words found: <b>{res.local.style.cliches.join(", ")}</b></div>
              )}

              {res.ai.strengths.length > 0 && <>
                <h4>What works</h4>
                <ul className="clean good">{res.ai.strengths.map((s, i) => <li key={i}><Icon name="check" size={15} />{s}</li>)}</ul>
              </>}

              <h4>What to fix</h4>
              <div className="issues">
                {res.ai.issues.map((x, i) => (
                  <div key={i} className={`issue ${sev[x.severity] || "info"}`}>
                    <div className="issue-top"><span className="sev">{x.severity}</span><b>{x.section}</b></div>
                    <p>{x.problem}</p>
                    <p className="fix"><Icon name="arrow" size={14} /> {x.fix}</p>
                  </div>
                ))}
              </div>

              {res.ai.bullet_rewrites.length > 0 && <>
                <h4>Bullet rewrites</h4>
                {res.ai.bullet_rewrites.map((b, i) => (
                  <div key={i} className="rewrite">
                    <div className="before">{b.original}</div>
                    <div className="after">{b.improved}</div>
                    <small className="muted">{b.why}</small>
                  </div>
                ))}
                <p className="hint">Placeholders like [X%] mean: put in your real number — never make one up.</p>
              </>}

              {(res.ai.ats_risks.length > 0 || res.local.ats_risks.length > 0) && <>
                <h4>ATS risks</h4>
                <ul className="clean warnlist">{[...res.local.ats_risks, ...res.ai.ats_risks].map((s, i) => <li key={i}><Icon name="x" size={14} />{s}</li>)}</ul>
              </>}

              {res.ai.keywords_to_consider.length > 0 && <>
                <h4>Keywords recruiters search for</h4>
                <div className="chips">{res.ai.keywords_to_consider.map((k) => <span key={k} className="chip">{k}</span>)}</div>
                <p className="hint">Add these to your profile only if you genuinely have them.</p>
              </>}

              <div className="improve-box">
                <div>
                  <b>Ready for the rewrite?</b>
                  <p className="muted small">The AI writes a fresh, human-sounding version for “{role || "your target role"}” using only facts from your resume, then scores and polishes it.</p>
                  <div className="row tight">
                    {file && <label className="switch"><input type="checkbox" checked={saveProfile} onChange={(e) => setSaveProfile(e.target.checked)} /><i />Save as my master profile</label>}
                    <label className="switch"><input type="checkbox" checked={cover} onChange={(e) => setCover(e.target.checked)} /><i />Also write a cover letter</label>
                  </div>
                </div>
                <button className="btn primary lg" disabled={improving || !role.trim()} onClick={improve}>
                  {improving ? <Spinner /> : <Icon name="spark" />} Generate improved resume
                </button>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
