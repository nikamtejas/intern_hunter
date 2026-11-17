"""Tiny SQLite layer. Everything is stored locally in data/app.db."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

DATA_DIR = Path(os.getenv("INTERN_HUNTER_DATA", Path(__file__).resolve().parent.parent / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "app.db"

_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    source TEXT, title TEXT, company TEXT, location TEXT, country TEXT,
    url TEXT, posted_at TEXT, description TEXT, extra TEXT,
    created_at REAL
);
CREATE TABLE IF NOT EXISTS profile (id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT, updated_at REAL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT, status TEXT, error TEXT,
    resume TEXT, ats TEXT, cover_letter TEXT, options TEXT,
    created_at REAL, updated_at REAL
);
-- one row per person using the app; each has their own profile, searches, resumes and tracker
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS profiles (user_id INTEGER PRIMARY KEY, data TEXT, raw_text TEXT, updated_at REAL);
CREATE TABLE IF NOT EXISTS user_settings (user_id INTEGER, key TEXT, value TEXT, PRIMARY KEY (user_id, key));
CREATE TABLE IF NOT EXISTS searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, params TEXT, job_ids TEXT,
    per_source TEXT, warnings TEXT, created_at REAL
);
-- application timeline: status changes (manual or from email) and notes
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, app_id INTEGER, user_id INTEGER, kind TEXT,
    old TEXT, new TEXT, source TEXT, detail TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS email_seen (user_id INTEGER, msg_id TEXT, PRIMARY KEY (user_id, msg_id));
-- sign-in sessions; only a hash of the cookie token is stored
CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id INTEGER, created_at REAL, expires_at REAL);
"""

# application-tracking stages, in pipeline order
TRACK_STAGES = ["not_applied", "applied", "assessment", "interview", "offer", "rejected", "withdrawn"]
APP_COLUMNS = {"user_id": "INTEGER DEFAULT 1", "track": "TEXT DEFAULT 'not_applied'", "applied_at": "REAL", "notes": "TEXT",
               "prep": "TEXT", "followup": "TEXT"}
USER_COLUMNS = {"password_hash": "TEXT", "salt": "TEXT", "avatar": "TEXT"}
SEARCH_COLUMNS = {"watch": "INTEGER DEFAULT 0", "last_run": "REAL", "new_ids": "TEXT"}
SESSION_DAYS = 30


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with _lock, connect() as c:
        c.executescript(SCHEMA)
        have = {r["name"] for r in c.execute("PRAGMA table_info(applications)")}
        for col, decl in APP_COLUMNS.items():
            if col not in have:
                c.execute(f"ALTER TABLE applications ADD COLUMN {col} {decl}")
        have_s = {r["name"] for r in c.execute("PRAGMA table_info(searches)")}
        for col, decl in SEARCH_COLUMNS.items():
            if col not in have_s:
                c.execute(f"ALTER TABLE searches ADD COLUMN {col} {decl}")
        have_u = {r["name"] for r in c.execute("PRAGMA table_info(users)")}
        for col, decl in USER_COLUMNS.items():
            if col not in have_u:
                c.execute(f"ALTER TABLE users ADD COLUMN {col} {decl}")
        # migrate the old single-profile install into user 1
        if not c.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            old = c.execute("SELECT data FROM profile WHERE id=1").fetchone()
            name = (json.loads(old["data"]).get("name") if old else "") or "My profile"
            c.execute("INSERT INTO users(id,name,created_at) VALUES(1,?,?)", (name, time.time()))
            if old:
                raw = c.execute("SELECT value FROM settings WHERE key='RAW_RESUME_TEXT'").fetchone()
                c.execute("INSERT OR IGNORE INTO profiles(user_id,data,raw_text,updated_at) VALUES(1,?,?,?)",
                          (old["data"], raw["value"] if raw else "", time.time()))
        c.commit()


def execute(sql: str, params: tuple = ()) -> int:
    with _lock, connect() as c:
        cur = c.execute(sql, params)
        c.commit()
        return cur.lastrowid


