"""Run all selected sources concurrently and merge the results."""
from __future__ import annotations

import asyncio
import logging
import re

from .. import db
from . import adzuna, arbeitnow, bundesagentur, internshala, linkedin
from .base import COUNTRIES, EUROPE, Job, detect_work_mode

log = logging.getLogger(__name__)

SOURCES = {
    "linkedin": {"label": "LinkedIn (public pages)", "countries": list(COUNTRIES)},
    "internshala": {"label": "Internshala", "countries": ["india"]},
    "bundesagentur": {"label": "Bundesagentur für Arbeit", "countries": ["germany"]},
    "arbeitnow": {"label": "Arbeitnow", "countries": ["europe", *EUROPE]},
    "adzuna": {"label": "Adzuna", "countries": ["india", "europe", *[k for k in EUROPE if COUNTRIES[k].get("adzuna")]]},
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


async def _run(name: str, coro) -> tuple[str, list[Job], list[str]]:
    try:
        jobs, warns = await asyncio.wait_for(coro, timeout=120)
        return name, jobs, warns
    except asyncio.TimeoutError:
        return name, [], [f"{SOURCES[name]['label']} timed out."]
    except Exception as e:  # never let one source break the search
        log.exception("source %s failed", name)
        return name, [], [f"{SOURCES[name]['label']} failed: {type(e).__name__}: {e}"]


async def search_all(country: str, time_range: str, sources: list[str], keywords: str = "", location: str = "",
                     work_mode: str = "any") -> dict:
    tasks = []
    for s in sources:
        if s not in SOURCES or country not in SOURCES[s]["countries"]:
            continue
        if s == "linkedin":
            coro = linkedin.search(
                country, time_range, keywords, location,
                max_pages=int(db.get_setting("LINKEDIN_MAX_PAGES", "4")),
                delay=float(db.get_setting("LINKEDIN_DELAY", "2.0")),
                work_mode=work_mode,
            )
        elif s == "adzuna":
            coro = adzuna.search(country, time_range, keywords, location,
                                 app_id=db.get_setting("ADZUNA_APP_ID"), app_key=db.get_setting("ADZUNA_APP_KEY"),
                                 work_mode=work_mode)
        elif s == "internshala":
            coro = internshala.search(country, time_range, keywords, location, work_mode=work_mode)
        elif s == "bundesagentur":
            coro = bundesagentur.search(country, time_range, keywords, location, work_mode=work_mode)
        elif s == "arbeitnow":
            coro = arbeitnow.search(country, time_range, keywords, location, work_mode=work_mode)
        tasks.append(_run(s, coro))

    results = await asyncio.gather(*tasks)
    merged: dict[str, Job] = {}
    per_source: dict[str, int] = {}
    warnings: list[str] = []
    for name, jobs, warns in results:
        per_source[name] = len(jobs)
        warnings.extend(warns)
        for j in jobs:
            key = _norm(j.title) + "|" + _norm(j.company)  # cross-source de-dupe
            if key in merged:
                existing = merged[key]
                existing.extra.setdefault("also_on", []).append({"source": j.source, "url": j.url})
                if len(j.description) > len(existing.description):
                    existing.description = j.description
                continue
            merged[key] = j

    for j in merged.values():  # every card shows Remote / Hybrid / On-site
        j.extra.setdefault("work_mode", detect_work_mode(j.title, j.location, j.description))
    jobs = sorted(merged.values(), key=lambda j: j.posted_at or "", reverse=True)
    for j in jobs:
        db.upsert_job(j.to_dict())
    return {"jobs": [j.to_dict() for j in jobs], "per_source": per_source, "warnings": warnings}


async def ensure_description(job: dict) -> str:
    """Fetch the full job description if we only have a snippet."""
    desc = job.get("description") or ""
    extra = job.get("extra") or {}
    if len(desc) > 400 and not extra.get("snippet_only"):
        return desc
    full = ""
    try:
        if job["source"] == "linkedin":
            ext = extra.get("external_id") or (re.findall(r"(\d{8,})", job["url"] or "") or [""])[-1]
            full = await linkedin.fetch_description(ext) if ext else ""
        elif job["source"] == "internshala":
            full = await internshala.fetch_description(job["url"])
        elif job["source"] == "bundesagentur":
            full = await bundesagentur.fetch_description(extra.get("refnr") or "")
    except Exception as e:
        log.warning("description fetch failed for %s: %s", job["id"], e)
    if len(full) > len(desc):
        db.set_job_description(job["id"], full)
        return full
    return desc
