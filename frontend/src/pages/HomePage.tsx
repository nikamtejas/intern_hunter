import { useEffect, useState } from "react";
import { api, Application, Profile } from "../api";
import type { Tab } from "../App";
import { Icon, ScoreRing } from "../ui";

export default function HomePage({ go, groqOk }: { go: (t: Tab, id?: number | null) => void; groqOk: boolean }) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [apps, setApps] = useState<Application[]>([]);
  useEffect(() => {
    api.profile().then(setProfile).catch(() => {});
    api.apps().then(setApps).catch(() => {});
  }, []);

  const hasProfile = !!profile && !!(profile.name && (profile.experience.length || profile.projects.length || profile.education.length));
  const done = apps.filter((a) => a.status === "done" && a.score !== undefined);
  const avg = done.length ? done.reduce((s, a) => s + (a.score || 0), 0) / done.length : 0;
  const steps: [boolean, string, string, Tab][] = [
    [groqOk, "Connect Groq AI", "Paste your free API key so the app can write resumes.", "settings"],
    [hasProfile, "Add your master profile", "Upload your resume once — everything else is built from it.", "profile"],
    [done.length > 0, "Generate your first tailored resume", "Search internships, tick the ones you like, generate.", "search"],
  ];
  const first = profile?.name?.split(" ")[0];

  return (
    <div className="page">
      <div className="hero">
        <div>
          <span className="eyebrow">Internships · India & Europe</span>
          <h1>{first ? `Hi ${first}, let's land that internship.` : "Land your internship faster."}</h1>
          <p>Find fresh internships from LinkedIn, Internshala, Arbeitsagentur and more — then get a resume tailored to each posting,
            written to pass ATS filters and read like a person wrote it.</p>
          <div className="row">
            <button className="btn primary lg" onClick={() => go("search")}><Icon name="search" /> Find internships</button>
            <button className="btn lg" onClick={() => go("studio")}><Icon name="studio" /> Improve my resume</button>
          </div>
        </div>
        <div className="hero-art" aria-hidden>
          <div className="mini-card a"><b>Data Science Intern</b><span>Bengaluru · 1 day ago</span><i>LinkedIn</i></div>
          <div className="mini-card b"><ScoreRing score={96} size={64} /><div><b>Tailored resume</b><span>Ready · PDF & DOCX</span></div></div>
          <div className="mini-card c"><b>Werkstudent Software</b><span>München · 3 days ago</span><i className="de">Arbeitsagentur</i></div>
        </div>
      </div>

      <div className="grid-home">
        <section className="card">
          <h3>Getting started</h3>
          <div className="steps">
            {steps.map(([ok, title, text, tab], i) => (
              <button key={i} className={`step ${ok ? "done" : ""}`} onClick={() => go(tab)}>
                <span className="step-num">{ok ? <Icon name="check" size={16} /> : i + 1}</span>
                <span className="step-text"><b>{title}</b><small>{text}</small></span>
                <Icon name="arrow" size={16} className="step-arrow" />
              </button>
            ))}
          </div>
        </section>
        <section className="card stats">
          <h3>Your progress</h3>
          <div className="stat-row">
            <div className="stat"><b>{apps.length}</b><span>Resumes generated</span></div>
            <div className="stat"><b>{done.length ? Math.round(avg) : "—"}</b><span>Average ATS score</span></div>
            <div className="stat"><b>{apps.filter((a) => a.track && a.track !== "not_applied").length}</b><span>Applied</span></div>
          </div>
          {done.slice(0, 3).map((a) => (
            <button key={a.id} className="recent" onClick={() => go("applications", a.id)}>
              <ScoreRing score={a.score || 0} target={a.target || 98} size={40} />
              <span><b>{a.job_title}</b><small>{a.job_company || "Resume Studio"}</small></span>
              <Icon name="arrow" size={16} />
            </button>
          ))}
        </section>
      </div>
    </div>
  );
}