def query(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    with _lock, connect() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


# ---------- settings (global: API keys, scraper tuning) ----------
def get_setting(key: str, default: str | None = None) -> str | None:
    rows = query("SELECT value FROM settings WHERE key=?", (key,))
    if rows and rows[0]["value"]:
        return rows[0]["value"]
    return os.getenv(key, default) or default


def set_setting(key: str, value: str) -> None:
    execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


# ---------- users ----------
def list_users() -> list[dict]:
    """Public list for the sign-in screen: names only, plus whether a password protects the profile."""
    return query("""SELECT u.id, u.name, u.created_at, (u.password_hash IS NOT NULL) AS locked,
                           (SELECT count(*) FROM applications a WHERE a.user_id=u.id) AS applications
                    FROM users u ORDER BY u.id""")


# ---------- passwords & sessions ----------
def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 240_000).hex()


def set_password(user_id: int, password: str) -> None:
    salt = secrets.token_bytes(16)
    execute("UPDATE users SET password_hash=?, salt=? WHERE id=?", (_hash_password(password, salt), salt.hex(), user_id))
    execute("DELETE FROM sessions WHERE user_id=?", (user_id,))  # a new password signs out other devices


def has_password(user_id: int) -> bool:
    rows = query("SELECT password_hash FROM users WHERE id=?", (user_id,))
    return bool(rows and rows[0]["password_hash"])


def check_password(user_id: int, password: str) -> bool:
    rows = query("SELECT password_hash, salt FROM users WHERE id=?", (user_id,))
    if not rows or not rows[0]["password_hash"]:
        return False
    return hmac.compare_digest(rows[0]["password_hash"], _hash_password(password, bytes.fromhex(rows[0]["salt"])))


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    execute("INSERT INTO sessions(token_hash,user_id,created_at,expires_at) VALUES(?,?,?,?)",
            (hashlib.sha256(token.encode()).hexdigest(), user_id, now, now + SESSION_DAYS * 86400))
    return token


def session_user(token: str | None) -> int | None:
    if not token:
        return None
    rows = query("SELECT user_id FROM sessions WHERE token_hash=? AND expires_at>?",
                 (hashlib.sha256(token.encode()).hexdigest(), time.time()))
    return rows[0]["user_id"] if rows and user_exists(rows[0]["user_id"]) else None


def delete_session(token: str | None) -> None:
    if token:
        execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))


def user_exists(user_id: int) -> bool:
    return bool(query("SELECT 1 FROM users WHERE id=?", (user_id,)))


def first_user_id() -> int:
    rows = query("SELECT id FROM users ORDER BY id LIMIT 1")
    return rows[0]["id"] if rows else execute("INSERT INTO users(name,created_at) VALUES(?,?)", ("My profile", time.time()))


def create_user(name: str) -> int:
    return execute("INSERT INTO users(name,created_at) VALUES(?,?)", (name.strip() or "New profile", time.time()))


def rename_user(user_id: int, name: str) -> None:
    execute("UPDATE users SET name=? WHERE id=?", (name.strip(), user_id))


def delete_user(user_id: int) -> None:
    for sql in ("DELETE FROM applications WHERE user_id=?", "DELETE FROM events WHERE user_id=?",
                "DELETE FROM searches WHERE user_id=?", "DELETE FROM profiles WHERE user_id=?",
                "DELETE FROM user_settings WHERE user_id=?", "DELETE FROM email_seen WHERE user_id=?",
                "DELETE FROM sessions WHERE user_id=?",
                "DELETE FROM users WHERE id=?"):
        execute(sql, (user_id,))


def get_user_setting(user_id: int, key: str, default: str = "") -> str:
    rows = query("SELECT value FROM user_settings WHERE user_id=? AND key=?", (user_id, key))
    return rows[0]["value"] if rows and rows[0]["value"] is not None else default


def set_user_setting(user_id: int, key: str, value: str) -> None:
    execute("""INSERT INTO user_settings(user_id,key,value) VALUES(?,?,?)
               ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value""", (user_id, key, value))


# ---------- profile ----------
def get_profile(user_id: int = 1) -> dict | None:
    rows = query("SELECT data FROM profiles WHERE user_id=?", (user_id,))
    return json.loads(rows[0]["data"]) if rows and rows[0]["data"] else None


def save_profile(data: dict, user_id: int = 1) -> None:
    execute(
        """INSERT INTO profiles(user_id,data,updated_at) VALUES(?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at""",
        (user_id, json.dumps(data), time.time()),
    )
    name = data.get("name", "").strip()
    if name and query("SELECT 1 FROM users WHERE id=? AND name IN ('My profile','New profile','')", (user_id,)):
        rename_user(user_id, name)


