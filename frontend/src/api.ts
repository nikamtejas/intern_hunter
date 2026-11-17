export type Job = {
  id: string;
  source: string;
  title: string;
  company: string;
  location: string;
  country: string;
  url: string;
  posted_at: string | null;
  description: string;
  extra: Record<string, any>;
};

export type Profile = {
  name: string; headline: string; email: string; phone: string; location: string;
  linkedin: string; github: string; portfolio: string;
  links: { label: string; url: string }[];
  summary: string;
  education: { institution: string; degree: string; field: string; location: string; start: string; end: string; grade: string; details: string[] }[];
  experience: { title: string; company: string; location: string; start: string; end: string; bullets: string[] }[];
  projects: { name: string; tech: string[]; link: string; live: string; start: string; end: string; bullets: string[] }[];
  skills: { technical: string[]; tools: string[]; soft: string[] };
  languages: { name: string; level: string }[];
  certifications: { name: string; issuer: string; date: string }[];
  achievements: string[];
  learning: string[];
  extras: { nationality: string; work_permit: string; availability: string; date_of_birth: string };
};

export type AtsResult = {
  score: number;
  breakdown: Record<string, number>;
  matched: Record<string, string[]>;
  missing: Record<string, string[]>;
  word_count: number;
  tips: string[];
};

export type StudioResult = {
  profile: Profile;
  raw_text: string;
  ai: {
    overall: number; verdict: string; strengths: string[];
    issues: { severity: "high" | "medium" | "low"; section: string; problem: string; fix: string }[];
    bullet_rewrites: { original: string; improved: string; why: string }[];
    missing_sections: string[]; keywords_to_consider: string[]; ats_risks: string[];
  };
  local: { checks: { label: string; ok: boolean }[]; passed: number; total: number; word_count: number;
           bullets: number; bullets_with_numbers: number; ats_risks: string[]; style: StyleReview };
};

export type StyleReview = { cliches: string[]; repeated_verbs: string[]; short_bullets: string[]; long_bullets: string[];
  first_person: string[]; filler: string[]; thin_entries: string[]; count: number };

export type Track = "not_applied" | "applied" | "assessment" | "interview" | "offer" | "rejected" | "withdrawn";

export const TRACK: Record<Track, { label: string; tone: string }> = {
  not_applied: { label: "Not applied", tone: "idle" },
  applied: { label: "Applied", tone: "info" },
  assessment: { label: "Assessment", tone: "warn" },
  interview: { label: "Interview", tone: "accent" },
  offer: { label: "Offer", tone: "ok" },
  rejected: { label: "Rejected", tone: "err" },
  withdrawn: { label: "Withdrawn", tone: "idle" },
};
export const TRACK_ORDER = Object.keys(TRACK) as Track[];

export type AppEvent = {
  id: number; app_id: number; kind: "status" | "note"; old: Track | null; new: Track | null; source: "manual" | "email";
  detail: { subject?: string; from?: string; date?: number; snippet?: string; reason?: string; confidence?: number; text?: string };
  created_at: number; job_title?: string; job_company?: string;
};

export type User = { id: number; name: string; locked: number | boolean };
export type Me = { id: number; name: string; locked: boolean };
export type Prep = {
  elevator_pitch: string;
  questions: { type: string; question: string; why_they_ask: string; answer_outline: string; based_on: string }[];
  brush_up: { skill: string; why: string; days: string[]; free_resources: string[] }[];
  questions_to_ask: string[]; red_flags: string[]; generated_at: number;
};
export type FollowUp = { subject: string; body: string; ai: boolean; generated_at: number };
export type Goal = { weekly: number; this_week: number; streak: number; history: { week: string; count: number }[] };
export type CheckItem = { severity: "high" | "medium" | "low"; field: string; message: string };
export type EmailConfig = { address: string; host: string; has_password: boolean; auto: boolean; last_sync: number;
  last_result: { checked?: number; job_related?: number; updated?: { app_id: number; company: string; role: string; from: Track; to: Track; subject: string }[]; error?: string; at?: number } | null };
export type Dashboard = {
  counts: Record<Track, number>; total: number; applied: number; response_rate: number; interview_rate: number;
  avg_score: number | null; applied_this_week: number;
  apps: { id: number; job_title: string; job_company: string; job_location: string; job_country: string; job_url: string;
          job_source: string; status: string; score: number | null; track: Track; applied_at: number | null; created_at: number; notes: string | null }[];
  events: AppEvent[]; email: EmailConfig; goal: Goal;
  followups: { id: number; job_title: string; job_company: string; days: number }[];
};
export type Mission = { kind: string; title: string; sub: string; action: "journey" | "app" | "profile" | "search"; target: number | null; urgent: boolean };
export type Today = {
  missions: Mission[]; goal: Goal; profile_score: number; new_jobs: Job[]; new_total: number;
  watched: { id: number; params: SearchSummary["params"]; last_run: number | null; new_count: number }[];
  counts: Record<Track, number>; resumes: number; ready_not_sent: number; followups_due: number; events: AppEvent[];
};
export type SearchSummary = { id: number; watch?: number; new_count?: number; last_run?: number | null;
  params: { country: string; time_range: string; keywords: string; location: string; work_mode?: string };
  per_source: Record<string, number>; count: number; created_at: number };

