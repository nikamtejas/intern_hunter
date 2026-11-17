"""What a recruiter will look for that the profile doesn't have yet (links, contact, metrics...)."""
from __future__ import annotations

import re

from .profile_schema import normalize

TECH_HINT = re.compile(r"python|java|javascript|react|sql|machine learning|developer|software|data|c\+\+|node|flutter|android", re.I)


def check(profile: dict, country: str = "") -> dict:
    p = normalize(profile)
    items: list[dict] = []

    def add(severity: str, field: str, message: str) -> None:
        items.append({"severity": severity, "field": field, "message": message})

    if not p["name"]:
        add("high", "name", "Add your full name.")
    if "@" not in p["email"]:
        add("high", "email", "Add a professional email address.")
    if len(re.sub(r"\D", "", p["phone"])) < 8:
        add("high", "phone", "Add a phone number with country code (e.g. +91 …, +49 …).")
    if not p["linkedin"]:
        add("high", "linkedin", "Add your LinkedIn URL — most recruiters check it before shortlisting.")
    elif "linkedin.com/in/" not in p["linkedin"].lower():
        add("medium", "linkedin", "LinkedIn link should be your public profile URL (linkedin.com/in/your-name).")
    techy = bool(TECH_HINT.search(" ".join(p["skills"]["technical"] + p["skills"]["tools"]) + " " + p["headline"]))
    if not p["github"] and techy:
        add("high", "github", "Add your GitHub profile — for tech internships it's the proof behind your projects.")
    if not p["location"]:
        add("medium", "location", "Add your city and country.")
    if len(p["summary"]) < 40:
        add("low", "summary", "Add a 2–3 line summary (the AI tailors it per job, but needs a starting point).")

    if not p["projects"] and not p["experience"]:
        add("high", "projects", "Add at least 2 projects or internships — they carry most of an internship resume.")
    for pr in p["projects"]:
        name = pr.get("name") or "A project"
        if not pr.get("link") and techy:
            add("medium", "projects", f"“{name}” has no code link — add the GitHub repo URL.")
        if not pr.get("live"):
            add("low", "projects", f"“{name}” has no live demo link — add it if the project is deployed (Vercel, Netlify, Streamlit…).")
        if len(pr.get("bullets", [])) < 2:
            add("medium", "projects", f"“{name}” needs 2–3 bullet points: what you built, with what, and the result.")
    for e in p["experience"]:
        if len(e.get("bullets", [])) < 2:
            add("medium", "experience", f"“{e.get('title') or 'An experience'}” needs 2–4 bullet points.")
        if not (e.get("start") or e.get("end")):
            add("low", "experience", f"“{e.get('title') or 'An experience'}” has no dates.")

    bullets = [b for s in ("experience", "projects") for it in p[s] for b in it.get("bullets", [])]
    if bullets:
        with_nums = sum(1 for b in bullets if re.search(r"\d", b))
        if with_nums / len(bullets) < 0.33:
            add("medium", "metrics", f"Only {with_nums} of {len(bullets)} bullets have a number. Add real figures "
                                     "(users, %, time saved, dataset size) — the score's impact points depend on it.")
    if not p["education"]:
        add("high", "education", "Add your degree, institution and graduation year.")
    elif not any(e.get("grade") for e in p["education"]):
        add("low", "education", "Add your CGPA / grade if it's decent — Indian recruiters filter on it.")
    n_skills = len(p["skills"]["technical"]) + len(p["skills"]["tools"])
    if n_skills < 8:
        add("medium", "skills", f"Only {n_skills} technical skills/tools listed. Add everything you genuinely know — "
                                "the AI only uses what's here, so missing skills cap your ATS score.")
    if not p["skills"]["soft"]:
        add("medium", "skills", "No soft skills listed. Add the ones you genuinely have (communication, teamwork, problem solving, "
                                "attention to detail…) — most postings ask for them and ATS match them word for word.")
    if not p["languages"]:
        add("high" if country in ("germany", "europe") else "low", "languages",
            "Add languages with levels (e.g. English C1, German A2) — important across Europe.")
    if country in ("germany", "europe"):
        if not p["extras"].get("availability"):
            add("medium", "extras", "Add availability (start date and duration) — German postings ask for it.")
        if not p["extras"].get("work_permit"):
            add("low", "extras", "Add your work-permit status (e.g. EU citizen / student visa).")
    if not p["certifications"]:
        add("low", "certifications", "Add certifications if you have any (Coursera, NPTEL, AWS…).")

    weight = {"high": 12, "medium": 5, "low": 2}
    score = max(0, 100 - sum(weight[i["severity"]] for i in items))
    order = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda i: order[i["severity"]])
    return {"score": score, "items": items}
