"""Shared scraper types and helpers."""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone

import httpx

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
}

# Time range -> days
RANGE_DAYS = {"24h": 1, "week": 7, "month": 30}

# region drives resume/cover-letter conventions: india | germany (DACH: Lebenslauf, German option) | europe
COUNTRIES = {
    "india": {"name": "India", "flag": "🇮🇳", "region": "india", "adzuna": "in", "linkedin_geo": "102713980", "lang": "en"},
    "europe": {"name": "All of Europe", "flag": "🇪🇺", "region": "europe", "linkedin_location": "Europe", "lang": "en"},
    "germany": {"name": "Germany", "flag": "🇩🇪", "region": "germany", "adzuna": "de", "linkedin_geo": "101282230", "lang": "de"},
    "austria": {"name": "Austria", "flag": "🇦🇹", "region": "germany", "adzuna": "at", "lang": "de"},
    "switzerland": {"name": "Switzerland", "flag": "🇨🇭", "region": "germany", "adzuna": "ch", "lang": "de"},
    "netherlands": {"name": "Netherlands", "flag": "🇳🇱", "region": "europe", "adzuna": "nl", "lang": "nl"},
    "france": {"name": "France", "flag": "🇫🇷", "region": "europe", "adzuna": "fr", "lang": "fr"},
    "spain": {"name": "Spain", "flag": "🇪🇸", "region": "europe", "adzuna": "es", "lang": "es"},
    "italy": {"name": "Italy", "flag": "🇮🇹", "region": "europe", "adzuna": "it", "lang": "it"},
    "united_kingdom": {"name": "United Kingdom", "flag": "🇬🇧", "region": "europe", "adzuna": "gb", "lang": "en"},
    "ireland": {"name": "Ireland", "flag": "🇮🇪", "region": "europe", "lang": "en"},
    "belgium": {"name": "Belgium", "flag": "🇧🇪", "region": "europe", "adzuna": "be", "lang": "fr"},
    "poland": {"name": "Poland", "flag": "🇵🇱", "region": "europe", "adzuna": "pl", "lang": "pl"},
    "portugal": {"name": "Portugal", "flag": "🇵🇹", "region": "europe", "lang": "en"},
    "sweden": {"name": "Sweden", "flag": "🇸🇪", "region": "europe", "lang": "en"},
    "denmark": {"name": "Denmark", "flag": "🇩🇰", "region": "europe", "lang": "en"},
    "finland": {"name": "Finland", "flag": "🇫🇮", "region": "europe", "lang": "en"},
    "czechia": {"name": "Czechia", "flag": "🇨🇿", "region": "europe", "lang": "en"},
}
EUROPE = [k for k, v in COUNTRIES.items() if v["region"] != "india" and k != "europe"]

# the word for "internship" in each language (LinkedIn's guest search ignores its own internship filter)
INTERN_WORDS = {"en": ["intern", "internship"], "de": ["praktikum", "werkstudent"], "fr": ["stage", "stagiaire"],
                "nl": ["stage"], "es": ["prácticas", "becario"], "it": ["tirocinio", "stage"], "pl": ["staż", "praktyki"]}

