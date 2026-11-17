"""Bundesagentur für Arbeit Jobsuche — Germany's official job board (our own client).

Public API used by the arbeitsagentur.de website. angebotsart=34 = Praktikum/Trainee.
Docs: https://github.com/bundesAPI/jobsuche-api
"""
from __future__ import annotations

import asyncio
import base64

from .base import RANGE_DAYS, Job, clean_text, detect_work_mode, is_internship, make_client, mode_matches

BASE = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service"
SEARCH_PATHS = ["/pc/v4/jobs", "/pc/v4/app/jobs", "/pc/v6/jobs"]
DETAIL_PATHS = ["/pc/v4/jobdetails/{code}", "/pc/v3/jobdetails/{code}"]
HEADERS = {"X-API-Key": "jobboerse-jobsuche", "Accept": "application/json"}


def _loc(r: dict) -> str:
    # v4: "arbeitsort" dict; v6: "stellenlokationen" list of {"adresse": {...}}
    a = r.get("arbeitsort") or next((l.get("adresse") or {} for l in r.get("stellenlokationen") or []), {})
    region = (a.get("region") or "").replace("_", " ").title()
    return ", ".join(x for x in (a.get("ort"), region) if x)


def parse(data: dict) -> list[Job]:
    """Parse a search response (v4 "stellenangebote" or v6 "ergebnisliste" schema)."""
    jobs = []
    for r in data.get("stellenangebote") or data.get("ergebnisliste") or []:
        refnr = r.get("refnr") or r.get("referenznummer") or ""
        date = (r.get("aktuelleVeroeffentlichungsdatum") or (r.get("veroeffentlichungszeitraum") or {}).get("von")
                or r.get("datumErsteVeroeffentlichung") or r.get("eintrittsdatum"))
        beruf = r.get("beruf") or r.get("hauptberuf")
        jobs.append(
            Job(
                source="bundesagentur",
                title=r.get("titel") or r.get("stellenangebotsTitel") or beruf or "",
                company=r.get("arbeitgeber") or r.get("firma") or "",
                location=_loc(r),
                country="germany",
                url=r.get("externeUrl") or r.get("externeURL") or f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}",
                posted_at=(date + "T00:00:00+00:00") if date and len(date) == 10 else date,
                external_id=refnr,
                extra={"beruf": beruf, "refnr": refnr,
                       "work_mode": "hybrid" if r.get("homeofficemoeglich") else detect_work_mode(r.get("titel") or r.get("stellenangebotsTitel") or "")},
            )
        )
    return jobs


async def search(country, time_range, keywords="", location="", max_pages=3, size=50, work_mode="any"):
    if country != "germany":
        return [], []
    days = RANGE_DAYS[time_range]
    out: dict[str, Job] = {}
    warnings: list[str] = []
    async with make_client(headers=HEADERS) as client:
        path = None
        for page in range(1, max_pages + 1):
            params = {"angebotsart": 34, "veroeffentlichtseit": days, "page": page, "size": size, "pav": "false"}
            if keywords:
                params["was"] = keywords
            if location:
                params["wo"] = location
                params["umkreis"] = 50
            r = None
            for p in ([path] if path else SEARCH_PATHS):
                try:
                    r = await client.get(BASE + p, params=params)
                except Exception as e:
                    warnings.append(f"Bundesagentur request failed: {e}")
                    r = None
                    continue
                if r.status_code == 200:
                    path = p
                    break
            if r is None or r.status_code != 200:
                warnings.append(f"Bundesagentur HTTP {r.status_code if r is not None else 'error'}")
                break
            batch = parse(r.json())
            for j in batch:
                out.setdefault(j.external_id, j)
            if len(batch) < size:
                break
            await asyncio.sleep(0.5)
    # angebotsart=34 includes trainee programmes; keep them (relevant for students) but tag
    jobs = [j for j in out.values() if mode_matches(j.extra["work_mode"], work_mode)]
    for j in jobs:
        j.extra["title_says_intern"] = is_internship(j.title)
    return jobs, warnings


async def fetch_description(refnr: str) -> str:
    code = base64.b64encode(refnr.encode()).decode()
    async with make_client(headers=HEADERS) as client:
        for p in DETAIL_PATHS:
            r = await client.get(BASE + p.format(code=code))
            if r.status_code == 200:
                d = r.json()
                parts = [d.get("stellenangebotsTitel") or d.get("titel"), d.get("stellenangebotsBeschreibung") or d.get("stellenbeschreibung")]
                return clean_text("\n\n".join(x for x in parts if x))
    return ""
