"""Internshala (India's largest internship site) — our own HTML scraper.

Listing pages:  https://internshala.com/internships/page-N/
Keyword pages:  https://internshala.com/internships/keywords-{kw}/page-N/
City pages:     https://internshala.com/internships/internship-in-{city}/page-N/
Detail pages:   https://internshala.com/internship/detail/<slug><id>

The parser keys off the detail links (stable) instead of fragile CSS class names,
then reads the surrounding card's text for stipend / duration / posted time.
"""
from __future__ import annotations

import asyncio
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import Job, RANGE_DAYS, clean_text, detect_work_mode, html_to_text, make_client, mode_matches, relative_to_iso, within_days

BASE = "https://internshala.com"
STIPEND_RE = re.compile(r"(₹\s?[\d,]+(?:\s?-\s?[\d,]+)?\s*(?:/month|/week|lump sum)?|Unpaid|Performance based)", re.I)
DURATION_RE = re.compile(r"\b(\d+\s*(?:Months?|Weeks?))\b", re.I)
POSTED_RE = re.compile(r"(Just now|Few hours ago|Today|\d+\+?\s*(?:hours?|days?|weeks?|months?)\s*ago)", re.I)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def listing_url(keywords: str, location: str, page: int, wfh: bool = False) -> str:
    if wfh:  # Internshala's own work-from-home listing (location doesn't apply)
        path = f"/internships/work-from-home-{_slug(keywords) + '-' if keywords else ''}internships/"
        return BASE + path + (f"page-{page}/" if page > 1 else "")
    parts = []
    if keywords:
        parts.append(f"keywords-{_slug(keywords)}")
    if location:
        parts.append(f"internship-in-{_slug(location)}")
    path = "/internships/" + ("/".join(parts) + "/" if parts else "")
    if page > 1:
        path += f"page-{page}/"
    return BASE + path


def _card_for(a):
    """Walk up from a detail link to the listing card container."""
    node = a
    for _ in range(8):
        node = node.parent
        if node is None:
            return None
        cls = node.get("class") or []
        if "individual_internship" in cls or node.get("internshipid") or node.get("data-internship_id"):
            return node
    return a.parent.parent.parent if a.parent and a.parent.parent else a.parent


def parse_listing(html: str) -> list[Job]:
    soup = BeautifulSoup(html, "lxml")
    jobs: dict[str, Job] = {}
    for a in soup.select("a[href*='/internship/detail/'], a[href*='/job/detail/']"):
        href = a.get("href") or ""
        if "/job/detail/" in href:
            continue  # full-time jobs, not internships
        m = re.search(r"(\d{6,})/?$", href.split("?")[0])
        if not m:
            continue
        ext_id = m.group(1)
        if ext_id in jobs:
            continue
        card = _card_for(a)
        if card is None:
            continue
        title = a.get_text(" ", strip=True)
        if not title or len(title) < 3:
            h = card.select_one("h3, .job-internship-name, .profile")
            title = h.get_text(" ", strip=True) if h else ""
        if not title:
            continue
        # Try in priority order: one combined selector returns the first match in document
        # order, and ".company a" also matches the title link (it sits inside div.company).
        comp_el = next((el for sel in ("p.company-name", ".company-name", ".company_name", "h4")
                        if (el := card.select_one(sel))), None)
        loc_els = card.select(".locations a, .location_link, .row-1-item.locations span a, #location_names a")
        text = card.get_text(" | ", strip=True)
        stipend = STIPEND_RE.search(text)
        duration = DURATION_RE.search(text)
        posted = POSTED_RE.search(text)
        location = ", ".join(dict.fromkeys(el.get_text(strip=True) for el in loc_els)) if loc_els else ""
        if not location:
            location = "Work from home" if re.search(r"work from home", text, re.I) else ""
        jobs[ext_id] = Job(
            source="internshala",
            title=title,
            company=comp_el.get_text(" ", strip=True) if comp_el else "",
            location=location,
            country="india",
            url=urljoin(BASE, href.split("?")[0]),
            posted_at=relative_to_iso(posted.group(1)) if posted else None,
            external_id=ext_id,
            extra={
                "stipend": stipend.group(1) if stipend else None,
                "duration": duration.group(1) if duration else None,
                "posted_text": posted.group(1) if posted else None,
            },
        )
    return list(jobs.values())


def parse_detail(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    parts = []
    for sel in (".internship_details", ".about_company_text_container", "#about_internship", ".text-container"):
        for el in soup.select(sel):
            parts.append(html_to_text(str(el)))
    if not parts:
        main = soup.select_one(".detail_view, #details_container, main")
        if main:
            parts.append(html_to_text(str(main)))
    return clean_text("\n\n".join(dict.fromkeys(p for p in parts if p)))


async def search(country, time_range, keywords="", location="", max_pages=4, delay=1.0, work_mode="any"):
    if country != "india":
        return [], []
    wfh = work_mode == "remote"
    days = RANGE_DAYS[time_range]
    out: dict[str, Job] = {}
    warnings: list[str] = []
    async with make_client() as client:
        for page in range(1, max_pages + 1):
            url = listing_url(keywords, location, page, wfh)
            try:
                r = await client.get(url)
            except Exception as e:
                warnings.append(f"Internshala request failed: {e}")
                break
            if r.status_code == 404:
                break
            if r.status_code >= 400:
                warnings.append(f"Internshala HTTP {r.status_code}")
                break
            batch = parse_listing(r.text)
            if not batch:
                if page == 1:
                    warnings.append("Internshala returned no parsable listings (page layout may have changed).")
                break
            for j in batch:
                j.extra["work_mode"] = "remote" if wfh or "work from home" in j.location.lower() else \
                    detect_work_mode(j.title, j.location)
            fresh = [j for j in batch if within_days(j.posted_at, days)]
            for j in fresh:
                out.setdefault(j.external_id, j)
            # Listings are newest-first; if nothing on this page is fresh, stop.
            if not fresh:
                break
            await asyncio.sleep(delay)
    return [j for j in out.values() if mode_matches(j.extra["work_mode"], work_mode)], warnings


async def fetch_description(url: str) -> str:
    async with make_client() as client:
        r = await client.get(url)
        return parse_detail(r.text) if r.status_code == 200 else ""
