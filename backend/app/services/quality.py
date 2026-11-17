"""The "ready to send" rules every tailored resume is checked against (shown as a checklist in the app)."""
from __future__ import annotations

import re

from . import humanize, render

SHORTLIST_MIN = 90  # ATS score a resume must reach to count as ready


def check(resume: dict, ats_result: dict, country: str, language: str, minimum: float = SHORTLIST_MIN) -> dict:
    _, layout, _ = render.fit_one_page(resume, country, language)
    bullets = render.bullet_lines(resume, country, language, layout)
    flush = sum(1 for b in bullets if b["fill"] >= render.FLUSH_AT)
    texts = [b["text"] for b in bullets]
    with_numbers = sum(1 for t in texts if re.search(r"\d", t))
    # judge only the wording the AI wrote, not the candidate's own job and project titles
    style = humanize.review({**resume, "projects": [{**p, "name": ""} for p in resume.get("projects", [])],
                             "experience": [{**e, "title": "", "company": ""} for e in resume.get("experience", [])]})
    contact_missing = [k for k, ok in (("email", "@" in resume.get("email", "")),
                                       ("phone", len(re.sub(r"\D", "", resume.get("phone", ""))) >= 8),
                                       ("LinkedIn", bool(resume.get("linkedin"))), ("GitHub", bool(resume.get("github")))) if not ok]
    projects_without_links = [p.get("name", "") for p in resume.get("projects", []) if not (p.get("link") or p.get("live"))]
    score = ats_result["score"]

    rules = [
        {"id": "ats", "core": True, "ok": score >= minimum, "label": f"ATS score {minimum:.0f}+",
         "detail": f"{score:.0f}/100" + ("" if score >= minimum else " — see “Path to 90+” below")},
        {"id": "page", "core": True, "ok": layout.get("pages", 1) == 1 and layout["fill"] >= 0.95, "label": "Exactly one full page",
         "detail": f"{round(layout['fill'] * 100)}% of the page used"},
        {"id": "flush", "core": False, "ok": not bullets or flush / len(bullets) >= 0.8, "label": "Bullets end at the right margin",
         "detail": f"{flush} of {len(bullets)} bullets end flush"},
        {"id": "contact", "core": True, "ok": not contact_missing, "label": "Header: email, phone, LinkedIn, GitHub",
         "detail": "complete" if not contact_missing else "missing " + ", ".join(contact_missing)},
        {"id": "style", "core": False, "ok": not style["cliches"] and not style["repeated_verbs"], "label": "Human-sounding writing",
         "detail": "no clichés or repeated openers" if not style["cliches"] and not style["repeated_verbs"]
         else ", ".join((style["cliches"] + style["repeated_verbs"])[:4])},
        {"id": "truth", "core": True, "ok": True, "label": "Every claim backed by your profile",
         "detail": "invented tools, numbers and moved skills are removed automatically"},
        {"id": "numbers", "core": False, "ok": not texts or with_numbers / len(texts) >= 0.33, "label": "Real numbers in bullets",
         "detail": f"{with_numbers} of {len(texts)} bullets — add real figures on My profile"},
        {"id": "links", "core": False, "ok": not projects_without_links, "label": "Project code / live links",
         "detail": "all projects linked" if not projects_without_links else f"{len(projects_without_links)} project(s) without a link"},
    ]
    ready = all(r["ok"] for r in rules if r["core"])
    return {"ready": ready, "rules": rules, "passed": sum(r["ok"] for r in rules), "total": len(rules)}
