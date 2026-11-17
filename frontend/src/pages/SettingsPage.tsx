import { useEffect, useState } from "react";
import { api } from "../api";
import { Icon, PageHeader, useToast } from "../ui";

const GROUPS: [string, [string, string, string][]][] = [
  ["Groq AI", [
    ["GROQ_API_KEY", "API key", "gsk_… — free at console.groq.com/keys"],
    ["GROQ_MODEL", "Model", "openai/gpt-oss-120b"],
    ["GROQ_FALLBACK_MODEL", "Fallback model when the main one hits its free-tier limit", "openai/gpt-oss-20b"],
  ]],
  ["Resume quality", [
    ["ATS_TARGET", "Target ATS score (98 = keep rewriting until nearly every keyword you genuinely have is covered)", "98"],
    ["ATS_MAX_ROUNDS", "Max AI passes per resume (write + edits)", "4"],
    ["AUTO_LEARNING", "Put the job's missing technical skills in a “Currently learning” row (lifts ATS 90+; never claimed as experience)", "toggle"],
  ]],
  ["Job sources", [
    ["ADZUNA_APP_ID", "Adzuna app ID (optional)", "developer.adzuna.com"],
    ["ADZUNA_APP_KEY", "Adzuna app key (optional)", ""],
    ["LINKEDIN_DELAY", "LinkedIn delay between requests (seconds)", "2.0 — keep ≥ 1.5"],
    ["LINKEDIN_MAX_PAGES", "LinkedIn pages per search pass", "4 (10 jobs per page)"],
  ]],
];

export default function SettingsPage({ onSaved }: { onSaved: (groqOk: boolean) => void }) {
  const toast = useToast();
  const [s, setS] = useState<Record<string, any>>({});
  useEffect(() => { api.settings().then(setS); }, []);
  async function save() {
    try {
      const r = await api.saveSettings(s);
      setS(r);
      onSaved(!!r.groq_configured);
      toast("Settings saved");
    } catch (e: any) {
      toast(e.message, "err");
    }
  }
  return (
    <div className="page narrow">
      <PageHeader title="Settings" subtitle="Saved only on this computer (backend/data/app.db). Your API key never leaves your machine except to call Groq." />
      {GROUPS.map(([g, fields]) => (
        <section key={g} className="card">
          <h3>{g === "Groq AI" && <Icon name="key" />} {g}</h3>
          {fields.map(([k, label, hint]) => hint === "toggle" ? (
            <label key={k} className="switch inline">
              <input type="checkbox" checked={(s[k] ?? "1") === "1"} onChange={(e) => setS({ ...s, [k]: e.target.checked ? "1" : "0" })} />
              <i />{label}
            </label>
          ) : (
            <label key={k} className="lbl">
              {label}
              <input type={k.endsWith("_KEY") ? "password" : "text"} value={s[k] ?? ""} placeholder={hint}
                     onChange={(e) => setS({ ...s, [k]: e.target.value })} />
            </label>
          ))}
        </section>
      ))}
      <div className="row"><button className="btn primary lg" onClick={save}><Icon name="check" /> Save settings</button></div>
    </div>
  );
}
