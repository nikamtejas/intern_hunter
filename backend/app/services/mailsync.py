"""Read-only inbox check: find recruiter emails about tracked applications and move their status forward.

Connects over IMAP with an app password (Gmail: Google Account → Security → 2-Step Verification → App passwords).
The mailbox is opened read-only and messages are fetched with BODY.PEEK, so nothing is marked as read, moved or sent.
Only emails that look job-related AND mention a company you applied to are looked at further; for those, the subject,
sender and a short snippet are stored in the application's timeline so every automatic change can be checked.
"""
from __future__ import annotations

import asyncio
import email
import email.header
import email.utils
import hashlib
import imaplib
import json
import logging
import re
import time
from html import unescape

from .. import db
from . import groq_client

log = logging.getLogger(__name__)

IMAP_DEFAULT = "imap.gmail.com"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

JOBISH = re.compile(
    r"application|applied|applying|candida|interview|assessment|assignment|coding (?:test|challenge|round)|hackerrank|"
    r"hackerearth|codility|offer|position|internship|\bintern\b|recruit|hiring|talent|unfortunately|regret|shortlist|"
    r"bewerbung|praktikum|werkstudent|vorstellungsgespr|absage|zusage|einladung|leider", re.I)

# order matters: a rejection often starts with "thank you for applying"
RULES: list[tuple[str, re.Pattern]] = [
    ("rejected", re.compile(
        r"unfortunately|regret to inform|not (?:to )?(?:be )?mov(?:e|ing) forward|decided to (?:pursue|proceed|move forward) with other|"
        r"other candidates|position has been filled|not been selected|were not selected|won.t be (?:moving|proceeding)|"
        r"will not be (?:moving|proceeding)|no longer under consideration|leider.{0,120}(?:nicht|absage|anderen? (?:kandidat|bewerber))|"
        r"\babsage\b", re.I | re.S)),
    ("offer", re.compile(
        r"offer letter|pleased to offer|(?:delighted|happy|pleased|excited) to (?:offer|extend)|congratulations.{0,80}(?:selected|offer)|"
        r"\bzusage\b|freuen uns.{0,80}(?:anzubieten|zusage)", re.I | re.S)),
    ("interview", re.compile(
        r"\binterview|schedule (?:a|an|your) (?:call|chat|meeting|conversation)|calendly\.com|next round|"
        r"vorstellungsgespr|kennenlerngespr|einladung zu(?:m|r)? (?:gespr|interview)", re.I)),
    ("assessment", re.compile(
        r"assessment|coding (?:test|challenge|round)|online test|take[- ]home|technical assignment|hackerrank|hackerearth|"
        r"codility|mettl|testgorilla", re.I)),
    ("applied", re.compile(
        r"(?:thank you|thanks) for (?:your )?(?:applying|application|interest)|application (?:has been |was )?(?:received|submitted|sent)|"
        r"(?:we.ve|we have) received your application|your application (?:to|for)|eingangsbest|"
        r"(?:vielen )?dank für (?:ihre|deine) bewerbung", re.I)),
]

RANK = {"not_applied": 0, "applied": 1, "assessment": 2, "interview": 3, "rejected": 4, "withdrawn": 4, "offer": 5}
COMPANY_NOISE = {"gmbh", "pvt", "ltd", "private", "limited", "inc", "ag", "se", "llp", "llc", "technologies", "technology",
                 "solutions", "services", "india", "germany", "deutschland", "group", "co", "kg", "the", "and", "&", "e.v.",
                 "ev", "gruppe", "holding", "international", "software", "labs", "systems", "consulting", "company"}


# ---------------------------------------------------------------- pure helpers (unit-tested)
def classify_rules(subject: str, body: str) -> str | None:
    text = f"{subject}\n{body}"
    for status, rx in RULES:
        if rx.search(text):
            return status
    return None


def should_update(current: str, new: str) -> bool:
    """Only move forward. A rejection can arrive at any stage (except after an offer); nothing overrides offer/withdrawn."""
    current = current or "not_applied"
    if new == current or new not in RANK or current in ("offer", "withdrawn"):
        return False
    if current == "rejected":
        return False
    if new == "rejected":
        return True
    return RANK[new] > RANK[current]


def company_keys(company: str) -> list[str]:
    c = re.sub(r"[^a-z0-9äöüß& ]+", " ", (company or "").lower())
    words = [w for w in c.split() if w not in COMPANY_NOISE]
    keys = []
    if words:
        keys.append(" ".join(words))
        if len(words[0]) >= 4:
            keys.append(words[0])
    return list(dict.fromkeys(k for k in keys if len(k) >= 3))


