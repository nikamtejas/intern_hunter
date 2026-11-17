"""The profile / resume JSON shape shared by parser, tailor, ATS and renderer."""
from __future__ import annotations

import copy
import re

EMPTY_PROFILE: dict = {
    "name": "",
    "headline": "",
    "email": "",
    "phone": "",
    "location": "",
    "linkedin": "",
    "github": "",
    "portfolio": "",
    "links": [],  # other links: [{label, url}]
    "summary": "",
    "education": [],  # [{institution, degree, field, location, start, end, grade, details: []}]
    "experience": [],  # [{title, company, location, start, end, bullets: []}]
    "projects": [],  # [{name, tech: [], link (source/GitHub), live (deployed demo), start, end, bullets: []}]
    "skills": {"technical": [], "tools": [], "soft": []},
    "languages": [],  # [{name, level}]  e.g. German B1 (CEFR)
    "certifications": [],  # [{name, issuer, date}]
    "achievements": [],  # [str]
    "learning": [],  # skills the candidate is learning right now — shown as "Currently learning", never claimed as experience
    "extras": {"nationality": "", "work_permit": "", "availability": "", "date_of_birth": ""},
}

SCHEMA_TEXT = """{
  "name": str, "headline": str, "email": str, "phone": str, "location": str,
  "linkedin": str, "github": str, "portfolio": str,   // full profile URLs
  "links": [{"label": str, "url": str}],              // any other links (Kaggle, LeetCode, blog...)
  "summary": str,
  "education": [{"institution": str, "degree": str, "field": str, "location": str, "start": str, "end": str, "grade": str, "details": [str]}],
  "experience": [{"title": str, "company": str, "location": str, "start": str, "end": str, "bullets": [str]}],
  "projects": [{"name": str, "tech": [str], "link": str, "live": str, "start": str, "end": str, "bullets": [str]}],   // link = GitHub/source, live = deployed demo
  "skills": {"technical": [str], "tools": [str], "soft": [str]},
  "languages": [{"name": str, "level": str}],
  "certifications": [{"name": str, "issuer": str, "date": str}],
  "achievements": [str],
  "extras": {"nationality": str, "work_permit": str, "availability": str, "date_of_birth": str}
}"""


def normalize(p: dict | None) -> dict:
    """Fill missing keys so the rest of the code can rely on the shape."""
    out = copy.deepcopy(EMPTY_PROFILE)
    if not p:
        return out
    for k, v in p.items():
        if k == "skills" and isinstance(v, dict):
            for sk in ("technical", "tools", "soft"):
                out["skills"][sk] = [str(x) for x in (v.get(sk) or []) if str(x).strip()]
        elif k == "skills" and isinstance(v, list):
            out["skills"]["technical"] = [str(x) for x in v]
        elif k == "extras" and isinstance(v, dict):
            out["extras"].update({kk: str(vv or "") for kk, vv in v.items()})
        elif k in out:
            out[k] = v if v is not None else out[k]
    for sec, fields in (
        ("education", ("institution", "degree", "field", "location", "start", "end", "grade")),
        ("experience", ("title", "company", "location", "start", "end")),
        ("projects", ("name", "link", "live", "start", "end")),
        ("certifications", ("name", "issuer", "date")),
        ("languages", ("name", "level")),
        ("links", ("label", "url")),
    ):
        items = []
        for it in out.get(sec) or []:
            if isinstance(it, str):
                it = {fields[0]: it}
            if not isinstance(it, dict):
                continue
            for f in fields:
                it[f] = str(it.get(f) or "")
            for lf in ("bullets", "details", "tech"):
                if lf in it or sec in ("experience", "projects") and lf == "bullets":
                    it[lf] = [str(x) for x in (it.get(lf) or []) if str(x).strip()]
            if sec == "projects":
                it.setdefault("tech", [])
            if sec == "education":
                it.setdefault("details", [])
            items.append(it)
        out[sec] = items
    out["achievements"] = [str(x) for x in (out.get("achievements") or []) if str(x).strip()]
    out["learning"] = list(dict.fromkeys(str(x).strip() for x in (out.get("learning") or []) if str(x).strip()))
    for k in ("name", "headline", "email", "phone", "location", "summary", "linkedin", "github", "portfolio"):
        out[k] = str(out.get(k) or "").strip()
    _split_links(out)
    return out


def _split_links(out: dict) -> None:
    """Move LinkedIn/GitHub URLs out of the generic link list into their own fields (older profiles)."""
    rest = []
    for l in out["links"]:
        url = l.get("url", "").strip()
        low = url.lower()
        if not url:
            continue
        if "linkedin.com/" in low and not out["linkedin"]:
            out["linkedin"] = url
        elif re.search(r"github\.com/[^/\s]+/?$", low) and not out["github"]:
            out["github"] = url
        elif url not in (out["linkedin"], out["github"], out["portfolio"]):
            rest.append(l)
    out["links"] = rest


def flatten_text(p: dict) -> str:
    """All resume text as one string (used for keyword matching)."""
    parts: list[str] = [p.get("headline", ""), p.get("summary", "")]
    for e in p.get("education", []):
        parts += [e.get("degree", ""), e.get("field", ""), e.get("institution", ""), *e.get("details", [])]
    for e in p.get("experience", []):
        parts += [e.get("title", ""), e.get("company", ""), *e.get("bullets", [])]
    for pr in p.get("projects", []):
        parts += [pr.get("name", ""), " ".join(pr.get("tech", [])), *pr.get("bullets", [])]
    sk = p.get("skills", {})
    for k in ("technical", "tools", "soft"):
        parts.append(", ".join(sk.get(k, [])))
    parts += [c.get("name", "") for c in p.get("certifications", [])]
    parts += [f"{l.get('name','')} {l.get('level','')}" for l in p.get("languages", [])]
    parts += p.get("achievements", [])
    if p.get("learning"):
        parts.append("Currently learning: " + ", ".join(p["learning"]))
    return "\n".join(x for x in parts if x)
