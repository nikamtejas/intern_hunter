"""Resume Studio: critique a sample resume (AI recruiter review + local ATS/style checks)."""
from __future__ import annotations

import json
import re

from . import ats, groq_client, humanize, prompts
from .profile_schema import flatten_text, normalize


def local_checks(profile: dict, raw_text: str = "") -> dict:
    p = normalize(profile)
    text = flatten_text(p)
    review = humanize.review(p)
    if raw_text:  # the parser may tidy wording; scan the original text too
        review["cliches"] = sorted(set(review["cliches"]) | set(humanize.find_cliches(raw_text)))
    bullets = [b for s in ("experience", "projects") for it in p[s] for b in it.get("bullets", [])]
    with_numbers = sum(1 for b in bullets if re.search(r"\d", b))
    checks = [
        ("Email present", bool(re.search(r"@", p["email"]))),
        ("Phone present", len(re.sub(r"\D", "", p["phone"])) >= 8),
        ("LinkedIn/GitHub/portfolio link", bool(p["links"])),
        ("Summary present", len(p["summary"]) > 40),
        ("Education section", bool(p["education"])),
        ("Skills section", bool(p["skills"]["technical"] or p["skills"]["tools"])),
        ("Projects or experience", bool(p["experience"] or p["projects"])),
        ("At least 1/3 of bullets have numbers", bool(bullets) and with_numbers / len(bullets) >= 0.33),
        ("No AI-cliché words", not review["cliches"]),
        ("No repeated bullet openers", not review["repeated_verbs"]),
        ("Length 250–850 words", 250 <= len(text.split()) <= 850),
    ]
    ats_risks = []
    if raw_text:
        if raw_text.count("|") > 15:
            ats_risks.append("Looks like the original uses tables or multi-column layout — many ATS parsers scramble these.")
        if len(raw_text.split()) < 120:
            ats_risks.append("Very little text could be extracted — the file may be image-based or use text boxes/graphics.")
    return {
        "checks": [{"label": l, "ok": ok} for l, ok in checks],
        "passed": sum(ok for _, ok in checks), "total": len(checks),
        "word_count": len(text.split()), "bullets": len(bullets), "bullets_with_numbers": with_numbers,
        "style": review, "ats_risks": ats_risks,
    }


async def analyze(profile: dict, raw_text: str, target_role: str, country: str) -> dict:
    target = f"a {target_role} internship in {country.title()}" if target_role else f"internships in {country.title()}"
    system = prompts.ANALYZER.replace("{target}", target)
    source = raw_text.strip() or json.dumps(profile, ensure_ascii=False)
    ai = await groq_client.chat_json(system, f"{prompts.REGION_RULES.get(country, '')}\n\nRESUME:\n{source[:14000]}",
                                     temperature=0.2, max_tokens=3000)
    ai.setdefault("issues", [])
    ai.setdefault("strengths", [])
    ai.setdefault("bullet_rewrites", [])
    return {"ai": ai, "local": local_checks(profile, raw_text)}
