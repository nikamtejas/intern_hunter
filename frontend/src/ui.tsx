import { createContext, ReactNode, useCallback, useContext, useState } from "react";
import { CountryInfo, Track, TRACK, TRACK_ORDER } from "./api";

const PATHS: Record<string, string> = {
  home: "M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  search: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zm10 17-5-5",
  studio: "M12 3l2.4 5.6L20 11l-5.6 2.4L12 19l-2.4-5.6L4 11l5.6-2.4z",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm-8 9a8 8 0 0 1 16 0",
  file: "M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8zm0 0v5h5M8 13h8M8 17h5",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm7.4-3a7.4 7.4 0 0 0-.1-1.3l2-1.6-2-3.4-2.4 1a7.5 7.5 0 0 0-2.2-1.3L14.3 3h-4l-.4 2.5a7.5 7.5 0 0 0-2.2 1.3l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 0 0 0 2.6l-2 1.6 2 3.4 2.4-1a7.5 7.5 0 0 0 2.2 1.3l.4 2.5h4l.4-2.5a7.5 7.5 0 0 0 2.2-1.3l2.4 1 2-3.4-2-1.6c.1-.4.1-.9.1-1.3z",
  pin: "M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11zm0-8.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zm0-13v4l3 2",
  building: "M4 21V5a1 1 0 0 1 1-1h9a1 1 0 0 1 1 1v16M15 9h4a1 1 0 0 1 1 1v11M8 8h3M8 12h3M8 16h3M2 21h20",
  external: "M14 4h6v6m0-6L11 13M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5",
  check: "M5 12.5l4.5 4.5L19 7.5",
  x: "M6 6l12 12M18 6 6 18",
  upload: "M12 16V4m0 0-4.5 4.5M12 4l4.5 4.5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3",
  download: "M12 4v12m0 0-4.5-4.5M12 16l4.5-4.5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3",
  refresh: "M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7",
  trash: "M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3",
  plus: "M12 5v14M5 12h14",
  arrow: "M5 12h14m-5-5 5 5-5 5",
  back: "M19 12H5m5-5-5 5 5 5",
  key: "M14.5 9.5a4.5 4.5 0 1 1-9 0 4.5 4.5 0 0 1 9 0zM13 13l8 8m-3-3 2-2m-4 0 2-2",
  money: "M3 7h18v10H3zm9 7.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z",
  spark: "M13 3 4 14h7l-1 7 9-11h-7z",
  paste: "M9 4h6v3H9zM7 5H6a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V6a1 1 0 0 0-1-1h-1",
  board: "M4 4h4v16H4zM10 4h4v10h-4zM16 4h4v6h-4z",
  mail: "M3 6h18v12H3zm0 0 9 7 9-7",
  link: "M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1",
  warn: "M12 4 2.5 20h19zM12 10v4m0 3v.01",
  chevron: "m7 10 5 5 5-5",
};

export function Icon({ name, size = 18, className = "" }: { name: string; size?: number; className?: string }) {
  return (
    <svg className={`icon ${className}`} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d={PATHS[name] || ""} />
    </svg>
  );
}

export function ScoreRing({ score, target = 95, size = 104, label = "ATS score" }: { score: number; target?: number; size?: number; label?: string }) {
  const r = (size - 12) / 2;
  const c = 2 * Math.PI * r;
  const tone = score >= target ? "var(--ok)" : score >= 80 ? "var(--accent)" : score >= 65 ? "var(--warn)" : "var(--err)";
  return (
    <div className="ring" style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={r} stroke="var(--line)" strokeWidth={8} fill="none" />
        <circle cx={size / 2} cy={size / 2} r={r} stroke={tone} strokeWidth={8} fill="none" strokeLinecap="round"
                strokeDasharray={c} strokeDashoffset={c * (1 - Math.min(score, 100) / 100)}
                transform={`rotate(-90 ${size / 2} ${size / 2})`} style={{ transition: "stroke-dashoffset .8s ease" }} />
      </svg>
      <div className="ring-label">
        <b style={{ fontSize: size * 0.27 }}>{Math.round(score)}</b>
        {size > 70 && <small>{label}</small>}
      </div>
    </div>
  );
}

export function Empty({ icon, title, children }: { icon: string; title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty-icon"><Icon name={icon} size={26} /></div>
      <h3>{title}</h3>
      {children && <p>{children}</p>}
    </div>
  );
}

export function PageHeader({ title, subtitle, children }: { title: string; subtitle?: ReactNode; children?: ReactNode }) {
  return (
    <div className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {children && <div className="page-actions">{children}</div>}
    </div>
  );
}

export function Spinner() {
  return <span className="spinner" />;
}

// ---------------- toasts
type Toast = { id: number; text: string; tone: "ok" | "err" | "info" };
const ToastCtx = createContext<(text: string, tone?: Toast["tone"]) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((text: string, tone: Toast["tone"] = "ok") => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x, { id, text, tone }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), tone === "err" ? 7000 : 3500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts">
        {items.map((t) => (
          <div key={t.id} className={`toast ${t.tone}`}>
            <Icon name={t.tone === "err" ? "x" : "check"} size={16} />
            {t.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export function CountrySelect({ countries, value, onChange }: { countries: CountryInfo[]; value: string; onChange: (k: string) => void }) {
  const groups = [...new Set(countries.map((c) => c.group))];
  return (
    <label className="country-select">
      <select value={value} onChange={(e) => onChange(e.target.value)} aria-label="Country">
        {groups.map((g) => (
          <optgroup key={g} label={g}>
            {countries.filter((c) => c.group === g).map((c) => <option key={c.key} value={c.key}>{c.flag} {c.name}</option>)}
          </optgroup>
        ))}
      </select>
      <Icon name="chevron" size={14} />
    </label>
  );
}

export function WorkModeBadge({ mode }: { mode?: string }) {
  if (mode === "remote") return <span className="badge wm-remote">🏠 Remote</span>;
  if (mode === "hybrid") return <span className="badge wm-hybrid">Hybrid</span>;
  return null;
}

export const SOURCE_LABEL: Record<string, string> = {
  linkedin: "LinkedIn", internshala: "Internshala", bundesagentur: "Arbeitsagentur", arbeitnow: "Arbeitnow",
  adzuna: "Adzuna", manual: "Pasted", studio: "Studio",
};

export function TrackBadge({ track }: { track: Track }) {
  const t = TRACK[track] || TRACK.not_applied;
  return <span className={`track t-${t.tone}`}><i />{t.label}</span>;
}

/** Status picker styled as a badge; stops clicks from bubbling into the card it sits on. */
export function TrackSelect({ value, onChange }: { value: Track; onChange: (t: Track) => void }) {
  const t = TRACK[value] || TRACK.not_applied;
  return (
    <label className={`track track-select t-${t.tone}`} onClick={(e) => e.stopPropagation()}>
      <i />
      <select value={value} onChange={(e) => onChange(e.target.value as Track)} aria-label="Application status">
        {TRACK_ORDER.map((k) => <option key={k} value={k}>{TRACK[k].label}</option>)}
      </select>
      <Icon name="chevron" size={13} />
    </label>
  );
}
