"""Intern Hunter API — job scraping + ATS resume builder + application tracker."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import AfterValidator, BaseModel, Field  # noqa: E402

from . import db, scrapers  # noqa: E402
from .scrapers.base import COUNTRIES, region_of  # noqa: E402
from .services import ats, completeness, cover_letter, mailsync, prep, quality, render, resume_parser, studio, tailor  # noqa: E402
from .services.groq_client import GroqError  # noqa: E402
from .services.profile_schema import EMPTY_PROFILE, flatten_text, normalize  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("intern-hunter")

DEFAULT_TARGET = "98"
DEFAULT_ROUNDS = "4"

queue: asyncio.Queue[int]  # created at startup, bound to the running event loop


async def worker():
    """Process resume generations one at a time (keeps Groq rate limits happy)."""
    while True:
        app_id = await queue.get()
        try:
            await process_application(app_id)
        except Exception as e:  # pragma: no cover
            log.exception("application %s failed", app_id)
            db.update_application(app_id, status="error", error=str(e))
        finally:
            queue.task_done()


@asynccontextmanager
async def lifespan(_: FastAPI):
    global queue
    queue = asyncio.Queue()
    db.init()
    # resume anything left queued from a previous run
    for a in db.query("SELECT id FROM applications WHERE status IN ('queued','running')"):
        queue.put_nowait(a["id"])
    tasks = [asyncio.create_task(worker()), asyncio.create_task(mailsync.auto_sync_loop())]
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="Intern Hunter", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


COOKIE = "ih_session"
_failed: dict[int, list[float]] = {}  # user_id -> recent failed sign-in times


def current_user(request: Request) -> int:
    """The signed-in profile (session cookie). A profile without a password (older installs) stays open until its
    owner sets one; password-protected profiles are only reachable with a valid session."""
    uid = db.session_user(request.cookies.get(COOKIE))
    if uid:
        return uid
    raw = request.headers.get("x-user-id") or request.query_params.get("u")
    target = int(raw) if raw and raw.isdigit() and db.user_exists(int(raw)) else (None if raw else db.first_user_id())
    if target and not db.has_password(target):
        return target
    raise HTTPException(401, "Sign in to your profile")


def _set_session(response: Response, uid: int) -> None:
    response.set_cookie(COOKIE, db.create_session(uid), max_age=db.SESSION_DAYS * 86400, httponly=True, samesite="lax")


def owned_app(app_id: int, uid: int) -> dict:
    a = db.get_application(app_id)
    if not a or (a.get("user_id") or 1) != uid:
        raise HTTPException(404, "Application not found for this profile")
    return a


# ------------------------------------------------------------------ meta / settings
SETTING_KEYS = ["GROQ_API_KEY", "GROQ_MODEL", "GROQ_FALLBACK_MODEL", "AUTO_LEARNING", "ADZUNA_APP_ID", "ADZUNA_APP_KEY", "ATS_TARGET", "ATS_MAX_ROUNDS",
                "LINKEDIN_DELAY", "LINKEDIN_MAX_PAGES"]
SECRET_KEYS = {"GROQ_API_KEY", "ADZUNA_APP_KEY"}


@app.get("/api/meta")
def meta():
    countries = [{"key": k, "name": v["name"], "flag": v["flag"], "region": v["region"],
                  "group": "India" if v["region"] == "india" else "Europe"} for k, v in COUNTRIES.items()]
    return {"sources": scrapers.SOURCES, "countries": countries,
            "work_modes": {"any": "Any", "remote": "Remote / WFH", "hybrid": "Hybrid", "onsite": "On-site"},
            "time_ranges": {"24h": "Last 24 hours", "week": "Past week", "month": "Past month"},
            "track_stages": db.TRACK_STAGES}


@app.get("/api/settings")
def get_settings(uid: int = Depends(current_user)):
    out = {}
    for k in SETTING_KEYS:
        v = db.get_setting(k) or ""
        out[k] = ("•" * 8 + v[-4:]) if (k in SECRET_KEYS and v) else v
    out["ATS_TARGET"] = out["ATS_TARGET"] or DEFAULT_TARGET
    out["ATS_MAX_ROUNDS"] = out["ATS_MAX_ROUNDS"] or DEFAULT_ROUNDS
    out["AUTO_LEARNING"] = out["AUTO_LEARNING"] or "1"
    out["groq_configured"] = bool(db.get_setting("GROQ_API_KEY"))
    return out


@app.put("/api/settings")
def put_settings(body: dict, uid: int = Depends(current_user)):
    for k, v in body.items():
        if k in SETTING_KEYS and isinstance(v, str) and not v.startswith("•"):
            db.set_setting(k, v.strip())
    return get_settings(uid)


# ------------------------------------------------------------------ profiles (people using the app)
class UserBody(BaseModel):
    name: str


class NewUser(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=6, max_length=200)


class LoginBody(BaseModel):
    user_id: int
    password: str = ""


class PasswordBody(BaseModel):
    password: str = Field(min_length=6, max_length=200)
    current: str = ""


def _me(uid: int) -> dict:
    u = next(x for x in db.list_users() if x["id"] == uid)
    return {"id": uid, "name": u["name"], "locked": bool(u["locked"])}


@app.get("/api/users")
def list_users():
    """Names for the sign-in screen; nothing personal."""
    return [{k: u[k] for k in ("id", "name", "locked")} for u in db.list_users()]


@app.get("/api/auth/me")
def me(uid: int = Depends(current_user)):
    return _me(uid)


@app.post("/api/auth/login")
def login(body: LoginBody, response: Response):
    if not db.user_exists(body.user_id):
        raise HTTPException(404, "Profile not found")
    recent = [t for t in _failed.get(body.user_id, []) if t > time.time() - 60]
    if len(recent) >= 5:
        raise HTTPException(429, "Too many wrong passwords — wait a minute and try again.")
    if db.has_password(body.user_id) and not db.check_password(body.user_id, body.password):
        _failed[body.user_id] = recent + [time.time()]
        raise HTTPException(401, "Wrong password")
    _failed.pop(body.user_id, None)
    _set_session(response, body.user_id)
    return _me(body.user_id)


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    db.delete_session(request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.put("/api/auth/password")
def set_password(body: PasswordBody, response: Response, uid: int = Depends(current_user)):
    if db.has_password(uid) and not db.check_password(uid, body.current):
        raise HTTPException(401, "Current password is wrong")
    db.set_password(uid, body.password)
    _set_session(response, uid)
    return _me(uid)


@app.post("/api/users")
def create_user(body: NewUser, response: Response):
    """New profiles always get a password, so each person's resumes, tracker and inbox link stay private."""
    uid = db.create_user(body.name)
    db.set_password(uid, body.password)
    _set_session(response, uid)
    return _me(uid)