# how a location string names each country (English + local spellings + biggest cities)
COUNTRY_HINTS = {
    "germany": "germany deutschland berlin munich münchen hamburg cologne köln frankfurt stuttgart düsseldorf leipzig dresden "
               "hannover nuremberg nürnberg bremen essen dortmund bonn mannheim karlsruhe heidelberg augsburg",
    "austria": "austria österreich vienna wien graz linz salzburg innsbruck",
    "switzerland": "switzerland schweiz suisse svizzera zurich zürich geneva genève basel bern lausanne lugano zug",
    "netherlands": "netherlands nederland holland amsterdam rotterdam utrecht eindhoven the hague den haag delft leiden groningen",
    "france": "france paris lyon marseille toulouse nice nantes bordeaux lille rennes strasbourg montpellier grenoble",
    "spain": "spain españa espana madrid barcelona valencia seville sevilla malaga málaga bilbao",
    "italy": "italy italia milan milano rome roma turin torino florence firenze bologna naples napoli",
    "united_kingdom": "united kingdom uk england scotland wales london manchester edinburgh birmingham cambridge oxford bristol leeds glasgow",
    "ireland": "ireland dublin cork galway limerick",
    "belgium": "belgium belgique belgië brussels bruxelles antwerp antwerpen ghent gent leuven",
    "poland": "poland polska warsaw warszawa krakow kraków wroclaw wrocław gdansk gdańsk poznan poznań",
    "portugal": "portugal lisbon lisboa porto",
    "sweden": "sweden sverige stockholm gothenburg göteborg malmö malmo",
    "denmark": "denmark danmark copenhagen københavn aarhus",
    "finland": "finland suomi helsinki espoo tampere",
    "czechia": "czechia czech republic česko prague praha brno",
}
NON_EUROPE = re.compile(r"\b(?:united states|usa|canada|india|singapore|australia|brazil|mexico|japan|china|dubai|uae)\b", re.I)


def region_of(country: str) -> str:
    return COUNTRIES.get(country or "", {}).get("region", "europe")


def intern_terms(country: str) -> list[str]:
    lang = COUNTRIES.get(country, {}).get("lang", "en")
    return list(dict.fromkeys(INTERN_WORDS.get(lang, []) + INTERN_WORDS["en"]))


def location_country(location: str) -> str | None:
    """Best guess of the country key from a free-text location ("Lyon, France", "Köln", "Remote - EU")."""
    loc = f" {(location or '').lower()} "
    for key, hints in COUNTRY_HINTS.items():
        for h in hints.split():
            if re.search(r"(?<![a-zà-ÿ])" + re.escape(h) + r"(?![a-zà-ÿ])", loc):
                return key
    return None


# ---- work mode (remote / hybrid / on-site), read from the posting text
REMOTE_RX = re.compile(r"(?:\b(?:fully remote|100\s?% remote|remote[- ](?:first|only|friendly|position|role|internship|job|"
                       r"work(?:ing)?|possible|option|based|from)|work(?:ing)? (?:from|at) home|wfh|work from anywhere|"
                       r"télétravail complet|vollständig remote|100\s?% homeoffice)\b|\(remote\)|[-–|,]\s*remote\b|"
                       r"^\s*remote\b|\bremote\s*$)", re.I | re.M)
HYBRID_RX = re.compile(r"\b(?:hybrid|homeoffice|home office|home-office|mobiles arbeiten|mobile work(?:ing)?|"
                       r"télétravail|teletrabajo|smart working|thuiswerken|remote days?|days? (?:from|at) home)\b", re.I)
# "2 days of remote working per week", "partly remote", "remote Fridays" are hybrid, and win over the remote check
PARTIAL_RX = re.compile(r"\b(?:\d+|one|two|three|four|ein|zwei|drei|deux|trois)\s*(?:-|to)?\s*(?:\d+\s*)?(?:days?|tage?n?|jours?)\s+"
                        r"(?:of\s+|per week\s+)?(?:remote|home ?office|from home|télétravail)|(?:remote|home ?office|télétravail)\s+"
                        r"(?:\w+\s+){0,3}(?:per|a|each|pro)\s+(?:week|woche|semaine)|partial(?:ly)? remote|partly remote|"
                        r"remote (?:mondays?|fridays?)|occasional(?:ly)? remote", re.I)
WORK_MODES = ("any", "remote", "hybrid", "onsite")


def detect_work_mode(*texts: str, remote_flag: bool | None = None) -> str:
    """remote | hybrid | onsite — from a source's own flag when it has one, else from the wording."""
    if remote_flag:
        return "remote"
    t = "\n".join(x for x in texts if x)
    if PARTIAL_RX.search(t):
        return "hybrid"
    if REMOTE_RX.search(t):
        return "remote"
    if HYBRID_RX.search(t):
        return "hybrid"
    return "onsite"