export type Application = {
  id: number; job_id: string; status: "queued" | "running" | "done" | "error"; error: string | null;
  score?: number; target?: number; ready?: boolean | null; created_at: number; has_prep?: boolean;
  prep?: Prep | null; followup?: FollowUp | null; cover_letter_present?: boolean; track: Track; applied_at: number | null; notes: string | null;
  events?: AppEvent[];
  job_title?: string; job_company?: string; job_location?: string; job_country?: string; job_url?: string; job_source?: string;
  options: { language: "en" | "de"; cover_letter: boolean };
  resume?: Profile;
  ats?: { ats: AtsResult; keywords: Record<string, any>; style?: StyleReview; gaps: string[]; history: any[]; target: number; reached_target: boolean; note: string | null; description_chars: number; trimmed?: string[]; removed_claims?: string[];
         potential?: { with_missing_skills: number; with_skills_and_numbers: number }; auto_learning?: string[];
         checks?: { ready: boolean; passed: number; total: number;
                    rules: { id: string; core: boolean; ok: boolean; label: string; detail: string }[] } };
  cover_letter?: { subject: string; greeting: string; paragraphs: string[]; closing: string } | null;
  job?: Job;
};

// signed-in state lives in an httpOnly session cookie; when it's missing the app shows the sign-in screen
let onSignedOut: () => void = () => {};
export function setSignedOutHandler(fn: () => void) {
  onSignedOut = fn;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    credentials: "same-origin",
    ...init,
    headers: init?.body instanceof FormData ? undefined : { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (r.status === 401 && !path.startsWith("/api/auth/login")) onSignedOut();
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const j = await r.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {}
    throw new Error(msg);
  }
  return r.json();
}

export type CountryInfo = { key: string; name: string; flag: string; region: "india" | "germany" | "europe"; group: string };
export type Meta = { sources: Record<string, { label: string; countries: string[] }>; countries: CountryInfo[];
  time_ranges: Record<string, string>; work_modes: Record<string, string>; track_stages: string[] };
let metaCache: Promise<Meta> | null = null;