@app.put("/api/users/me")
def rename_me(body: UserBody, uid: int = Depends(current_user)):
    db.rename_user(uid, body.name)
    return _me(uid)


@app.delete("/api/users/me")
def delete_me(body: LoginBody, request: Request, response: Response, uid: int = Depends(current_user)):
    if body.user_id != uid or (db.has_password(uid) and not db.check_password(uid, body.password)):
        raise HTTPException(401, "Confirm with your password to delete this profile")
    if len(db.list_users()) <= 1:
        raise HTTPException(400, "You can't delete the only profile.")
    db.delete_user(uid)
    response.delete_cookie(COOKIE)
    return {"ok": True}


# ------------------------------------------------------------------ jobs
def _country(v: str) -> str:
    if v not in COUNTRIES:
        raise ValueError(f"unknown country {v!r}")
    return v


CountryKey = Annotated[str, AfterValidator(_country)]


class SearchBody(BaseModel):
    country: CountryKey
    work_mode: Literal["any", "remote", "hybrid", "onsite"] = "any"
    time_range: Literal["24h", "week", "month"] = "week"
    sources: list[str] = Field(default_factory=lambda: list(scrapers.SOURCES))
    keywords: str = ""
    location: str = ""


def _fit(jobs: list[dict], uid: int) -> None:
    """Quick, free match estimate per job: share of the skills named in the posting (or its title, when the card has no
    description yet) that the profile already shows. No AI call — it's for deciding where to spend one."""
    prof = db.get_profile(uid)
    if not prof:
        return
    pl = (flatten_text(normalize({**prof, "learning": []})) + "\n" + db.get_raw_text(uid)).lower()
    for j in jobs:
        kw = ats.local_keywords(f"{j.get('title', '')}\n{j.get('description') or ''}")
        uniq: dict[str, str] = {}
        for t in kw["hard_skills"] + kw["soft_skills"]:
            uniq.setdefault(ats.norm(t), t)  # "mysql" and "sql" are one skill
        terms = list(uniq.values())
        if len(terms) >= 2:
            have = sum(1 for t in terms if ats.has_evidence(pl, t))
            j.setdefault("extra", {})["fit"] = {"pct": round(100 * have / len(terms)), "terms": len(terms),
                                                "missing": [t for t in terms if not ats.has_evidence(pl, t)][:6]}