def get_raw_text(user_id: int) -> str:
    rows = query("SELECT raw_text FROM profiles WHERE user_id=?", (user_id,))
    return (rows[0]["raw_text"] or "") if rows else ""


def set_raw_text(user_id: int, text: str) -> None:
    execute("""INSERT INTO profiles(user_id,raw_text,updated_at) VALUES(?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET raw_text=excluded.raw_text""", (user_id, text[:30000], time.time()))


# ---------- jobs ----------
def upsert_job(job: dict) -> None:
    execute(
        """INSERT INTO jobs(id,source,title,company,location,country,url,posted_at,description,extra,created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET title=excluded.title, company=excluded.company, location=excluded.location,
             url=excluded.url, posted_at=excluded.posted_at,
             description=CASE WHEN length(coalesce(excluded.description,'')) > length(coalesce(jobs.description,''))
                              THEN excluded.description ELSE jobs.description END,
             extra=excluded.extra""",
        (job["id"], job["source"], job["title"], job.get("company"), job.get("location"), job.get("country"),
         job.get("url"), job.get("posted_at"), job.get("description") or "", json.dumps(job.get("extra") or {}), time.time()),
    )


def get_job(job_id: str) -> dict | None:
    rows = query("SELECT * FROM jobs WHERE id=?", (job_id,))
    if not rows:
        return None
    j = rows[0]
    j["extra"] = json.loads(j["extra"] or "{}")
    return j


def get_jobs(job_ids: list[str]) -> list[dict]:
    by_id = {}
    for i in range(0, len(job_ids), 500):
        chunk = job_ids[i:i + 500]
        for j in query(f"SELECT * FROM jobs WHERE id IN ({','.join('?' * len(chunk))})", tuple(chunk)):
            j["extra"] = json.loads(j["extra"] or "{}")
            by_id[j["id"]] = j
    return [by_id[i] for i in job_ids if i in by_id]


def set_job_extra(job_id: str, extra: dict) -> None:
    execute("UPDATE jobs SET extra=? WHERE id=?", (json.dumps(extra), job_id))


def set_job_description(job_id: str, description: str) -> None:
    execute("UPDATE jobs SET description=? WHERE id=?", (description, job_id))


# ---------- searches (per user history) ----------
def save_search(user_id: int, params: dict, job_ids: list[str], per_source: dict, warnings: list[str]) -> int:
    sid = execute("INSERT INTO searches(user_id,params,job_ids,per_source,warnings,created_at) VALUES(?,?,?,?,?,?)",
                  (user_id, json.dumps(params), json.dumps(job_ids), json.dumps(per_source), json.dumps(warnings), time.time()))
    # keep the 30 most recent per user (watched searches are always kept)
    execute("""DELETE FROM searches WHERE user_id=? AND coalesce(watch,0)=0 AND id NOT IN
               (SELECT id FROM searches WHERE user_id=? ORDER BY id DESC LIMIT 30)""", (user_id, user_id))
    return sid


def _decode_search(s: dict) -> dict:
    for k in ("params", "job_ids", "per_source", "warnings", "new_ids"):
        s[k] = json.loads(s.get(k) or "null")
    s["new_ids"] = s["new_ids"] or []
    return s


