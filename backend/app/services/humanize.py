"""Local checks that catch AI-sounding writing before the editor pass."""
from __future__ import annotations

import re
from collections import Counter

from .prompts import BANNED_PHRASES

FILLER = re.compile(r"\b(successfully|effectively|efficiently|various|several|etc)\b", re.I)


def _bullets_by_section(r: dict) -> dict[str, list[str]]:
    out = {}
    for sec in ("experience", "projects"):
        out[sec] = [b for it in r.get(sec, []) for b in it.get("bullets", [])]
    return out


def find_cliches(text: str) -> list[str]:
    tl = text.lower()
    return [p for p in BANNED_PHRASES if re.search(r"(?<![a-z])" + re.escape(p) + r"(?![a-z])", tl)]


def review(r: dict) -> dict:
    """Return concrete problems the editor must fix."""
    from .profile_schema import flatten_text

    text = flatten_text(r)
    issues: dict = {"cliches": find_cliches(text), "repeated_verbs": [], "short_bullets": [], "long_bullets": [],
                    "first_person": [], "filler": [], "thin_entries": []}
    for sec, bl in _bullets_by_section(r).items():
        verbs = Counter((b.split() or [""])[0].lower().strip(",.") for b in bl)
        issues["repeated_verbs"] += [f"{v} ({sec})" for v, n in verbs.items() if n > 1 and v]
        for b in bl:
            n = len(b.split())
            if n < 9:
                issues["short_bullets"].append(b)
            if n > 38:  # two full printed lines is ~34 words
                issues["long_bullets"].append(b)
            if re.search(r"\b(I|my|me)\b", b):
                issues["first_person"].append(b)
            if FILLER.search(b):
                issues["filler"].append(b)
    for sec in ("experience", "projects"):
        for it in r.get(sec, []):
            if len(it.get("bullets", [])) < 2:
                issues["thin_entries"].append(it.get("title") or it.get("name") or sec)
    if re.search(r"\b(I|my)\b", r.get("summary", "")):
        issues["first_person"].append("summary")
    issues["count"] = sum(len(v) for k, v in issues.items() if isinstance(v, list))
    return issues


def notes(issues: dict) -> list[str]:
    out = []
    if issues["cliches"]:
        out.append("Remove these AI-sounding/cliché words and rewrite those sentences concretely: " + ", ".join(issues["cliches"]))
    if issues["repeated_verbs"]:
        out.append("These opening verbs are repeated — vary them: " + ", ".join(issues["repeated_verbs"]))
    if issues["short_bullets"]:
        out.append("Expand these thin bullets with how/what/why from the profile: " + " | ".join(issues["short_bullets"][:5]))
    if issues["long_bullets"]:
        out.append("Split or tighten these long bullets: " + " | ".join(issues["long_bullets"][:3]))
    if issues["first_person"]:
        out.append("Remove first-person words (I/my/me) from: " + " | ".join(issues["first_person"][:3]))
    if issues["filler"]:
        out.append("Remove filler adverbs (successfully/effectively/efficiently/various) from: " + " | ".join(issues["filler"][:3]))
    if issues["thin_entries"]:
        out.append("Give these entries 2–4 bullets using facts from the profile: " + ", ".join(issues["thin_entries"]))
    return out
