import { useEffect, useMemo, useState } from "react";
import { api, Job, Meta, SearchSummary, timeAgo } from "../api";
import { CountrySelect, Empty, Icon, PageHeader, SOURCE_LABEL, Spinner, TrackBadge, useToast, WorkModeBadge } from "../ui";

const RANGE_LABEL: Record<string, string> = { "24h": "24h", week: "week", month: "month" };

export default function SearchPage({ onGenerated, openApp }: { onGenerated: () => void; openApp: (id: number) => void }) {
  const toast = useToast();
  const [meta, setMeta] = useState<Meta | null>(null);
  const [country, setCountry] = useState<string>("india");
  const [workMode, setWorkMode] = useState("any");
  const cinfo = meta?.countries.find((c) => c.key === country);
  const flagOf = (k: string) => meta?.countries.find((c) => c.key === k)?.flag || "🌍";
  const [range, setRange] = useState("week");
  const [keywords, setKeywords] = useState("");
  const [location, setLocation] = useState("");
  const [sources, setSources] = useState<string[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [perSource, setPerSource] = useState<Record<string, number>>({});
  const [warnings, setWarnings] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState("");
  const [srcFilter, setSrcFilter] = useState("");
  const [preview, setPreview] = useState<Job | null>(null);
  const [lang, setLang] = useState<"en" | "de">("en");
  const [cover, setCover] = useState(true);
  const [busy, setBusy] = useState(false);
  const [showManual, setShowManual] = useState(false);
  const [recent, setRecent] = useState<SearchSummary[]>([]);
  const [activeSearch, setActiveSearch] = useState<number | null>(null);

  useEffect(() => { api.meta().then(setMeta); api.searches().then(setRecent).catch(() => {}); }, []);
  const available = useMemo(
    () => (meta ? Object.entries(meta.sources).filter(([, v]) => v.countries.includes(country)).map(([k]) => k) : []),
    [meta, country]
  );
  useEffect(() => setSources(available), [available.join(",")]);

  async function run() {
    setLoading(true);
    setWarnings([]);
    setSelected(new Set());
    setSrcFilter("");
    try {
      const r = await api.search({ country, time_range: range, sources, keywords, location, work_mode: workMode });
      setJobs(r.jobs);
      setPerSource(r.per_source);
      setWarnings(r.warnings);
      setSearched(true);
      setActiveSearch(r.search_id);
      api.searches().then(setRecent).catch(() => {});
    } catch (e: any) {
      toast(e.message, "err");
    } finally {
      setLoading(false);
    }
  }

  async function reopen(sid: number) {
    setLoading(true);
    try {
      const r = await api.savedSearch(sid);
      setCountry(r.params.country);
      setWorkMode(r.params.work_mode || "any");
      setRange(r.params.time_range);
      setKeywords(r.params.keywords || "");
      setLocation(r.params.location || "");
      setJobs(r.jobs);
      setPerSource(r.per_source);
      setWarnings(r.warnings || []);
      setSelected(new Set());
      setSrcFilter("");
      setSearched(true);
      setActiveSearch(sid);
    } catch (e: any) {
      toast(e.message, "err");
    } finally {
      setLoading(false);
    }
  }

  const shown = jobs.filter((j) =>
    (!srcFilter || j.source === srcFilter) &&
    (!filter || `${j.title} ${j.company} ${j.location}`.toLowerCase().includes(filter.toLowerCase()))
  );
  const toggle = (id: string) => {
    const s = new Set(selected);
    s.has(id) ? s.delete(id) : s.add(id);
    setSelected(s);
  };

  async function generate() {
    setBusy(true);
    try {
      const r = await api.createApps([...selected], lang, cover);
      toast(`Generating ${r.created.length} tailored resume${r.created.length > 1 ? "s" : ""}…`);
      onGenerated();
    } catch (e: any) {
      toast(e.message, "err");
    } finally {
      setBusy(false);
    }
  }

  async function openPreview(j: Job) {
    setPreview(j);
    try { setPreview(await api.job(j.id, true)); } catch {}
  }

  return (
    <div className="page">
      <PageHeader title="Find internships" subtitle="Fresh internship postings from every source, merged and de-duplicated.">
        <button className="btn" onClick={() => setShowManual(true)}><Icon name="paste" /> Paste a job</button>
      </PageHeader>

      <section className="card search-panel">
        <div className="search-row">
          <div className="field grow">
            <Icon name="search" />
            <input placeholder="Role or skill — e.g. data science, marketing, python (optional)" value={keywords}
                   onChange={(e) => setKeywords(e.target.value)} onKeyDown={(e) => e.key === "Enter" && run()} />
          </div>
          <div className="field">
            <Icon name="pin" />
            <input placeholder={`City — blank = all of ${cinfo?.key === "europe" ? "Europe" : cinfo?.name || ""}`} value={location}
                   onChange={(e) => setLocation(e.target.value)} onKeyDown={(e) => e.key === "Enter" && run()} />
          </div>
          <button className="btn primary lg" onClick={run} disabled={loading || !sources.length}>
            {loading ? <><Spinner /> Searching</> : <>Search</>}
          </button>
        </div>
        <div className="search-row opts">
          {meta && <CountrySelect countries={meta.countries} value={country}
                                  onChange={(c) => { setCountry(c); setJobs([]); setSearched(false);
                                                     if (meta.countries.find((x) => x.key === c)?.region !== "germany") setLang("en"); }} />}
          <div className="pills" title="LinkedIn has no remote filter of its own — postings are read to check">
            {Object.entries(meta?.work_modes || { any: "Any" }).map(([k, l]) => (
              <button key={k} className={workMode === k ? "on" : ""} onClick={() => setWorkMode(k)}>{l}</button>
            ))}
          </div>
          <div className="pills">
            {[["24h", "Last 24h"], ["week", "Past week"], ["month", "Past month"]].map(([k, l]) => (
              <button key={k} className={range === k ? "on" : ""} onClick={() => setRange(k)}><Icon name="clock" size={14} /> {l}</button>
            ))}
          </div>
          <div className="source-chips">
            {available.map((s) => (
              <button key={s} className={`schip ${sources.includes(s) ? "on" : ""}`}
                      onClick={() => setSources(sources.includes(s) ? sources.filter((x) => x !== s) : [...sources, s])}>
                <i className={`dot src-${s}`} />{SOURCE_LABEL[s]}
                {perSource[s] !== undefined && <em>{perSource[s]}</em>}
              </button>
            ))}
          </div>
        </div>
        {recent.length > 0 && (
          <div className="recent-searches">
            <span className="muted small">Your recent searches</span>
            {recent.slice(0, 8).map((r) => (
              <button key={r.id} className={`schip ${activeSearch === r.id ? "on" : ""}`} onClick={() => reopen(r.id)}
                      title={new Date(r.created_at * 1000).toLocaleString()}>
                {flagOf(r.params.country)} {r.params.keywords || "all internships"}
                {r.params.work_mode && r.params.work_mode !== "any" ? ` · ${meta?.work_modes[r.params.work_mode]}` : ""}
                {r.params.location ? ` · ${r.params.location}` : ""} · {RANGE_LABEL[r.params.time_range] || r.params.time_range}
                <em>{r.count}</em>
              </button>
            ))}
          </div>
        )}
        {loading && <div className="progress"><i /></div>}
        {loading && <p className="hint">LinkedIn is queried slowly on purpose so you don't get blocked — this can take up to a minute
          {workMode !== "any" ? " (a bit longer with a remote/hybrid filter: each LinkedIn posting is read to check)" : ""}.</p>}
      </section>

      {warnings.map((w, i) => <div key={i} className="banner warn">{w}</div>)}

      {jobs.length > 0 && (
        <>
          <div className="results-bar">
            <div className="results-title">
              <b>{shown.length}</b> internships
              <div className="pills sm">
                <button className={!srcFilter ? "on" : ""} onClick={() => setSrcFilter("")}>All</button>
                {Object.entries(perSource).filter(([, n]) => n > 0).map(([s, n]) => (
                  <button key={s} className={srcFilter === s ? "on" : ""} onClick={() => setSrcFilter(s)}>{SOURCE_LABEL[s]} {n}</button>
                ))}
              </div>
            </div>
            <div className="row">
              <div className="field sm"><Icon name="search" size={15} />
                <input placeholder="Filter results" value={filter} onChange={(e) => setFilter(e.target.value)} />
              </div>
              <button className="btn ghost" onClick={() => setSelected(shown.every((j) => selected.has(j.id)) ? new Set() : new Set(shown.map((j) => j.id)))}>
                {shown.length && shown.every((j) => selected.has(j.id)) ? "Clear" : "Select all"}
              </button>
            </div>
          </div>
          <div className="job-list">
            {shown.map((j) => (
              <article key={j.id} className={`job ${selected.has(j.id) ? "sel" : ""}`} onClick={() => toggle(j.id)}>
                <div className="job-check">{selected.has(j.id) && <Icon name="check" size={14} />}</div>
                <div className="job-logo">{(j.company || j.title).slice(0, 1).toUpperCase()}</div>
                <div className="job-main">
                  <h4>{j.title}</h4>
                  <div className="job-meta">
                    <span><Icon name="building" size={14} />{j.company || "—"}</span>
                    <span><Icon name="pin" size={14} />{country === "europe" && j.country !== "europe" ? `${flagOf(j.country)} ` : ""}{j.location || "—"}</span>
                    <WorkModeBadge mode={j.extra?.work_mode} />
                    {j.extra?.fit && <span className={`badge fit ${j.extra.fit.pct >= 70 ? "hi" : j.extra.fit.pct >= 40 ? "mid" : "lo"}`}
                      title={j.extra.fit.missing.length ? `Not on your profile: ${j.extra.fit.missing.join(", ")}` : "All named skills are on your profile"}>
                      🎯 {j.extra.fit.pct}% fit</span>}
                    <span><Icon name="clock" size={14} />{j.extra?.posted_text || timeAgo(j.posted_at)}</span>
                    {j.extra?.stipend && <span><Icon name="money" size={14} />{j.extra.stipend}{j.extra.duration ? ` · ${j.extra.duration}` : ""}</span>}
                  </div>
                </div>
                <div className="job-side" onClick={(e) => e.stopPropagation()}>
                  <span className={`badge src-${j.source}`}>{SOURCE_LABEL[j.source] || j.source}
                    {j.extra?.also_on?.length ? ` +${j.extra.also_on.length}` : ""}</span>
                  {j.extra?.mine && (
                    <button className="mine" title="Open your resume for this job" onClick={() => openApp(j.extra.mine.app_id)}>
                      {j.extra.mine.track === "not_applied" ? <span className="badge ok"><Icon name="file" size={12} /> Resume made</span>
                                                            : <TrackBadge track={j.extra.mine.track} />}
                    </button>
                  )}
                  <div className="row tight">
                    <button className="btn ghost sm" onClick={() => openPreview(j)}>Details</button>
                    {j.url && <a className="btn ghost sm icon-only" href={j.url} target="_blank" rel="noreferrer" title="Open posting"><Icon name="external" size={15} /></a>}
                  </div>
                </div>
              </article>
            ))}
          </div>
        </>
      )}

      {!loading && jobs.length === 0 && (
        searched
          ? <Empty icon="search" title="No internships found">Try a wider time range, fewer keywords, or leave the city empty.</Empty>
          : <Empty icon="search" title="Search to get started">Pick a country and time range. Then tick the internships you like and generate tailored resumes in one go.</Empty>
      )}

      {selected.size > 0 && (
        <div className="dock">
          <span className="dock-count">{selected.size}</span>
          <span>selected</span>
          <label className="switch"><input type="checkbox" checked={cover} onChange={(e) => setCover(e.target.checked)} /><i />Cover letter</label>
          {cinfo?.region === "germany" && (
            <div className="pills sm">
              <button className={lang === "en" ? "on" : ""} onClick={() => setLang("en")}>English</button>
              <button className={lang === "de" ? "on" : ""} onClick={() => setLang("de")}>Deutsch</button>
            </div>
          )}
          <button className="btn primary" disabled={busy} onClick={generate}>
            <Icon name="spark" /> {busy ? "Queuing…" : `Generate resume${selected.size > 1 ? "s" : ""}`}
          </button>
        </div>
      )}

      {preview && (
        <div className="modal" onClick={() => setPreview(null)}>
          <div className="modal-body" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <div>
                <h2>{preview.title}</h2>
                <p className="muted">{preview.company} · {preview.location}</p>
              </div>
              <button className="btn ghost icon-only" onClick={() => setPreview(null)}><Icon name="x" /></button>
            </div>
            <div className="jd">{preview.description || <><Spinner /> Loading full description…</>}</div>
            <div className="modal-foot">
              {preview.url && <a className="btn ghost" href={preview.url} target="_blank" rel="noreferrer"><Icon name="external" /> Original posting</a>}
              <button className="btn primary" onClick={() => { toggle(preview.id); setPreview(null); }}>
                {selected.has(preview.id) ? "Unselect" : "Select for resume"}
              </button>
            </div>
          </div>
        </div>
      )}

      {showManual && (
        <ManualJob country={country} onClose={() => setShowManual(false)}
                   onAdded={(j) => { setJobs([j, ...jobs]); setSelected(new Set([...selected, j.id])); setShowManual(false); toast("Job added and selected"); }} />
      )}
    </div>
  );
}

function ManualJob({ country, onClose, onAdded }: { country: string; onClose: () => void; onAdded: (j: Job) => void }) {
  const toast = useToast();
  const [f, setF] = useState({ title: "", company: "", location: "", url: "", description: "" });
  return (
    <div className="modal" onClick={onClose}>
      <div className="modal-body" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div>
            <h2>Paste a job posting</h2>
            <p className="muted">From Naukri, StepStone, Indeed, Xing, a careers page — anything.</p>
          </div>
          <button className="btn ghost icon-only" onClick={onClose}><Icon name="x" /></button>
        </div>
        <div className="grid2">
          <label className="lbl">Job title *<input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></label>
          <label className="lbl">Company<input value={f.company} onChange={(e) => setF({ ...f, company: e.target.value })} /></label>
          <label className="lbl">Location<input value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} /></label>
          <label className="lbl">URL<input value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} /></label>
        </div>
        <label className="lbl">Full job description *
          <textarea rows={10} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} />
        </label>
        <div className="modal-foot">
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={!f.title || f.description.length < 50}
                  onClick={() => api.manualJob({ ...f, country }).then(onAdded).catch((e) => toast(e.message, "err"))}>Add & select</button>
        </div>
      </div>
    </div>
  );
}