def _mark_mine(jobs: list[dict], uid: int) -> None:
    """Flag jobs this profile already made a resume for / applied to."""
    _fit(jobs, uid)
    mine = {a["job_id"]: a for a in db.list_applications(uid)}
    for j in jobs:
        a = mine.get(j["id"])
        if a:
            j.setdefault("extra", {})["mine"] = {"app_id": a["id"], "track": a.get("track") or "not_applied"}


@app.post("/api/search")
async def search(body: SearchBody, uid: int = Depends(current_user)):
    res = await scrapers.search_all(body.country, body.time_range, body.sources, body.keywords.strip(), body.location.strip(),
                                    body.work_mode)
    res["search_id"] = db.save_search(uid, body.model_dump(), [j["id"] for j in res["jobs"]], res["per_source"], res["warnings"])
    _mark_mine(res["jobs"], uid)
    return res


@app.get("/api/searches")
def list_searches(uid: int = Depends(current_user)):
    return db.list_searches(uid)


@app.get("/api/searches/{search_id}")
def get_search(search_id: int, uid: int = Depends(current_user)):
    s = db.get_search(uid, search_id)
    if not s:
        raise HTTPException(404, "Search not found")
    jobs = db.get_jobs(s["job_ids"])
    _mark_mine(jobs, uid)
    return {"jobs": jobs, "per_source": s["per_source"], "warnings": s["warnings"], "search_id": s["id"],
            "params": s["params"], "created_at": s["created_at"]}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str, full: bool = False, uid: int = Depends(current_user)):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if full:
        job["description"] = await scrapers.ensure_description(job)
    return job


class ManualJob(BaseModel):
    title: str
    company: str = ""
    location: str = ""
    country: CountryKey
    url: str = ""
    description: str


@app.post("/api/jobs/manual")
def add_manual_job(body: ManualJob, uid: int = Depends(current_user)):
    """Paste any posting (from Naukri, StepStone, company sites...) and build a resume for it."""
    from .scrapers.base import Job
    import hashlib

    j = Job(source="manual", title=body.title, company=body.company, location=body.location, country=body.country,
            url=body.url, description=body.description,
            external_id=hashlib.sha1((body.title + body.company + body.description[:200]).encode()).hexdigest()[:12])
    db.upsert_job(j.to_dict())
    return j.to_dict()


# ------------------------------------------------------------------ profile
@app.get("/api/profile")
def get_profile(uid: int = Depends(current_user)):
    return normalize(db.get_profile(uid)) if db.get_profile(uid) else EMPTY_PROFILE


@app.put("/api/profile")
def put_profile(body: dict, uid: int = Depends(current_user)):
    p = normalize(body)
    db.save_profile(p, uid)
    return p