def match_score(msg: dict, app: dict) -> int:
    """How strongly an email points at an application (0 = unrelated)."""
    keys = company_keys(app.get("job_company") or "")
    if not keys:
        return 0
    sender = (msg["from"] or "").lower()
    head = f"{msg['subject']}".lower()
    body = (msg["body"] or "").lower()[:6000]
    score = 0
    for k in keys:
        pat = r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])"
        if re.search(pat, sender) or k.replace(" ", "") in sender.split("@")[-1]:
            score = max(score, 3)
        elif re.search(pat, head):
            score = max(score, 3)
        elif re.search(pat, body):
            score = max(score, 2)
    if score:
        title_words = [w for w in re.findall(r"[a-z]{4,}", (app.get("job_title") or "").lower())
                       if w not in {"intern", "internship", "praktikum", "praktikant", "student", "werkstudent"}]
        if title_words and any(w in head or w in body for w in title_words):
            score += 1
    return score


def html_to_text(s: str) -> str:
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", unescape(s)).strip()


def _decode(v: str | None) -> str:
    if not v:
        return ""
    try:
        return str(email.header.make_header(email.header.decode_header(v)))
    except Exception:
        return v


def parse_message(raw: bytes) -> dict:
    m = email.message_from_bytes(raw)
    plain, html = [], []
    for part in m.walk() if m.is_multipart() else [m]:
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html") or part.get_filename():
            continue
        try:
            payload = part.get_payload(decode=True) or b""
            text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        except Exception:
            continue
        (plain if ctype == "text/plain" else html).append(text)
    body = "\n".join(plain) if plain else html_to_text("\n".join(html))
    try:
        ts = email.utils.parsedate_to_datetime(m.get("Date")).timestamp()
    except Exception:
        ts = time.time()
    subject, sender = _decode(m.get("Subject")), _decode(m.get("From"))
    mid = (m.get("Message-ID") or "").strip() or hashlib.sha1(f"{sender}{subject}{ts}".encode()).hexdigest()
    return {"id": mid, "subject": subject, "from": sender, "date": ts, "body": re.sub(r"\s+", " ", body)[:8000]}


# ---------------------------------------------------------------- IMAP
def fetch_messages(host: str, user: str, password: str, since_ts: float, limit: int = 400) -> list[dict]:
    t = time.gmtime(since_ts)
    since = f"{t.tm_mday:02d}-{MONTHS[t.tm_mon - 1]}-{t.tm_year}"
    conn = imaplib.IMAP4_SSL(host, 993, timeout=40)
    try:
        conn.login(user, password)
        conn.select("INBOX", readonly=True)
        typ, data = conn.search(None, "SINCE", since)
        ids = (data[0] or b"").split()[-limit:] if typ == "OK" else []
        out = []
        for i in range(0, len(ids), 40):
            typ, rows = conn.fetch(b",".join(ids[i:i + 40]), "(BODY.PEEK[]<0.40000>)")
            for row in rows or []:
                if isinstance(row, tuple) and len(row) == 2:
                    try:
                        out.append(parse_message(row[1]))
                    except Exception as e:  # one odd message must not stop the sync
                        log.warning("could not parse a message: %s", e)
        return out
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def test_login(host: str, user: str, password: str) -> None:
    conn = imaplib.IMAP4_SSL(host, 993, timeout=30)
    try:
        conn.login(user, password)
    finally:
        try:
            conn.logout()
        except Exception:
            pass


# ---------------------------------------------------------------- AI check for ambiguous / important emails
AI_PROMPT = """You read one email from a job seeker's inbox and decide whether it is an update about one of their applications.
Return ONLY JSON: {"app_id": int|null, "status": "applied"|"assessment"|"interview"|"offer"|"rejected"|"none",
"confidence": number 0-1, "reason": str}
- status "applied" = confirmation that an application was received; "assessment" = online test / assignment invitation;
  "interview" = invitation or scheduling of an interview/call; "offer" = job/internship offer; "rejected" = rejection.
- Use "none" for newsletters, job alerts / recommendations ("jobs you may like"), marketing, or anything not about one of
  the listed applications. Job-alert emails listing many openings are always "none".
- app_id must be one of the candidate ids, chosen by company (and role if several match). Be strict."""


async def classify_ai(msg: dict, candidates: list[dict], hint: str | None) -> dict | None:
    cands = [{"app_id": a["id"], "company": a.get("job_company"), "role": a.get("job_title")} for a in candidates[:8]]
    user = (f"CANDIDATE APPLICATIONS: {json.dumps(cands, ensure_ascii=False)}\nRULE-BASED GUESS: {hint}\n\n"
            f"FROM: {msg['from']}\nSUBJECT: {msg['subject']}\n\n{msg['body'][:3000]}")
    try:
        out = await groq_client.chat_json(AI_PROMPT, user, temperature=0.0, max_tokens=600)
    except Exception as e:
        log.warning("AI email classification failed: %s", e)
        return None
    return out if isinstance(out, dict) else None


