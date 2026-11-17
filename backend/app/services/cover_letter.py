"""Cover letter (Anschreiben for Germany) with Groq, plus a cliché clean-up pass."""
from __future__ import annotations

import json

from . import groq_client, humanize, prompts


async def generate(profile: dict, job: dict, country: str, language: str = "en", jd: dict | None = None) -> dict:
    lang = "Write in natural GERMAN." if language == "de" else "Write in English."
    user = (
        f"{prompts.COVER_REGION.get(country, '')}\n{lang}\n\n"
        f"JOB: {job.get('title')} at {job.get('company')} ({job.get('location')})\n"
        f"JOB ANALYSIS: {json.dumps(jd or {}, ensure_ascii=False)}\n"
        f"POSTING:\n{(job.get('description') or '')[:7000]}\n\n"
        f"CANDIDATE PROFILE:\n{json.dumps(profile, ensure_ascii=False)}"
    )
    out = await groq_client.chat_json(prompts.COVER_LETTER, user, temperature=0.55, max_tokens=1500)
    found = humanize.find_cliches(" ".join(out.get("paragraphs", [])))
    if found:
        fix = (f"{user}\n\nYOUR DRAFT:\n{json.dumps(out, ensure_ascii=False)}\n\n"
               f"Rewrite it without these words/phrases: {', '.join(found)}. Keep the facts and structure. Same JSON shape.")
        out = await groq_client.chat_json(prompts.COVER_LETTER, fix, temperature=0.4, max_tokens=1500)
    out.setdefault("paragraphs", [])
    out["signature"] = profile.get("name", "")
    return out