def list_searches(user_id: int, limit: int = 12) -> list[dict]:
    rows = [_decode_search(s) for s in query("SELECT * FROM searches WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit))]
    for s in rows:
        s["count"] = len(s.pop("job_ids") or [])
        s["new_count"] = len(s.pop("new_ids") or [])
    return rows


def set_watch(user_id: int, search_id: int, watch: bool) -> None:
    execute("UPDATE searches SET watch=? WHERE id=? AND user_id=?", (1 if watch else 0, search_id, user_id))


def watched_searches(user_id: int | None = None) -> list[dict]:
    sql, params = "SELECT * FROM searches WHERE watch=1", ()
    if user_id is not None:
        sql, params = sql + " AND user_id=?", (user_id,)
    return [_decode_search(s) for s in query(sql + " ORDER BY id DESC", params)]


def record_watch_run(search_id: int, found_ids: list[str]) -> list[str]:
    """Remember a refresh of a watched search; returns the job ids never seen in it before."""
    s = _decode_search(query("SELECT * FROM searches WHERE id=?", (search_id,))[0])
    seen = set(s["job_ids"] or [])
    fresh = [i for i in found_ids if i not in seen]
    now = time.time()
    new_ids = [n for n in s["new_ids"] if now - n["at"] < 7 * 86400] + [{"id": i, "at": now} for i in fresh]
    execute("UPDATE searches SET job_ids=?, new_ids=?, last_run=? WHERE id=?",
            (json.dumps((fresh + list(s["job_ids"] or []))[:600]), json.dumps(new_ids[-150:]), now, search_id))
    return fresh


def clear_new(user_id: int) -> None:
    execute("UPDATE searches SET new_ids='[]' WHERE user_id=?", (user_id,))


def get_search(user_id: int, search_id: int) -> dict | None:
    rows = query("SELECT * FROM searches WHERE id=? AND user_id=?", (search_id, user_id))
    return _decode_search(rows[0]) if rows else None


# ---------- applications ----------
def create_application(job_id: str, options: dict, user_id: int = 1) -> int:
    now = time.time()
    return execute(
        "INSERT INTO applications(job_id,status,options,created_at,updated_at,user_id,track) VALUES(?,?,?,?,?,?,?)",
        (job_id, "queued", json.dumps(options), now, now, user_id, "not_applied"),
    )


def update_application(app_id: int, **fields: Any) -> None:
    cols, vals = [], []
    for k, v in fields.items():
        cols.append(f"{k}=?")
        vals.append(json.dumps(v) if isinstance(v, (dict, list)) else v)
    cols.append("updated_at=?")
    vals.append(time.time())
    execute(f"UPDATE applications SET {', '.join(cols)} WHERE id=?", (*vals, app_id))


def _decode_app(a: dict) -> dict:
    for k in ("resume", "ats", "options", "prep", "followup"):
        a[k] = json.loads(a[k]) if a.get(k) else None
    return a


def get_application(app_id: int) -> dict | None:
    rows = query("SELECT * FROM applications WHERE id=?", (app_id,))
    return _decode_app(rows[0]) if rows else None


def list_applications(user_id: int = 1) -> list[dict]:
    rows = query(
        """SELECT a.*, j.title AS job_title, j.company AS job_company, j.location AS job_location,
                  j.country AS job_country, j.url AS job_url, j.source AS job_source
           FROM applications a LEFT JOIN jobs j ON j.id = a.job_id WHERE a.user_id=? ORDER BY a.id DESC""",
        (user_id,),
    )
    return [_decode_app(r) for r in rows]


def delete_application(app_id: int) -> None:
    execute("DELETE FROM applications WHERE id=?", (app_id,))
    execute("DELETE FROM events WHERE app_id=?", (app_id,))


def set_track(app_id: int, track: str, source: str = "manual", detail: dict | None = None) -> None:
    a = get_application(app_id)
    if not a or track not in TRACK_STAGES:
        return
    old = a.get("track") or "not_applied"
    fields: dict[str, Any] = {"track": track}
    if track != "not_applied" and not a.get("applied_at"):
        fields["applied_at"] = time.time()
    update_application(app_id, **fields)
    if old != track:
        add_event(app_id, a.get("user_id") or 1, "status", old, track, source, detail)


def add_event(app_id: int, user_id: int, kind: str, old: str | None, new: str | None, source: str, detail: dict | None = None) -> None:
    execute("INSERT INTO events(app_id,user_id,kind,old,new,source,detail,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (app_id, user_id, kind, old, new, source, json.dumps(detail or {}), time.time()))


def list_events(user_id: int, app_id: int | None = None, limit: int = 50) -> list[dict]:
    sql = """SELECT e.*, j.title AS job_title, j.company AS job_company FROM events e
             LEFT JOIN applications a ON a.id=e.app_id LEFT JOIN jobs j ON j.id=a.job_id WHERE e.user_id=?"""
    params: tuple = (user_id,)
    if app_id is not None:
        sql += " AND e.app_id=?"
        params += (app_id,)
    rows = query(sql + " ORDER BY e.id DESC LIMIT ?", params + (limit,))
    for r in rows:
        r["detail"] = json.loads(r["detail"] or "{}")
    return rows


def email_seen(user_id: int, msg_id: str) -> bool:
    return bool(query("SELECT 1 FROM email_seen WHERE user_id=? AND msg_id=?", (user_id, msg_id)))


def mark_email_seen(user_id: int, msg_id: str) -> None:
    execute("INSERT OR IGNORE INTO email_seen(user_id,msg_id) VALUES(?,?)", (user_id, msg_id))