# ---------------------------------------------------------------- orchestration
async def process(user_id: int, messages: list[dict], use_ai: bool) -> dict:
    apps = [a for a in db.list_applications(user_id) if a.get("job_company")]
    result = {"checked": len(messages), "job_related": 0, "updated": [], "unmatched": 0}
    for msg in sorted(messages, key=lambda m: m["date"]):
        if db.email_seen(user_id, msg["id"]):
            continue
        db.mark_email_seen(user_id, msg["id"])
        if not JOBISH.search(f"{msg['subject']} {msg['body'][:3000]}"):
            continue
        result["job_related"] += 1
        # only applications that existed when the email arrived (old mail from the same company is ignored)
        scored = sorted(((match_score(msg, a), a) for a in apps if msg["date"] >= (a["created_at"] or 0) - 86400),
                        key=lambda x: -x[0])
        scored = [(s, a) for s, a in scored if s > 0]
        if not scored:
            result["unmatched"] += 1
            continue
        rule = classify_rules(msg["subject"], msg["body"])
        top = [a for s, a in scored if s == scored[0][0]]
        app, status, reason, conf = None, None, "matched keywords", 0.0
        if use_ai:
            ai = await classify_ai(msg, [a for _, a in scored], rule)
            if ai and ai.get("status") not in (None, "none") and ai.get("app_id") in {a["id"] for _, a in scored}:
                app = next(a for _, a in scored if a["id"] == ai["app_id"])
                status, reason, conf = ai["status"], ai.get("reason") or "", float(ai.get("confidence") or 0)
                if conf < 0.6:
                    continue  # unsure: leave the status alone
            elif ai is not None:
                continue  # the model looked and said it isn't an update
            # ai is None (call failed): fall back to the rules below
        if app is None and rule and len(top) == 1 and scored[0][0] >= 3:
            app, status, reason, conf = top[0], rule, f"rule: {rule}", 0.7
        if not app or not status:
            continue
        current = app.get("track") or "not_applied"
        if not should_update(current, status):
            continue
        detail = {"subject": msg["subject"][:200], "from": msg["from"][:120], "date": msg["date"],
                  "snippet": msg["body"][:240], "reason": reason[:200], "confidence": round(conf, 2)}
        db.set_track(app["id"], status, source="email", detail=detail)
        app["track"] = status
        result["updated"].append({"app_id": app["id"], "company": app.get("job_company"), "role": app.get("job_title"),
                                  "from": current, "to": status, "subject": msg["subject"][:120]})
    return result


def config(user_id: int) -> dict:
    g = lambda k, d="": db.get_user_setting(user_id, k, d)  # noqa: E731
    return {"address": g("EMAIL_ADDRESS"), "host": g("EMAIL_IMAP_HOST", IMAP_DEFAULT), "has_password": bool(g("EMAIL_APP_PASSWORD")),
            "auto": g("EMAIL_AUTO_SYNC", "1") == "1", "last_sync": float(g("EMAIL_LAST_SYNC", "0") or 0),
            "last_result": json.loads(g("EMAIL_LAST_RESULT", "null") or "null")}


async def sync(user_id: int) -> dict:
    addr = db.get_user_setting(user_id, "EMAIL_ADDRESS")
    pw = db.get_user_setting(user_id, "EMAIL_APP_PASSWORD")
    host = db.get_user_setting(user_id, "EMAIL_IMAP_HOST", IMAP_DEFAULT) or IMAP_DEFAULT
    if not addr or not pw:
        raise ValueError("Connect your email first (address + app password).")
    last = float(db.get_user_setting(user_id, "EMAIL_LAST_SYNC", "0") or 0)
    apps = db.list_applications(user_id)
    first_app = min((a["created_at"] for a in apps), default=time.time())
    since = (last - 2 * 86400) if last else max(first_app - 86400, time.time() - 60 * 86400)
    try:
        messages = await asyncio.to_thread(fetch_messages, host, addr, pw, since)
    except imaplib.IMAP4.error as e:
        raise ValueError(f"Email login failed ({e}). Use an app password, not your normal password, and check IMAP is enabled.")
    use_ai = bool(db.get_setting("GROQ_API_KEY"))
    result = await process(user_id, messages, use_ai)
    result["at"] = time.time()
    db.set_user_setting(user_id, "EMAIL_LAST_SYNC", str(result["at"]))
    db.set_user_setting(user_id, "EMAIL_LAST_RESULT", json.dumps(result))
    return result


async def auto_sync_loop(every_seconds: int = 1800) -> None:
    """Background: check each connected inbox every 30 minutes while the app is running."""
    while True:
        await asyncio.sleep(every_seconds)
        for u in db.list_users():
            c = config(u["id"])
            if c["auto"] and c["address"] and c["has_password"]:
                try:
                    await sync(u["id"])
                except Exception as e:
                    log.warning("auto email sync for user %s failed: %s", u["id"], e)
                    db.set_user_setting(u["id"], "EMAIL_LAST_RESULT", json.dumps({"error": str(e), "at": time.time()}))
