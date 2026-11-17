"""Interview prep and follow-up emails for one application (generated on demand)."""
from __future__ import annotations

import json
import time

from . import groq_client, prompts

PREP = f"""You are an interview coach preparing a student for an internship interview at this company.
Return ONLY JSON:
{{
 "elevator_pitch": str,                          // 3-4 sentences "tell me about yourself", tailored to this job
 "questions": [{{"type": "technical"|"behavioral"|"role"|"company", "question": str,
                "why_they_ask": str, "answer_outline": str, "based_on": str}}],   // 10-12, most likely first
 "brush_up": [{{"skill": str, "why": str, "days": [str], "free_resources": [str]}}],  // 3-6 items
 "questions_to_ask": [str],                     // 3-4 smart questions for the interviewer
 "red_flags": [str]                             // gaps an interviewer may probe, with how to answer honestly
}}
Rules:
- answer_outline uses the STAR shape (Situation, Task, Action, Result) built ONLY from facts in the RESUME. "based_on" names
  the experience/project it comes from. Never invent numbers, tools or outcomes.
- For skills listed under CURRENTLY LEARNING (or missing from the resume) the honest answer is what the candidate has started
  and how they will close the gap fast — never pretend experience.
- brush_up covers the job's must-haves the candidate is weakest in (start with CURRENTLY LEARNING): a 7-day plan in "days"
  (one short line per day, practical: build X, read Y) and well-known free resources by name (official docs, freeCodeCamp,
  Kaggle Learn, Microsoft Learn, Google's courses, YouTube channel names) — no made-up URLs.
- Plain, direct language. Never use: {", ".join(prompts.BANNED_PHRASES[:30])}."""

FOLLOWUP = """Write a short, polite follow-up email for an internship application that got no reply yet.
Return ONLY JSON: {"subject": str, "body": str}
- 90-130 words. Reference the exact role and when they applied, restate one concrete match from the resume in one sentence,
  ask whether there is an update or anything else they need, and thank them. No pressure, no apologies, no clichés.
- Sign with the candidate's name, then their LinkedIn URL if given."""


def _ctx(app: dict, job: dict) -> str:
    r = app.get("resume") or {}
    learning = list(r.get("learning", [])) + list((app.get("ats") or {}).get("gaps", []))
    return (f"JOB TITLE: {job.get('title')}\nCOMPANY: {job.get('company')}\nLOCATION: {job.get('location')}\n"
            f"JOB POSTING:\n{(job.get('description') or '')[:6000]}\n\n"
            f"RESUME (only source of facts):\n{json.dumps(r, ensure_ascii=False)[:9000]}\n\n"
            f"CURRENTLY LEARNING / NOT YET ON THE RESUME: {', '.join(dict.fromkeys(learning)) or 'none'}")


async def interview_prep(app: dict, job: dict) -> dict:
    out = await groq_client.chat_json(PREP, _ctx(app, job), temperature=0.3, max_tokens=5000)
    out["generated_at"] = time.time()
    return out


def _days_since(ts: float | None) -> int:
    return int((time.time() - ts) / 86400) if ts else 0


def followup_template(app: dict, job: dict) -> dict:
    r = app.get("resume") or {}
    name, link = r.get("name", ""), r.get("linkedin", "")
    days = _days_since(app.get("applied_at"))
    when = f"{days} days ago" if days > 1 else "recently"
    body = (f"Dear Hiring Team,\n\nI applied for the {job.get('title')} position at {job.get('company') or 'your company'} {when} "
            f"and wanted to follow up on my application. I'm still very interested in the role and would be glad to share "
            f"anything else you need, such as references or work samples.\n\nCould you let me know if there is an update on "
            f"the next steps?\n\nThank you for your time.\n\nBest regards,\n{name}" + (f"\n{link}" if link else ""))
    return {"subject": f"Follow-up: {job.get('title')} application", "body": body, "ai": False, "generated_at": time.time()}


async def followup(app: dict, job: dict) -> dict:
    """AI draft when Groq is available; a solid template otherwise (never fails)."""
    try:
        ctx = _ctx(app, job) + f"\nAPPLIED: {_days_since(app.get('applied_at'))} days ago"
        out = await groq_client.chat_json(FOLLOWUP, ctx, temperature=0.4, max_tokens=900)
        if out.get("subject") and out.get("body"):
            return {"subject": out["subject"], "body": out["body"], "ai": True, "generated_at": time.time()}
    except Exception:
        pass
    return followup_template(app, job)
