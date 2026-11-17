"""Adzuna official API (India + 10 European markets). Free key at developer.adzuna.com."""
from __future__ import annotations

from .base import (COUNTRIES, EUROPE, RANGE_DAYS, Job, clean_text, detect_work_mode, intern_terms, is_internship, make_client,
                   mode_matches)

API = "https://api.adzuna.com/v1/api/jobs/{cc}/search/{page}"


def parse(data: dict, country: str) -> list[Job]:
    jobs = []
    for r in data.get("results", []):
        title = clean_text(r.get("title", "")).replace("<strong>", "").replace("</strong>", "")
        desc = clean_text(r.get("description", ""))
        jobs.append(
            Job(
                source="adzuna",
                title=title,
                company=(r.get("company") or {}).get("display_name", ""),
                location=(r.get("location") or {}).get("display_name", ""),
                country=country,
                url=r.get("redirect_url", ""),
                posted_at=r.get("created"),
                description=desc,  # Adzuna gives a ~500 char snippet
                external_id=str(r.get("id", "")),
                extra={"salary_min": r.get("salary_min"), "salary_max": r.get("salary_max"), "snippet_only": True,
                       "work_mode": detect_work_mode(title, (r.get("location") or {}).get("display_name", ""), desc)},
            )
        )
    return jobs


async def search(country, time_range, keywords="", location="", app_id=None, app_key=None, max_pages=3, work_mode="any"):
    if not app_id or not app_key:
        return [], ["Adzuna skipped: add ADZUNA_APP_ID and ADZUNA_APP_KEY in Settings (free at developer.adzuna.com)."]
    # "All of Europe" = one page from each European market Adzuna covers
    markets = [k for k in EUROPE if COUNTRIES[k].get("adzuna")] if country == "europe" else [country]
    if not COUNTRIES[markets[0]].get("adzuna"):
        return [], []
    out, warnings = {}, []
    async with make_client() as client:
        for market in markets:
            terms = intern_terms(market)
            queries = [f"{keywords} {terms[0]}".strip()] if keywords else terms[:3]
            if country == "europe":
                queries, pages = queries[:1], 1
            else:
                pages = max_pages
            for q in queries:
                for page in range(1, pages + 1):
                    params = {
                        "app_id": app_id, "app_key": app_key, "what": q, "results_per_page": 50,
                        "max_days_old": RANGE_DAYS[time_range], "sort_by": "date", "content-type": "application/json",
                    }
                    if location:
                        params["where"] = location
                    r = await client.get(API.format(cc=COUNTRIES[market]["adzuna"], page=page), params=params)
                    if r.status_code in (401, 403):
                        return [], ["Adzuna rejected the API key (check app id/key in Settings)."]
                    if r.status_code >= 400:
                        warnings.append(f"Adzuna HTTP {r.status_code}")
                        break
                    batch = parse(r.json(), market)
                    for j in batch:
                        out.setdefault(j.external_id, j)
                    if len(batch) < 50:
                        break
    jobs = [j for j in out.values() if is_internship(j.title, j.description) and mode_matches(j.extra["work_mode"], work_mode)]
    return jobs, warnings
