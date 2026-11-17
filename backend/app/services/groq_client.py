"""Minimal Groq client (OpenAI-compatible chat completions) with JSON mode + retries."""
from __future__ import annotations

import asyncio
import json
import re

import httpx
import logging

from .. import db

log = logging.getLogger(__name__)

URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqError(Exception):
    pass


def _key() -> str:
    k = db.get_setting("GROQ_API_KEY")
    if not k:
        raise GroqError("No Groq API key set. Add it on the Settings page (free at console.groq.com/keys).")
    return k


DEFAULT_MODEL = "openai/gpt-oss-120b"  # llama-3.3-70b-versatile is no longer served by Groq


def _model() -> str:
    return db.get_setting("GROQ_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL


DEFAULT_FALLBACK = "openai/gpt-oss-20b"  # separate quota from the 120b model
MAX_WAIT = 90  # seconds; longer waits fail fast with a clear message instead of hanging the queue


def _fallback() -> str:
    return db.get_setting("GROQ_FALLBACK_MODEL", DEFAULT_FALLBACK) or ""


async def chat(messages: list[dict], *, json_mode: bool = False, temperature: float = 0.3, max_tokens: int = 4096) -> str:
    body = {"model": _model(), "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    if body["model"].startswith("openai/gpt-oss"):
        body["reasoning_effort"] = "low"  # reasoning tokens count toward max_tokens
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"}
    delay = 2.0
    last = ""
    json_retries = 0
    async with httpx.AsyncClient(timeout=90) as client:
        for attempt in range(7):
            try:
                r = await client.post(URL, json=body, headers=headers)
            except httpx.TransportError as e:  # Wi-Fi blip / DNS hiccup: wait and retry instead of failing the resume
                last = f"network error: {e}"
                log.warning("Groq network error (attempt %s): %s", attempt + 1, e)
                await asyncio.sleep(delay)
                delay *= 2
                continue
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            last = f"HTTP {r.status_code}: {r.text[:300]}"
            if r.status_code == 401:
                raise GroqError("Groq rejected the API key (401). Check it on the Settings page.")
            if r.status_code in (429, 500, 502, 503):
                ra = r.headers.get("retry-after")
                wait = float(ra) if ra and ra.replace(".", "").isdigit() else delay
                log.warning("Groq %s HTTP %s (attempt %s), retry-after %ss", body["model"], r.status_code, attempt + 1, wait)
                if wait > MAX_WAIT:
                    # a long wait means a daily/hourly quota is used up, not a short burst limit
                    fallback = _fallback()
                    if fallback and fallback != body["model"]:
                        log.warning("Switching to fallback model %s", fallback)
                        body["model"] = fallback
                        continue
                    raise GroqError(f"Groq's free-tier limit is used up for now — try again in about {max(1, round(wait / 60))} "
                                    "minutes. Each tailored resume uses ~5 AI calls; a paid Groq plan "
                                    "(console.groq.com/settings/billing) removes this limit.")
                await asyncio.sleep(wait)
                delay *= 2
                continue
            if r.status_code == 400 and json_mode and "json" in r.text.lower() and json_retries < 2:
                # model failed to produce valid JSON (more common on the smaller fallback model); retry cooler
                json_retries += 1
                body["temperature"] = 0.1
                continue
            break
    if last.startswith("network error"):
        raise GroqError(f"Couldn't reach Groq — check your internet connection, then click Retry. ({last})")
    raise GroqError(f"Groq request failed: {last}")


def parse_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise


async def chat_json(system: str, user: str, **kw) -> dict:
    out = await chat([{"role": "system", "content": system}, {"role": "user", "content": user}], json_mode=True, **kw)
    return parse_json(out)