def mode_matches(mode: str, wanted: str) -> bool:
    return wanted == "any" or mode == wanted


INTERN_PATTERN = re.compile(
    r"\b(intern|interns|internship|internships|praktikum|praktikant|praktikantin|praktikanten|"
    r"werkstudent|werkstudentin|working student|trainee|summer analyst|co-?op|stipend|"
    r"pflichtpraktikum|abschlussarbeit|thesis|stagiaire|stage|alternance|tirocinio|tirocinante|pr[aá]cticas|"
    r"becari[oa]|sta[zż]|praktyki|praktikant\w*|stagi[aä]r|harjoittelija)\b",
    re.I,
)
# Titles that look like "intern" but are senior/full-time roles
EXCLUDE_PATTERN = re.compile(r"\b(internal|international|senior|lead|principal|head of|director|manager|"
                             r"early[- ]stage|late[- ]stage|growth[- ]stage|seed[- ]stage|backstage)\b", re.I)


@dataclass
class Job:
    source: str
    title: str
    company: str
    location: str
    country: str
    url: str
    posted_at: str | None = None  # ISO 8601 (UTC)
    description: str = ""
    external_id: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        key = f"{self.source}:{self.external_id or self.url}"
        return hashlib.sha1(key.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["id"] = self.id
        d["extra"] = {**d["extra"], "external_id": self.external_id}
        return d


def is_internship(title: str, description: str = "", strict_title: bool = False) -> bool:
    """True when the posting looks like an internship / working-student role."""
    title = title or ""
    if INTERN_PATTERN.search(title):
        # "Internal Auditor" etc. don't match INTERN_PATTERN thanks to \b, but guard senior titles
        return not re.search(r"\b(senior|lead|principal|head of|director|early[- ]stage|late[- ]stage|growth[- ]stage|"
                             r"seed[- ]stage|backstage)\b", title, re.I)
    if strict_title:
        return False
    return bool(INTERN_PATTERN.search((description or "")[:600]))


def within_days(posted_at: str | None, days: int) -> bool:
    if not posted_at:
        return True  # unknown date: keep, source already filtered server-side
    try:
        dt = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    # +1 day slack because many sites only give a date, not a time
    return dt >= datetime.now(timezone.utc) - timedelta(days=days + 1)


def relative_to_iso(text: str) -> str | None:
    """Convert 'Few hours ago', '3 days ago', '2 weeks ago', 'Just now', 'Today' to ISO."""
    if not text:
        return None
    t = text.lower().strip()
    now = datetime.now(timezone.utc)
    if any(w in t for w in ("just now", "few hours", "today", "minute", "hour", "heute", "stunde")):
        m = re.search(r"(\d+)\s*(hour|stunde)", t)
        return (now - timedelta(hours=int(m.group(1)) if m else 2)).isoformat()
    if "yesterday" in t or "gestern" in t:
        return (now - timedelta(days=1)).isoformat()
    m = re.search(r"(\d+)\+?\s*(day|week|month|tag|woche|monat)", t)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        days = n * {"day": 1, "tag": 1, "week": 7, "woche": 7, "month": 30, "monat": 30}[unit]
        return (now - timedelta(days=days)).isoformat()
    return None


def clean_text(s: str | None) -> str:
    if not s:
        return ""
    s = re.sub(r"\r", "", s)
    s = re.sub(r"[ \t ]+", " ", s)
    s = re.sub(r"\n\s*\n\s*\n+", "\n\n", s)
    return s.strip()


def html_to_text(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "lxml")
    for br in soup.find_all(["br"]):
        br.replace_with("\n")
    for li in soup.find_all("li"):
        li.insert_before("\n• ")
    for p in soup.find_all(["p", "div", "h1", "h2", "h3", "h4", "ul", "ol"]):
        p.insert_after("\n")
    return clean_text(soup.get_text())


def make_client(timeout: float = 20.0, headers: dict | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=timeout, headers={**DEFAULT_HEADERS, **(headers or {})}, follow_redirects=True, http2=False
    )


class ScraperError(Exception):
    pass