export const api = {
  meta: () => (metaCache ??= req<Meta>("/api/meta")),
  settings: () => req<Record<string, any>>("/api/settings"),
  saveSettings: (s: Record<string, string>) => req<Record<string, any>>("/api/settings", { method: "PUT", body: JSON.stringify(s) }),
  search: (b: { country: string; time_range: string; sources: string[]; keywords: string; location: string; work_mode: string }) =>
    req<{ jobs: Job[]; per_source: Record<string, number>; warnings: string[]; search_id: number }>("/api/search", { method: "POST", body: JSON.stringify(b) }),
  searches: () => req<SearchSummary[]>("/api/searches"),
  savedSearch: (id: number) => req<{ jobs: Job[]; per_source: Record<string, number>; warnings: string[]; search_id: number;
                                     params: SearchSummary["params"] }>(`/api/searches/${id}`),
  users: () => req<User[]>("/api/users"),
  me: () => req<Me>("/api/auth/me"),
  login: (user_id: number, password: string) => req<Me>("/api/auth/login", { method: "POST", body: JSON.stringify({ user_id, password }) }),
  logout: () => req("/api/auth/logout", { method: "POST" }),
  setPassword: (password: string, current = "") => req<Me>("/api/auth/password", { method: "PUT", body: JSON.stringify({ password, current }) }),
  createUser: (name: string, password: string) => req<Me>("/api/users", { method: "POST", body: JSON.stringify({ name, password }) }),
  renameMe: (name: string) => req<Me>("/api/users/me", { method: "PUT", body: JSON.stringify({ name }) }),
  deleteMe: (user_id: number, password: string) => req("/api/users/me", { method: "DELETE", body: JSON.stringify({ user_id, password }) }),
  prep: (id: number) => req<Prep>(`/api/applications/${id}/prep`, { method: "POST" }),
  followup: (id: number) => req<FollowUp>(`/api/applications/${id}/followup`, { method: "POST" }),
  today: () => req<Today>("/api/today"),
  todaySeen: () => req("/api/today/seen", { method: "POST" }),
  watchSearch: (id: number, watch: boolean) => req<SearchSummary[]>(`/api/searches/${id}/watch`, { method: "PUT", body: JSON.stringify({ watch }) }),
  refreshSearch: (id: number) => req<{ new: number }>(`/api/searches/${id}/refresh`, { method: "POST" }),
  setGoal: (weekly: number) => req<Goal>("/api/goal", { method: "PUT", body: JSON.stringify({ weekly }) }),
  checkProfile: (country = "") => req<{ score: number; items: CheckItem[] }>(`/api/profile/check?country=${country}`),
  setTrack: (id: number, b: { track?: Track; notes?: string }) =>
    req<Application>(`/api/applications/${id}/track`, { method: "PATCH", body: JSON.stringify(b) }).then((a) => {
      if (b.track === "offer") celebrate();  // you earned it
      return a;
    }),
  dashboard: () => req<Dashboard>("/api/dashboard"),
  saveEmail: (b: { address: string; app_password: string; host: string; auto: boolean }) =>
    req<EmailConfig>("/api/email", { method: "PUT", body: JSON.stringify(b) }),
  disconnectEmail: () => req<EmailConfig>("/api/email", { method: "DELETE" }),
  syncEmail: () => req<NonNullable<EmailConfig["last_result"]>>("/api/email/sync", { method: "POST" }),
  job: (id: string, full = false) => req<Job>(`/api/jobs/${id}?full=${full}`),
  manualJob: (b: any) => req<Job>("/api/jobs/manual", { method: "POST", body: JSON.stringify(b) }),
  profile: () => req<Profile>("/api/profile"),
  saveProfile: (p: Profile) => req<Profile>("/api/profile", { method: "PUT", body: JSON.stringify(p) }),
  uploadResume: (f: File) => {
    const fd = new FormData();
    fd.append("file", f);
    return req<Profile>("/api/profile/upload", { method: "POST", body: fd });
  },
  addSkills: (skills: string[], category = "technical") =>
    req<Profile>("/api/profile/skills", { method: "POST", body: JSON.stringify({ skills, category }) }),
  createApps: (job_ids: string[], language: string, cover_letter: boolean) =>
    req<{ created: number[] }>("/api/applications", { method: "POST", body: JSON.stringify({ job_ids, language, cover_letter }) }),
  studioAnalyze: (file: File | null, target_role: string, country: string) => {
    const fd = new FormData();
    if (file) fd.append("file", file);
    fd.append("target_role", target_role);
    fd.append("country", country);
    return req<StudioResult>("/api/studio/analyze", { method: "POST", body: fd });
  },
  studioImprove: (b: { target_role: string; country: string; language: string; role_description: string; cover_letter: boolean;
                       profile?: Profile | null; save_as_profile: boolean; raw_text?: string }) =>
    req<{ created: number[] }>("/api/studio/improve", { method: "POST", body: JSON.stringify(b) }),
  apps: () => req<Application[]>("/api/applications"),
  app: (id: number) => req<Application>(`/api/applications/${id}`),
  deleteApp: (id: number) => req(`/api/applications/${id}`, { method: "DELETE" }),
  regenerate: (id: number) => req(`/api/applications/${id}/regenerate`, { method: "POST" }),
  editResume: (id: number, r: Profile) => req<Application>(`/api/applications/${id}/resume`, { method: "PUT", body: JSON.stringify(r) }),
};

export function timeAgo(iso: string | null): string {
  if (!iso) return "—";
  const d = (Date.now() - new Date(iso).getTime()) / 1000;
  if (d < 3600) return "just now";
  if (d < 86400) return `${Math.floor(d / 3600)}h ago`;
  const days = Math.floor(d / 86400);
  return days === 1 ? "1 day ago" : `${days} days ago`;
}

export function dateShort(ts: number | null | undefined): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** A short burst of confetti (offers, weekly goals). Pure canvas, removed after ~2.5 s; skipped if the user prefers less motion. */
export function celebrate() {
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
  const c = document.createElement("canvas");
  c.className = "confetti";
  c.width = window.innerWidth;
  c.height = window.innerHeight;
  document.body.appendChild(c);
  const ctx = c.getContext("2d")!;
  const colors = ["#4f46e5", "#7c3aed", "#16a34a", "#f59e0b", "#ec4899", "#0ea5e9"];
  const parts = Array.from({ length: 160 }, () => ({
    x: c.width / 2 + (Math.random() - 0.5) * 200, y: c.height / 3, r: 4 + Math.random() * 5,
    vx: (Math.random() - 0.5) * 14, vy: -Math.random() * 14 - 4, c: colors[Math.floor(Math.random() * colors.length)], a: Math.random() * 6,
  }));
  const t0 = performance.now();
  const tick = (t: number) => {
    ctx.clearRect(0, 0, c.width, c.height);
    for (const p of parts) {
      p.vy += 0.38; p.x += p.vx; p.y += p.vy; p.a += 0.15;
      ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.a); ctx.fillStyle = p.c; ctx.fillRect(-p.r, -p.r / 2, p.r * 2, p.r); ctx.restore();
    }
    if (t - t0 < 2600) requestAnimationFrame(tick); else c.remove();
  };
  requestAnimationFrame(tick);
}

export type Theme = "system" | "light" | "dark";
export function applyTheme(t: Theme) {
  if (t === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = t;
  try { localStorage.setItem("ih_theme", t); } catch {}
}
export function savedTheme(): Theme {
  try { return (localStorage.getItem("ih_theme") as Theme) || "system"; } catch { return "system"; }
}