@app.get("/api/profile/check")
def check_profile(country: str = "", uid: int = Depends(current_user)):
    return completeness.check(db.get_profile(uid) or {}, region_of(country) if country else "")


@app.post("/api/profile/upload")
async def upload_resume(file: UploadFile = File(...), uid: int = Depends(current_user)):
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "File too large (max 10 MB)")
    try:
        profile, raw = await resume_parser.parse_resume(file.filename or "resume", data)
    except GroqError as e:
        raise HTTPException(400, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.set_raw_text(uid, raw)
    return profile  # not saved until the user reviews and clicks Save


class AddSkills(BaseModel):
    skills: list[str]
    category: Literal["technical", "tools", "soft", "learning"] = "technical"


@app.post("/api/profile/skills")
def add_skills(body: AddSkills, uid: int = Depends(current_user)):
    p = normalize(db.get_profile(uid))
    existing = {ats.norm(s) for k in ("technical", "tools", "soft") for s in p["skills"][k]} | {ats.norm(s) for s in p["learning"]}
    target = p["learning"] if body.category == "learning" else p["skills"][body.category]
    for s in body.skills:
        if s.strip() and ats.norm(s) not in existing:
            target.append(s.strip())
    db.save_profile(p, uid)
    return p


# ------------------------------------------------------------------ applications (resume + cover letter)
class CreateApps(BaseModel):
    job_ids: list[str]
    language: Literal["en", "de"] = "en"
    cover_letter: bool = True
    target: float | None = None


@app.post("/api/applications")
async def create_applications(body: CreateApps, uid: int = Depends(current_user)):
    if not db.get_profile(uid):
        raise HTTPException(400, "Fill in your profile first (upload your resume or use the form).")
    if not db.get_setting("GROQ_API_KEY"):
        raise HTTPException(400, "Add your Groq API key on the Settings page first.")
    ids = []
    for jid in body.job_ids:
        if not db.get_job(jid):
            continue
        aid = db.create_application(jid, body.model_dump(exclude={"job_ids"}), uid)
        ids.append(aid)
        queue.put_nowait(aid)
    return {"created": ids}


async def process_application(app_id: int):
    a = db.get_application(app_id)
    if not a:
        return
    uid = a.get("user_id") or 1
    job = db.get_job(a["job_id"])
    opts = a["options"] or {}
    profile = normalize(opts.get("profile") or db.get_profile(uid))
    country = region_of(job.get("country") or "india")  # india | germany (DACH) | europe: resume conventions
    lang = opts.get("language", "en")
    target = float(opts.get("target") or db.get_setting("ATS_TARGET", DEFAULT_TARGET) or DEFAULT_TARGET)
    rounds = int(db.get_setting("ATS_MAX_ROUNDS", DEFAULT_ROUNDS) or DEFAULT_ROUNDS)

    db.update_application(app_id, status="running", error="Fetching full job description")
    job["description"] = await scrapers.ensure_description(job)
    if len(job["description"]) < 80:
        log.warning("Job %s has a very short description; tailoring will rely on the title.", job["id"])

    def progress(msg):
        db.update_application(app_id, error=msg)

    # analyse each posting once; regenerations then score against the same keyword list
    import hashlib
    desc_hash = hashlib.sha1(job["description"].encode()).hexdigest()[:16]
    cached = (job.get("extra") or {}).get("jd_analysis")
    jd = cached["data"] if cached and cached.get("hash") == desc_hash else None
    if jd:  # analyses saved before a filter improvement get the same clean-up
        jd = {k: ([x for x in v if not tailor.DESCRIPTOR.search(str(x))] if isinstance(v, list) else v) for k, v in jd.items()}
    try:
        if jd is None:
            progress("Analysing job description")
            jd = await tailor.analyze_job(job.get("title", ""), job["description"] or job.get("title", ""))
            db.set_job_extra(job["id"], {**(job.get("extra") or {}), "jd_analysis": {"hash": desc_hash, "data": jd}})
        result = await tailor.build(profile, job, country, lang, target, rounds,
                                    raw_resume_text=db.get_raw_text(uid), on_progress=progress, jd=jd,
                                    auto_learning=(db.get_setting("AUTO_LEARNING", "1") or "1") == "1")
        cl = None
        if opts.get("cover_letter"):
            progress("Writing cover letter")
            cl = await cover_letter.generate(profile, job, country, lang, jd=result["keywords"])
    except GroqError as e:
        db.update_application(app_id, status="error", error=str(e))
        return
    ats_payload = {k: result[k] for k in ("ats", "keywords", "style", "gaps", "history", "target", "reached_target", "note", "trimmed", "removed_claims", "potential",
                                          "auto_learning", "checks", "ragged_bullets")}
    ats_payload["description_chars"] = len(job["description"])
    db.update_application(app_id, status="done", error=None, resume=result["resume"], ats=ats_payload,
                          cover_letter=json.dumps(cl) if cl else None)


@app.get("/api/applications")
def list_apps(uid: int = Depends(current_user)):
    out = []
    for a in db.list_applications(uid):
        a.pop("resume", None)
        a.pop("cover_letter", None)
        a["has_prep"] = bool(a.pop("prep", None))
        a.pop("followup", None)
        if a.get("ats"):
            a["score"] = a["ats"]["ats"]["score"]
            a["ready"] = (a["ats"].get("checks") or {}).get("ready")
            a["target"] = a["ats"].get("target")
            a["ats"] = None
        a["track"] = a.get("track") or "not_applied"
        out.append(a)
    return out


@app.get("/api/applications/{app_id}")
def get_app(app_id: int, uid: int = Depends(current_user)):
    a = owned_app(app_id, uid)
    a["job"] = db.get_job(a["job_id"])
    a["cover_letter"] = json.loads(a["cover_letter"]) if a.get("cover_letter") else None
    a["track"] = a.get("track") or "not_applied"
    a["events"] = db.list_events(uid, app_id)
    return a


@app.delete("/api/applications/{app_id}")
def del_app(app_id: int, uid: int = Depends(current_user)):
    owned_app(app_id, uid)
    db.delete_application(app_id)
    return {"ok": True}


@app.post("/api/applications/{app_id}/regenerate")
def regenerate(app_id: int, uid: int = Depends(current_user)):
    owned_app(app_id, uid)
    db.update_application(app_id, status="queued", error=None)
    queue.put_nowait(app_id)
    return {"ok": True}


class TrackBody(BaseModel):
    track: Literal["not_applied", "applied", "assessment", "interview", "offer", "rejected", "withdrawn"] | None = None
    notes: str | None = None


@app.patch("/api/applications/{app_id}/track")
def set_track(app_id: int, body: TrackBody, uid: int = Depends(current_user)):
    a = owned_app(app_id, uid)
    if body.track:
        db.set_track(app_id, body.track, source="manual")
    if body.notes is not None and body.notes != (a.get("notes") or ""):
        db.update_application(app_id, notes=body.notes)
        db.add_event(app_id, uid, "note", None, None, "manual", {"text": body.notes[:500]})
    return get_app(app_id, uid)


@app.post("/api/applications/{app_id}/prep")
async def make_prep(app_id: int, uid: int = Depends(current_user)):
    """Interview prep for this job: likely questions, answer outlines from your own resume, a 7-day brush-up plan."""
    a = owned_app(app_id, uid)
    if not a.get("resume"):
        raise HTTPException(400, "Generate the resume first.")
    job = db.get_job(a["job_id"]) or {}
    job["description"] = await scrapers.ensure_description(job)
    try:
        out = await prep.interview_prep(a, job)
    except GroqError as e:
        raise HTTPException(400, str(e))
    db.update_application(app_id, prep=out)
    db.add_event(app_id, uid, "prep", None, None, "manual", {"text": "Interview prep generated"})
    return out


@app.post("/api/applications/{app_id}/followup")
async def make_followup(app_id: int, uid: int = Depends(current_user)):
    a = owned_app(app_id, uid)
    out = await prep.followup(a, db.get_job(a["job_id"]) or {})
    db.update_application(app_id, followup=out)
    return out


@app.put("/api/applications/{app_id}/resume")
def edit_resume(app_id: int, body: dict, uid: int = Depends(current_user)):
    """Save manual edits, fit to one page and re-score instantly (no AI call)."""
    a = owned_app(app_id, uid)
    if not a.get("ats"):
        raise HTTPException(404)
    job = db.get_job(a["job_id"])
    kw = a["ats"]["keywords"]
    terms = [t for k in ("hard_skills", "tools", "other_keywords", "languages", "soft_skills") for t in kw.get(k) or []]
    resume, _, trimmed = render.fit_one_page(normalize(body), region_of(job.get("country", "india")),
                                             (a.get("options") or {}).get("language", "en"), terms)
    a["ats"]["ats"] = ats.score(resume, kw, job.get("title", ""))
    a["ats"]["trimmed"] = trimmed
    a["ats"]["checks"] = quality.check(resume, a["ats"]["ats"], region_of(job.get("country", "india")),
                                       (a.get("options") or {}).get("language", "en"))
    db.update_application(app_id, resume=resume, ats=a["ats"])
    return get_app(app_id, uid)


def _fname(a: dict, kind: str, ext: str) -> str:
    job = db.get_job(a["job_id"]) or {}
    name = (a.get("resume") or {}).get("name") or "Resume"
    base = f"{name}_{kind}_{job.get('company','')}".strip("_")
    return re.sub(r"[^A-Za-z0-9_-]+", "_", base)[:80] + "." + ext


@app.get("/api/applications/{app_id}/resume.{fmt}")
def download_resume(app_id: int, fmt: Literal["pdf", "docx"], uid: int = Depends(current_user)):
    a = owned_app(app_id, uid)
    if not a.get("resume"):
        raise HTTPException(404)
    job = db.get_job(a["job_id"]) or {}
    lang = (a.get("options") or {}).get("language", "en")
    country = region_of(job.get("country", "india"))
    data = render.resume_pdf(a["resume"], country, lang) if fmt == "pdf" else render.resume_docx(a["resume"], country, lang)
    mt = "application/pdf" if fmt == "pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    disp = "inline" if fmt == "pdf" else "attachment"
    return Response(data, media_type=mt, headers={"Content-Disposition": f'{disp}; filename="{_fname(a, "Resume", fmt)}"'})


@app.get("/api/applications/{app_id}/cover.{fmt}")
def download_cover(app_id: int, fmt: Literal["pdf", "docx"], uid: int = Depends(current_user)):
    a = owned_app(app_id, uid)
    if not a.get("cover_letter"):
        raise HTTPException(404, "No cover letter for this application")
    cl = json.loads(a["cover_letter"])
    lang = (a.get("options") or {}).get("language", "en")
    profile = normalize(a.get("resume") or db.get_profile(a.get("user_id") or 1))
    fn = render.cover_pdf if fmt == "pdf" else render.cover_docx
    data = fn(cl, profile, db.get_job(a["job_id"]) or {}, lang)
    mt = "application/pdf" if fmt == "pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return Response(data, media_type=mt, headers={"Content-Disposition": f'attachment; filename="{_fname(a, "CoverLetter", fmt)}"'})


# ------------------------------------------------------------------ tracker dashboard
class GoalBody(BaseModel):
    weekly: int = Field(ge=1, le=100)


@app.put("/api/goal")
def set_goal(body: GoalBody, uid: int = Depends(current_user)):
    db.set_user_setting(uid, "WEEKLY_GOAL", str(body.weekly))
    return _goal(list_apps(uid), uid)


def _goal(apps: list[dict], uid: int) -> dict:
    """Applications sent per ISO week vs. the weekly goal, and the streak of weeks the goal was met."""
    import datetime as dt

    weekly = int(db.get_user_setting(uid, "WEEKLY_GOAL", "5") or 5)
    per_week: dict[tuple[int, int], int] = {}
    for a in apps:
        if a.get("applied_at"):
            k = dt.datetime.fromtimestamp(a["applied_at"], dt.timezone.utc).isocalendar()[:2]
            per_week[k] = per_week.get(k, 0) + 1
    today = dt.date.today()
    this = today.isocalendar()[:2]
    streak, d = 0, today - dt.timedelta(days=7)  # the current week still counts as "in progress"
    while per_week.get(d.isocalendar()[:2], 0) >= weekly:
        streak += 1
        d -= dt.timedelta(days=7)
    if per_week.get(this, 0) >= weekly:
        streak += 1
    last8 = []
    for i in range(7, -1, -1):
        k = (today - dt.timedelta(days=7 * i)).isocalendar()[:2]
        last8.append({"week": f"{k[0]}-W{k[1]:02d}", "count": per_week.get(k, 0)})
    return {"weekly": weekly, "this_week": per_week.get(this, 0), "streak": streak, "history": last8}


def _needs_followup(apps: list[dict], uid: int) -> list[dict]:
    """Applied 7+ days ago and nothing has happened since."""
    last_event = {}
    for e in db.list_events(uid, limit=1000):
        last_event[e["app_id"]] = max(last_event.get(e["app_id"], 0), e["created_at"])
    out = []
    for a in apps:
        quiet_since = max(a.get("applied_at") or 0, last_event.get(a["id"], 0))
        if a["track"] == "applied" and a.get("applied_at") and time.time() - quiet_since > 7 * 86400:
            out.append({"id": a["id"], "job_title": a.get("job_title"), "job_company": a.get("job_company"),
                        "days": int((time.time() - a["applied_at"]) / 86400)})
    return sorted(out, key=lambda x: -x["days"])


@app.get("/api/dashboard")
def dashboard(uid: int = Depends(current_user)):
    apps = list_apps(uid)
    counts = {s: 0 for s in db.TRACK_STAGES}
    for a in apps:
        counts[a["track"]] = counts.get(a["track"], 0) + 1
    sent = sum(v for k, v in counts.items() if k != "not_applied")
    responded = counts["assessment"] + counts["interview"] + counts["offer"] + counts["rejected"]
    scores = [a["score"] for a in apps if a.get("score") is not None]
    week_ago = time.time() - 7 * 86400
    return {
        "counts": counts,
        "total": len(apps),
        "applied": sent,
        "response_rate": round(100 * responded / sent) if sent else 0,
        "interview_rate": round(100 * (counts["interview"] + counts["offer"]) / sent) if sent else 0,
        "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
        "applied_this_week": sum(1 for a in apps if (a.get("applied_at") or 0) >= week_ago),
        "apps": [{k: a.get(k) for k in ("id", "job_id", "job_title", "job_company", "job_location", "job_country", "job_url",
                                         "job_source", "status", "score", "track", "applied_at", "created_at", "updated_at", "notes")}
                 for a in apps],
        "events": db.list_events(uid, limit=30),
        "email": mailsync.config(uid),
        "goal": _goal(apps, uid),
        "followups": _needs_followup(apps, uid),
    }


# ------------------------------------------------------------------ email (auto status updates)
class EmailBody(BaseModel):
    address: str = ""
    app_password: str = ""
    host: str = ""
    auto: bool = True


@app.get("/api/email")
def get_email(uid: int = Depends(current_user)):
    return mailsync.config(uid)


@app.put("/api/email")
async def put_email(body: EmailBody, uid: int = Depends(current_user)):
    host = body.host.strip() or mailsync.IMAP_DEFAULT
    pw = body.app_password.replace(" ", "") or db.get_user_setting(uid, "EMAIL_APP_PASSWORD")
    if body.address and pw:
        try:
            await asyncio.to_thread(mailsync.test_login, host, body.address.strip(), pw)
        except Exception as e:
            raise HTTPException(400, f"Could not log in to {host}: {e}. Use an app password (not your normal password).")
    db.set_user_setting(uid, "EMAIL_ADDRESS", body.address.strip())
    db.set_user_setting(uid, "EMAIL_IMAP_HOST", host)
    db.set_user_setting(uid, "EMAIL_AUTO_SYNC", "1" if body.auto else "0")
    if body.app_password:
        db.set_user_setting(uid, "EMAIL_APP_PASSWORD", pw)
    return mailsync.config(uid)


@app.delete("/api/email")
def disconnect_email(uid: int = Depends(current_user)):
    for k in ("EMAIL_ADDRESS", "EMAIL_APP_PASSWORD", "EMAIL_LAST_SYNC", "EMAIL_LAST_RESULT"):
        db.set_user_setting(uid, k, "")
    return mailsync.config(uid)


@app.post("/api/email/sync")
async def sync_email(uid: int = Depends(current_user)):
    try:
        return await mailsync.sync(uid)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ------------------------------------------------------------------ Resume Studio
@app.post("/api/studio/analyze")
async def studio_analyze(file: UploadFile | None = File(None), target_role: str = Form(""), country: str = Form("india"),
                         uid: int = Depends(current_user)):
    """Analyse a sample resume (uploaded file, or the saved profile) and return a recruiter-style critique."""
    if file is not None:
        data = await file.read()
        try:
            profile, raw = await resume_parser.parse_resume(file.filename or "resume", data)
        except (GroqError, ValueError) as e:
            raise HTTPException(400, str(e))
    else:
        profile, raw = normalize(db.get_profile(uid)), ""
        if not profile.get("name") and not profile.get("experience") and not profile.get("projects"):
            raise HTTPException(400, "Upload a resume or save your profile first.")
    try:
        critique = await studio.analyze(profile, raw, target_role, region_of(country))
    except GroqError as e:
        raise HTTPException(400, str(e))
    return {"profile": profile, "raw_text": raw[:30000], **critique}


class ImproveBody(BaseModel):
    target_role: str
    country: CountryKey = "india"
    language: Literal["en", "de"] = "en"
    role_description: str = ""
    cover_letter: bool = False
    profile: dict | None = None  # from /analyze; if omitted, the saved profile is used
    save_as_profile: bool = False
    raw_text: str = ""


@app.post("/api/studio/improve")
def studio_improve(body: ImproveBody, uid: int = Depends(current_user)):
    if not db.get_setting("GROQ_API_KEY"):
        raise HTTPException(400, "Add your Groq API key on the Settings page first.")
    profile = normalize(body.profile) if body.profile else db.get_profile(uid)
    if not profile:
        raise HTTPException(400, "No resume to improve. Upload one first.")
    if body.save_as_profile:
        db.save_profile(normalize(profile), uid)
        if body.raw_text:
            db.set_raw_text(uid, body.raw_text)
    import hashlib
    from .scrapers.base import Job

    desc = body.role_description.strip() or f"(No posting provided — general resume for the role: {body.target_role})"
    j = Job(source="studio", title=body.target_role, company="", location=COUNTRIES[body.country]["name"],
            country=body.country, url="", description=desc,
            external_id=hashlib.sha1(f"{body.target_role}{desc[:200]}{time.time()}".encode()).hexdigest()[:12])
    db.upsert_job(j.to_dict())
    opts = {"language": body.language, "cover_letter": body.cover_letter, "profile": normalize(profile)}
    aid = db.create_application(j.id, opts, uid)
    queue.put_nowait(aid)
    return {"created": [aid], "job_id": j.id}


# ------------------------------------------------------------------ serve built frontend (production mode)
DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = DIST / path
        return FileResponse(f if f.is_file() else DIST / "index.html")
