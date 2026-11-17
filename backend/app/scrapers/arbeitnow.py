"""Arbeitnow free job-board API (Europe-wide, mostly Germany; no key)."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from .base import (NON_EUROPE, RANGE_DAYS, Job, detect_work_mode, html_to_text, is_internship, location_country, make_client,
                   mode_matches, region_of, within_days)

API = "https://www.arbeitnow.com/api/job-board-api"

# Arbeitnow is Europe-wide; drop postings whose location names another country or a big foreign city.
FOREIGN_RE = re.compile(
    r"\b(united kingdom|england|uk|london|manchester|netherlands|nederland|holland|amsterdam|rotterdam|france|paris|lyon|nice|"
    r"bordeaux|toulouse|switzerland|schweiz|suisse|zurich|zürich|geneva|genève|basel|bern|lausanne|austria|"
    r"österreich|vienna|wien|spain|madrid|barcelona|italy|milan|rome|belgium|brussels|poland|warsaw|"
    r"portugal|lisbon|ireland|dublin|sweden|stockholm|denmark|copenhagen|czech|prague|usa|united states)\b",
    re.I,
)


def in_germany(location: str) -> bool:
    return not FOREIGN_RE.search(location or "")


def parse(data: dict) -> list[Job]:
    jobs = []
    for r in data.get("data", []):
        ts = r.get("created_at")
        posted = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if isinstance(ts, (int, float)) else None
        types = " ".join(r.get("job_types") or [])
        tags = r.get("tags") or []
        jobs.append(
            Job(
                source="arbeitnow",
                title=r.get("title", ""),
                company=r.get("company_name", ""),
                location=r.get("location", "") + (" (Remote)" if r.get("remote") else ""),
                country=location_country(r.get("location", "")) or "germany",
                url=r.get("url", ""),
                posted_at=posted,
                description=html_to_text(r.get("description", "")),
                external_id=r.get("slug", ""),
                extra={"job_types": r.get("job_types"), "tags": tags, "types_text": types,
                       "work_mode": detect_work_mode(r.get("title", ""), r.get("location", ""), remote_flag=r.get("remote"))},
            )
        )
    return jobs


def wanted_country(job: Job, raw_location: str, country: str) -> bool:
    if country == "europe":
        return not NON_EUROPE.search(raw_location or "")
    found = location_country(raw_location)
    if country == "germany":  # German towns not in the hint list ("Lübbecke") count as Germany
        return found in (None, "germany") and in_germany(raw_location)
    return found == country


async def search(country, time_range, keywords="", location="", max_pages=8, work_mode="any"):
    if region_of(country) == "india":
        return [], []
    days = RANGE_DAYS[time_range]
    kw = [k.lower() for k in keywords.split()] if keywords else []
    out, warnings = [], []
    async with make_client() as client:
        for page in range(1, max_pages + 1):
            r = await client.get(API, params={"page": page})
            if r.status_code >= 400:
                warnings.append(f"Arbeitnow HTTP {r.status_code}")
                break
            batch = parse(r.json())
            if not batch:
                break
            stop = False
            for j in batch:
                if not within_days(j.posted_at, days):
                    stop = True  # feed is newest-first
                    continue
                intern = is_internship(j.title) or "intern" in j.extra.get("types_text", "").lower()
                if not intern or not wanted_country(j, j.location.replace(" (Remote)", ""), country):
                    continue
                if not mode_matches(j.extra["work_mode"], work_mode):
                    continue
                if country == "europe":
                    j.country = location_country(j.location) or "europe"
                hay = f"{j.title} {j.description} {' '.join(j.extra.get('tags') or [])}".lower()
                if kw and not all(k in hay for k in kw):
                    continue
                if location and location.lower() not in j.location.lower():
                    continue
                out.append(j)
            if stop:
                break
    return out, warnings
