"""LinkedIn public (guest) job search — no login, so no account risk.

Uses the same endpoints the logged-out jobs page calls:
  /jobs-guest/jobs/api/seeMoreJobPostings/search   (10 cards per page)
  /jobs-guest/jobs/api/jobPosting/{id}              (full description)

Note: scraping LinkedIn is against its Terms of Service and LinkedIn rate-limits
guest traffic (HTTP 429). We go slowly and stop cleanly when blocked.
"""
from __future__ import annotations

import asyncio
import logging
import re

from bs4 import BeautifulSoup

from .base import (COUNTRIES, Job, detect_work_mode, html_to_text, intern_terms, is_internship, location_country,
                   make_client, mode_matches, within_days)

log = logging.getLogger(__name__)

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"
TPR = {"24h": "r86400", "week": "r604800", "month": "r2592000"}


def parse_cards(html: str, country: str) -> list[Job]:
    soup = BeautifulSoup(html, "lxml")
    jobs: list[Job] = []
    for card in soup.select("div.base-card, div.job-search-card, li > div[data-entity-urn]"):
        urn = card.get("data-entity-urn") or ""
        m = re.search(r"(\d{6,})", urn)
        link_el = card.select_one("a.base-card__full-link, a[href*='/jobs/view/']")
        href = (link_el.get("href") if link_el else "") or ""
        if not m:
            m = re.search(r"-(\d{6,})(?:\?|$)", href) or re.search(r"/view/(\d{6,})", href)
        if not m:
            continue
        job_id = m.group(1)
        title_el = card.select_one(".base-search-card__title, h3")
        comp_el = card.select_one(".base-search-card__subtitle, h4")
        loc_el = card.select_one(".job-search-card__location")
        time_el = card.select_one("time")
        title = title_el.get_text(" ", strip=True) if title_el else ""
        if not title:
            continue
        jobs.append(
            Job(
                source="linkedin",
                title=title,
                company=comp_el.get_text(" ", strip=True) if comp_el else "",
                location=loc_el.get_text(" ", strip=True) if loc_el else "",
                country=country,
                url=href.split("?")[0] or f"https://www.linkedin.com/jobs/view/{job_id}/",
                posted_at=(time_el.get("datetime") + "T00:00:00+00:00") if time_el and time_el.get("datetime") else None,
                external_id=job_id,
            )
        )
    # de-dupe within page
    seen, out = set(), []
    for j in jobs:
        if j.external_id not in seen:
            seen.add(j.external_id)
            out.append(j)
    return out


def parse_detail(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    el = soup.select_one(".show-more-less-html__markup, .description__text, .decorated-job-posting__details")
    return html_to_text(str(el)) if el else ""


async def search(
    country: str,
    time_range: str,
    keywords: str = "",
    location: str = "",
    max_pages: int = 4,
    delay: float = 2.0,
    work_mode: str = "any",
) -> tuple[list[Job], list[str]]:
    c = COUNTRIES[country]
    warnings: list[str] = []
    results: dict[str, Job] = {}
    # LinkedIn's guest API ignores its job-type / experience / workplace filters (f_JT, f_E, f_WT), so internships are
    # found by putting the local word for "internship" in the query and checking the title afterwards.
    terms = intern_terms(country)[:3]
    async with make_client(headers={"Referer": "https://www.linkedin.com/jobs/search"}) as client:
        for term in terms:
            for page in range(max_pages):
                params = {
                    "keywords": f"{keywords} {term}".strip(),
                    "location": location or c.get("linkedin_location") or c["name"],
                    "f_TPR": TPR[time_range],
                    "start": page * 10,
                }
                if not location and c.get("linkedin_geo"):
                    params["geoId"] = c["linkedin_geo"]
                try:
                    r = await client.get(SEARCH_URL, params=params)
                except Exception as e:  # network error
                    warnings.append(f"LinkedIn request failed: {e}")
                    break
                if r.status_code == 429:
                    warnings.append("LinkedIn rate-limited the search (HTTP 429). Showing what was collected; try again in a few minutes.")
                    return await _finish(results, time_range, work_mode, country, delay, warnings), warnings
                if r.status_code >= 400:
                    warnings.append(f"LinkedIn returned HTTP {r.status_code}.")
                    break
                cards = parse_cards(r.text, country)
                if not cards:
                    break
                for j in cards:
                    results.setdefault(j.external_id, j)
                await asyncio.sleep(delay)
    return await _finish(results, time_range, work_mode, country, delay, warnings), warnings


async def _finish(results: dict[str, Job], time_range: str, work_mode: str, country: str, delay: float,
                  warnings: list[str]) -> list[Job]:
    from .base import RANGE_DAYS

    days = RANGE_DAYS[time_range]
    out = [j for j in results.values() if within_days(j.posted_at, days) and is_internship(j.title)]
    for j in out:
        j.extra["title_says_intern"] = True
        if country == "europe":  # a Europe-wide search: tag each job with the country it's actually in
            j.country = location_country(j.location) or "europe"
        j.extra["work_mode"] = detect_work_mode(j.title, j.location)
    if work_mode != "any" and out:
        # cards don't say remote/hybrid: read each posting (politely, a few at a time) and keep the matching ones
        sem = asyncio.Semaphore(3)

        async def classify(j: Job):
            async with sem:
                try:
                    j.description = await fetch_description(j.external_id)
                except Exception:
                    j.description = ""
                await asyncio.sleep(min(delay, 1.0))
            j.extra["work_mode"] = detect_work_mode(j.title, j.location, j.description)

        await asyncio.gather(*(classify(j) for j in out[:45]))
        out = [j for j in out[:45] if mode_matches(j.extra["work_mode"], work_mode)]
    return out


async def fetch_description(external_id: str) -> str:
    async with make_client() as client:
        r = await client.get(DETAIL_URL.format(id=external_id))
        if r.status_code != 200:
            return ""
        return parse_detail(r.text)
