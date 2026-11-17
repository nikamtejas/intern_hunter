"""Tailor a resume to one job: analyse JD → write → (score + humanize review → edit)* → best version."""
from __future__ import annotations

import copy
import json
import re
import logging

from . import ats, groq_client, humanize, prompts, quality, render
from .profile_schema import flatten_text, normalize

log = logging.getLogger(__name__)

KW_KEYS = ("hard_skills", "tools", "soft_skills", "languages", "education", "other_keywords", "must_have", "nice_to_have")
# job-ad nouns that aren't skills anyone "learns" ("data records", "data accuracy")
NOT_LEARNABLE = re.compile(r"\b(?:records?|accuracy|consistency|integrity|quality|insights?|reports?|stakeholders?|"
                           r"requirements|documentation|deadlines?|english|german|degree|bachelor|master)\b", re.I)
# industry / outcome / trait phrases the model sometimes lists although no recruiter searches for them
DESCRIPTOR = re.compile(r"\b(?:it services|it consulting|life sciences?|healthcare|enterprise systems?|scalable|data[- ]driven|"
                        r"insights?|agility|team support|production support|clients?|industry|domain knowledge|"
                        r"data (?:records|accuracy|consistency|integrity)|"
                        r"fast[- ]paced|self[- ]motivated|go[- ]getter)\b", re.I)


async def analyze_job(job_title: str, description: str) -> dict:
    """JD analysis with Groq, merged with a local keyword scan as a safety net."""
    local = ats.local_keywords(description)
    try:
        kw = await groq_client.chat_json(
            prompts.JD_ANALYST, f"JOB TITLE: {job_title}\n\nJOB POSTING:\n{description[:12000]}", temperature=0.0
        )
    except groq_client.GroqError:
        raise
    except Exception as e:
        log.warning("JD analysis failed, using local keywords: %s", e)
        kw = {}
    out = {k: list(dict.fromkeys(str(x) for x in (kw.get(k) or []) if str(x).strip() and not DESCRIPTOR.search(str(x))))
           for k in KW_KEYS}
    # must-haves count as hard skills for scoring if the model forgot to list them there
    seen = {ats.norm(x) for k in ("hard_skills", "tools", "soft_skills", "languages", "other_keywords") for x in out[k]}
    for m in out["must_have"]:
        if ats.norm(m) not in seen:
            out["hard_skills"].append(m)
            seen.add(ats.norm(m))
    for k in ("hard_skills", "soft_skills", "languages"):
        for s in local.get(k, []):
            if ats.norm(s) not in seen:
                out[k].append(s)
                seen.add(ats.norm(s))
    out["job_title"] = kw.get("job_title") or job_title
    out["role_summary"] = kw.get("role_summary", "")
    out["company_context"] = kw.get("company_context", "")
    return out


def _context(profile: dict, job: dict, jd: dict, country: str, language: str) -> str:
    lang_rule = ("LANGUAGE: Write the resume in natural GERMAN (Lebenslauf). Keep technical terms and tool names in English. "
                 "Section content in German, e.g. 'Entwickelte …'." if language == "de" else "LANGUAGE: Write in English.")
    return (
        f"{prompts.REGION_RULES.get(country, '')}\n{lang_rule}\n\n"
        f"JOB ANALYSIS:\n{json.dumps(jd, ensure_ascii=False)}\n\n"
        f"JOB TITLE: {job.get('title')}\nCOMPANY: {job.get('company')}\nLOCATION: {job.get('location')}\n"
        f"JOB POSTING:\n{(job.get('description') or '')[:8000]}\n\n"
        f"MASTER PROFILE (only source of facts):\n{json.dumps(profile, ensure_ascii=False)}"
    )


async def write(profile, job, jd, country, language) -> dict:
    out = await groq_client.chat_json(prompts.WRITER, _context(profile, job, jd, country, language),
                                      temperature=0.35, max_tokens=6000)
    return normalize(out)


async def edit(draft, profile, job, jd, country, language, editor_notes: list[str]) -> dict:
    user = (_context(profile, job, jd, country, language)
            + f"\n\nDRAFT RESUME:\n{json.dumps(draft, ensure_ascii=False)}\n\nEDITOR NOTES (fix all):\n"
            + "\n".join(f"- {n}" for n in editor_notes))
    out = await groq_client.chat_json(prompts.EDITOR, user, temperature=0.25, max_tokens=6000)
    return normalize(out)


def _guard_skills(resume: dict, profile_text: str) -> list[str]:
    """Remove any skill that does not appear anywhere in the master profile."""
    removed = []
    pl = profile_text.lower()
    for k in ("technical", "tools", "soft"):
        keep = []
        for s in resume["skills"].get(k, []):
            (keep if ats.has_evidence(pl, s) else removed).append(s)
        resume["skills"][k] = list(dict.fromkeys(keep))
    return removed


# technologies a model likes to "round out" a resume with; checked in every line, not only the skills list
EXTRA_TECH = ["express", "rest api", "graphql", "postgresql", "next.js", "tailwind", "redux", "typescript", "kubernetes",
              "amazon web services", "microsoft azure", "google cloud", "jenkins", "terraform", "spring boot", "angular", "vue",
              "django", "flask", "fastapi", "react", "react native", "flutter", "firebase", "redis", "kafka", "spark", "hadoop",
              "airflow", "tensorflow", "pytorch", "keras", "opencv", "langchain", "microservices", "ci/cd", "github actions",
              "webpack", "babel", "npm", "jira", "snowflake", "databricks", "dbt", "looker", "sas", "spss", "matlab", "solidity",
              "vba", "excel vba", "macros", "power query", "dax", "looker studio", "google analytics", "alteryx", "qlik",
              "seaborn", "plotly", "scipy", "statsmodels", "nltk", "spacy", "hugging face", "aws lambda", "s3", "ec2",
              "html", "css", "bootstrap", "sass", "jquery", "php", "laravel", "wordpress", "kotlin", "swift", "unity"]
# common English words that are also skill names: never treated as fabricated
AMBIGUOUS = {"c", "r", "go", "testing", "networking", "statistics", "accounting", "agile", "scrum", "leadership", "seo",
             "communication", "teamwork", "problem solving", "time management", "english", "german", "iot", "etl", "sap"}


def _tech_vocab(jd: dict, job_title: str = "") -> list[str]:
    """Technologies to verify. Words of the job title are exempt: naming the target role is not a skill claim."""
    title_l = f"{job_title} {jd.get('job_title', '')}".lower()
    terms = ats.COMMON_SKILLS + EXTRA_TECH + [t for k in ("hard_skills", "tools", "other_keywords", "must_have", "nice_to_have")
                                              for t in jd.get(k) or []]
    out, seen = [], set()
    for t in terms:
        n = ats.norm(t)
        if (n and n not in seen and n not in AMBIGUOUS and n not in ats.SOFT_SKILLS and len(n) > 1
                and not ats._contains(title_l, n)):
            seen.add(n)
            out.append(t)
    return out


def _unverified(text: str, vocab: list[str], profile_l: str) -> list[str]:
    tl = text.lower()
    return [t for t in vocab if ats._contains(tl, t) and not ats.has_evidence(profile_l, t)]


# a number not glued to letters, and not a version after a tech name ("Python 3", "HTML 5", "Angular 17")
_NUM = re.compile(r"(?<![A-Za-z0-9.])(?<!python )(?<!html )(?<!css )(?<!angular )(?<!java )(?<!php )(?<!vue )(?<!web )"
                  r"(?<!level )(?<!ios )(?<!android )\d+(?:[.,]\d+)?(?![A-Za-z0-9])", re.I)


def _invented_numbers(text: str, profile_l: str) -> list[str]:
    """Figures (99%, 30%, 1,000 users) that appear nowhere in the profile — models love to make these up."""
    known = set(_NUM.findall(profile_l))
    return [n for n in _NUM.findall(text) if n not in known and n.replace(",", "") not in known]


def _entry_key(e: dict) -> str:
    return ats.norm(f"{e.get('title') or e.get('name') or ''} {e.get('company', '')}")


def _entry_text(e: dict) -> str:
    return " ".join([e.get("title", ""), e.get("name", ""), e.get("company", ""), " ".join(e.get("tech", [])),
                     *e.get("bullets", [])]).lower()


def _enforce_truth(resume: dict, profile: dict, profile_text: str, vocab: list[str]) -> list[str]:
    """Strip every claim the master profile can't back up, in the summary, headline, bullets and project tech lists:
    - technologies the profile never mentions;
    - technologies moved onto an experience/project whose original entry doesn't mention them;
    - numbers/percentages that appear nowhere in the profile.
    Offending bullets are dropped (an entry left empty falls back to its original, truthful bullets);
    offending summary sentences are dropped. Returns what was removed."""
    pl = profile_text.lower()
    removed: list[str] = []
    own_skills = [x for k in ("technical", "tools") for x in profile.get("skills", {}).get(k, [])]
    entry_vocab = list(dict.fromkeys(vocab + own_skills))
    by_key = {_entry_key(e): e for sec in ("experience", "projects") for e in profile.get(sec, [])}
    by_title = {ats.norm(e.get("title") or e.get("name") or ""): e for sec in ("experience", "projects") for e in profile.get(sec, [])}
    for sec in ("experience", "projects"):
        for e in resume.get(sec, []):
            orig = by_key.get(_entry_key(e)) or by_title.get(ats.norm(e.get("title") or e.get("name") or ""))
            # tools must be backed by THIS entry when we know which original it came from
            local = _entry_text(orig) if orig else pl

            def problems(text: str) -> list[str]:
                bad = _unverified(text, vocab, pl)
                if orig:
                    bad += [t for t in entry_vocab if t not in bad and ats._contains(text.lower(), t)
                            and not ats.has_evidence(local, t)]
                bad += [f"the number {n}" for n in _invented_numbers(text, pl)]
                return bad

            if sec == "projects":
                bad = [t for t in e.get("tech", []) if not ats.has_evidence(local, t)]
                if bad:
                    e["tech"] = [t for t in e["tech"] if t not in bad]
                    removed += [f"{t} (tech list of {e.get('name')})" for t in bad]
            keep = []
            for b in e.get("bullets", []):
                bad = problems(b)
                if bad:
                    removed.append(f"{', '.join(dict.fromkeys(bad))} in “{b[:70]}…”")
                else:
                    keep.append(b)
            if len(keep) < 2 and orig:  # too little left: fall back to the original wording
                keep += [b for b in orig.get("bullets", []) if b not in keep and not problems(b)][: 3 - len(keep)]
            e["bullets"] = keep
    if resume.get("summary"):
        sentences = re.split(r"(?<=[.!?])\s+", resume["summary"])
        good = [x for x in sentences if not _unverified(x, vocab, pl) and not _invented_numbers(x, pl)]
        if len(good) < len(sentences):
            removed += [f"summary sentence: “{x[:80]}”" for x in sentences if x not in good]
            resume["summary"] = " ".join(good) or profile.get("summary", "")
    if resume.get("headline"):
        bad = _unverified(resume["headline"], vocab, pl)
        if bad:
            parts = [x for x in re.split(r"\s*[|·,]\s*", resume["headline"]) if x and not _unverified(x, vocab, pl)]
            resume["headline"] = " | ".join(parts[:1]) + (" | " + " · ".join(parts[1:]) if len(parts) > 1 else "")
            removed.append(f"headline: {', '.join(bad)}")
    return removed


def _potential(resume: dict, jd: dict, job_title: str, gaps: list[str]) -> dict:
    """What the score would be if the candidate genuinely has the missing skills and adds real numbers —
    shown as a to-do list, never written into the resume automatically."""
    with_skills = copy.deepcopy(resume)
    with_skills["learning"] = list(with_skills.get("learning", [])) + list(gaps)
    s1 = ats.score(with_skills, jd, job_title)["score"]
    with_numbers = copy.deepcopy(with_skills)
    for sec in ("experience", "projects"):
        for e in with_numbers.get(sec, []):
            e["bullets"] = [b if re.search(r"\d", b) else b + " 1" for b in e.get("bullets", [])]
    s2 = ats.score(with_numbers, jd, job_title)["score"]
    return {"with_missing_skills": s1, "with_skills_and_numbers": s2}


def _tidy(resume: dict, jd: dict, job_title: str) -> None:
    """Final polish: no duplicate bullets or skills, consistent capitalisation, always a headline."""
    key = lambda t: re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()  # noqa: E731
    for sec in ("experience", "projects"):
        for e in resume.get(sec, []):
            seen, out = set(), []
            for b in (x.strip().rstrip(".").strip() for x in e.get("bullets", [])):  # one style: no trailing periods
                if key(b) not in seen:
                    seen.add(key(b))
                    out.append(b)
            e["bullets"] = out
    for ed in resume.get("education", []):
        ed["details"] = [x.strip().rstrip(".").strip() for x in ed.get("details", []) if x.strip()]
    sk = resume.setdefault("skills", {})
    soft_named = [x for x in sk.get("technical", []) + sk.get("tools", []) if ats.norm(x) in ats.SOFT_SKILLS
                  or ats.norm(x) in {"attention to detail", "analytical thinking", "analytical skills", "critical thinking"}]
    if soft_named:  # soft skills listed as technical ones: move them to their own row
        for k in ("technical", "tools"):
            sk[k] = [x for x in sk.get(k, []) if x not in soft_named]
        sk["soft"] = list(sk.get("soft", [])) + soft_named
    seen = set()
    for k in ("technical", "tools", "soft"):
        out = []
        for x in resume.get("skills", {}).get(k, []):
            if ats.norm(x) not in seen:
                seen.add(ats.norm(x))
                out.append(x[:1].upper() + x[1:] if x[:1].islower() and k == "soft" else x)
        resume.setdefault("skills", {})[k] = out
    if resume.get("headline"):  # spoken languages belong in LANGUAGES, not in the headline's skill list
        head, *rest = re.split(r"\s*\|\s*", resume["headline"], maxsplit=1)
        if rest:
            keep = [x for x in re.split(r"\s*[·,]\s*", rest[0]) if x and ats.norm(x) not in
                    {"english", "german", "hindi", "marathi", "french", "spanish"}]
            resume["headline"] = head + (" | " + " · ".join(keep) if keep else "")
    if not resume.get("headline", "").strip():
        title = jd.get("job_title") or job_title
        sk = resume.get("skills", {})
        tl = flatten_text(resume).lower()
        top = [x for x in jd.get("must_have", []) + jd.get("hard_skills", []) + jd.get("tools", []) if ats._contains(tl, x)]
        top = list(dict.fromkeys(top or sk.get("technical", [])))[:3]
        resume["headline"] = title + (" | " + " · ".join(top) if top else "")


# meaning-preserving cuts tried (in order) when a bullet spills a word or two onto a second line
_TIGHTEN = [(r"\bin order to\b", "to"), (r"\bthe development of\b", "development of"), (r"\b(?:successfully|effectively|"
            r"efficiently|various|different|key|interactive|actively)\s+", ""), (r"\butili[sz](?:e|ed|ing)\b", "used"),
            (r",\s+and\b", " and"), (r"\b(?:the|a|an)\s+", "")]  # never drops tool names or parentheses: those are ATS keywords


def _tighten(text: str, layout) -> str:
    """Pull a 1–2 word orphan back onto one line with small, meaning-preserving cuts; return the text unchanged otherwise."""
    lines, fill = render.measure_bullet(text, layout)
    if lines != 2 or fill > 0.25:
        return text
    t = text
    for pat, rep in _TIGHTEN:
        t = re.sub(pat, rep, t, flags=re.I).strip()
        t = t[:1].upper() + t[1:]
        if render.measure_bullet(t, layout)[0] == 1:
            return t
    return text


_STOP = set("""a an the and or of to for in on with by from at as into using via that this its their our than then
also across over under per while within""".split())
_PADDING = ("key", "daily", "weekly", "monthly", "critical", "executive", "various", "high", "robust", "overall", "core",
            "major", "multiple", "numerous", "comprehensive", "end-to-end", "high-volume", "mission-critical", "strategic")
_DANGLING = _STOP | {"key", "daily", "weekly", "executive", "critical", "various", "high", "more", "better", "new", "data"}


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9+#.\-]{3,}", text.lower()) if w not in _STOP}


def grounded(new: str, old: str, facts: str) -> bool:
    """A resized bullet may only use words from its original wording or that entry's profile facts (light stemming),
    must read as a finished sentence, and must not repeat a word as padding."""
    known = _content_words(old) | _content_words(facts)
    stems = {w[:5] for w in known}
    extra = [w for w in _content_words(new) if w not in known and w[:5] not in stems]
    words = re.findall(r"[A-Za-z][\w\-]*", new)
    if not words or words[-1].lower() in _DANGLING:
        return False
    nl, ol, fl = f" {new.lower()} ", f" {old.lower()} ", f" {facts.lower()} "
    # filler a model adds just to reach a length: allowed only if the original or the facts already used it
    padded = any(re.search(rf"\b{w}\b", nl) and not re.search(rf"\b{w}\b", ol + fl) for w in _PADDING)
    padded |= any(nl.count(f" {w} ") > ol.count(f" {w} ") + 1 for w in ("data", "real-time"))
    return len(extra) <= 1 and not padded


async def fit_lines(resume: dict, profile: dict, profile_text: str, vocab: list[str], country: str, language: str,
                    passes: int = 2) -> int:
    """Make bullets end at the right margin (one or two full lines): one small AI call per pass for the ragged ones,
    each rewrite measured and truth-checked before it is kept; then deterministic tightening of orphan words.
    Returns how many bullets still end short."""
    _, layout, _ = render.fit_one_page(resume, country, language)
    by_key = {_entry_key(e): e for sec in ("experience", "projects") for e in profile.get(sec, [])}
    for _ in range(passes):
        items = []
        for sec in ("experience", "projects"):
            for e in resume.get(sec, []):
                orig = by_key.get(_entry_key(e)) or {}
                facts = " ".join([orig.get("title") or orig.get("name") or "", " ".join(orig.get("tech", [])), *orig.get("bullets", [])])
                for i, b in enumerate(e.get("bullets", [])):
                    lines, fill = render.measure_bullet(b, layout)
                    if fill < render.FLUSH_AT:
                        items.append((e, i, b, lines, facts or flatten_text(profile)[:600]))
        if not items:
            return 0
        per_line = render.bullet_lines(resume, country, language, layout)[0]["chars_per_line"]
        req = []
        for k, (e, i, b, lines, facts) in enumerate(items):
            one_line = len(b) < per_line * 1.35  # short single lines grow to one full line; spills go to two full lines
            lo, hi = (per_line - 5, per_line - 1) if one_line else (2 * per_line - 9, 2 * per_line - 3)
            req.append({"id": k, "text": b, "target": f"{lo}-{hi} characters", "entry_facts": facts[:700]})
        try:
            out = await groq_client.chat_json(prompts.LINE_FITTER, json.dumps({"bullets": req}, ensure_ascii=False),
                                              temperature=0.2, max_tokens=3000)
        except Exception as ex:  # quota or bad output: keep the finished resume, just skip this polish step
            log.warning("line fitting skipped: %s", ex)
            break
        for item in out.get("bullets", []) if isinstance(out, dict) else []:
            k = item.get("id")
            if not isinstance(k, int) or k >= len(items) or not str(item.get("text", "")).strip():
                continue
            e, i, old, _, _ = items[k]
            new = str(item["text"]).strip().rstrip(".")
            trial = copy.deepcopy(resume)
            t_entry = next(x for sec in ("experience", "projects") for x in trial.get(sec, []) if _entry_key(x) == _entry_key(e))
            t_entry["bullets"][i] = new
            _enforce_truth(trial, profile, profile_text, vocab)
            if new in t_entry["bullets"] and render.measure_bullet(new, layout)[1] > render.measure_bullet(old, layout)[1] - 0.01 \
                    and humanize.find_cliches(new) == [] and grounded(new, old, items[k][4]):
                e["bullets"][i] = new
    short = 0
    for sec in ("experience", "projects"):
        for e in resume.get(sec, []):
            e["bullets"] = [_tighten(b, layout) for b in e.get("bullets", [])]
            short += sum(1 for b in e["bullets"] if render.measure_bullet(b, layout)[1] < render.FLUSH_AT)
    return short


def _restore_facts(resume: dict, profile: dict) -> None:
    """Contact details and links always come from the profile, never the model; never lose whole sections."""
    for k in ("name", "email", "phone", "location", "linkedin", "github", "portfolio", "links", "extras", "learning"):
        resume[k] = copy.deepcopy(profile.get(k))
    by_name = {ats.norm(p.get("name", "")): p for p in profile.get("projects", [])}
    for p in resume.get("projects", []):
        src = by_name.get(ats.norm(p.get("name", "")))
        if src:  # repo / live URLs are copied verbatim so the model can't drop or mangle them
            p["link"], p["live"] = src.get("link", ""), src.get("live", "")
    for k in ("languages", "education", "certifications"):
        if not resume.get(k) and profile.get(k):
            resume[k] = copy.deepcopy(profile[k])


def _quality(score: float, review: dict) -> float:
    return score - 1.0 * len(review["cliches"]) - 0.4 * len(review["repeated_verbs"]) - 0.3 * len(review["short_bullets"])


async def build(profile: dict, job: dict, country: str, language: str = "en", target: float = 95,
                max_rounds: int = 3, raw_resume_text: str = "", on_progress=None, jd: dict | None = None,
                auto_learning: bool = False) -> dict:
    say = on_progress or (lambda m: None)
    profile = normalize(profile)
    # evidence comes only from what the candidate HAS done; "currently learning" items never back up a claim
    profile_text = flatten_text({**profile, "learning": []}) + "\n" + (raw_resume_text or "")

    if not jd:  # callers pass a cached analysis so regenerating the same job scores against the same keywords
        say("Analysing job description")
        jd = await analyze_job(job.get("title", ""), job.get("description") or job.get("title", ""))
    vocab = _tech_vocab(jd, job.get("title", ""))
    all_terms = jd["hard_skills"] + jd["tools"] + jd["other_keywords"] + jd["languages"] + jd["soft_skills"]
    proven, true_gaps = ats.present_in_profile(profile_text, all_terms)
    never_claim = list(dict.fromkeys(true_gaps))  # includes skills the candidate is only learning
    auto_added: list[str] = []
    if auto_learning:
        # the job's missing technical skills go into the labelled "Currently learning" row (the candidate's stated plan);
        # they still can never appear as experience in bullets, summary or headline
        learning_l = " ".join(profile.get("learning", [])).lower()
        order = jd.get("must_have", []) + jd.get("hard_skills", []) + jd.get("tools", []) + jd.get("other_keywords", [])
        tech_gaps = {ats.norm(g) for g in true_gaps}
        for t in order:
            n = ats.norm(t)
            if (n in tech_gaps and n not in ats.SOFT_SKILLS and not NOT_LEARNABLE.search(t) and not ats._contains(learning_l, t)
                    and n not in {ats.norm(x) for x in auto_added}):
                auto_added.append(t)
        auto_added = auto_added[:10]
        profile = {**profile, "learning": list(profile.get("learning", [])) + auto_added}
    learning_l = " ".join(profile.get("learning", [])).lower()
    true_gaps = [g for g in true_gaps if not ats._contains(learning_l, g)]
    # tell the model up front what it may and may not claim, so it tailors within the truth instead of being undone
    jd_ctx = {**jd, "USE_THESE_KEYWORDS (proven by the profile — use each at least once, exact spelling)": list(dict.fromkeys(proven)),
              "NEVER_CLAIM (not in the profile — must not appear anywhere)": never_claim}

    say("Writing tailored resume")
    resume = await write(profile, job, jd_ctx, country, language)
    best = None
    history = []
    for rnd in range(1, max_rounds + 1):
        _restore_facts(resume, profile)
        removed = _guard_skills(resume, profile_text)
        fabricated = _enforce_truth(resume, profile, profile_text, vocab)
        _tidy(resume, jd, job.get("title", ""))
        # score what will actually be on the page: fit to one A4 page, dropping the least job-relevant content
        resume, layout, trimmed = render.fit_one_page(resume, country, language, all_terms)
        too_short = layout["scale"] >= render.MAX_SCALE and layout["space"] > 1.5  # page only full thanks to big gaps
        ragged = [x for x in render.bullet_lines(resume, country, language, layout) if x["fill"] < render.FLUSH_AT]
        result = ats.score(resume, jd, job.get("title", ""))
        review = humanize.review(resume)
        q = _quality(result["score"], review) - 0.25 * len(ragged)
        history.append({"round": rnd, "score": result["score"], "style_issues": review["count"], "ragged_bullets": len(ragged),
                        "cliches": review["cliches"], "removed_unverified_skills": removed, "removed_unverified_claims": fabricated,
                        "trimmed_to_fit": trimmed})
        if best is None or q > best[0]:
            best = (q, copy.deepcopy(resume), result, review, trimmed, fabricated)
        if result["score"] >= target and review["count"] == 0 and len(ragged) <= 2:
            break
        if rnd >= 3 and result["score"] <= history[-2]["score"] + 0.5:
            break  # the last edit didn't help; further passes just burn API quota
        if rnd == max_rounds:
            break
        # ---- build editor notes
        missing = result["missing"]["hard_skills"] + result["missing"]["keywords"] + result["missing"]["soft_skills"]
        have, _ = ats.present_in_profile(profile_text, missing)
        notes = humanize.notes(review)
        if fabricated:
            notes.insert(0, "These claims were REMOVED because the master profile does not mention them — do not use these "
                         "technologies anywhere (summary, headline, bullets, tech lists); rewrite with what the profile states: "
                         + "; ".join(fabricated[:12]))
        if have:
            notes.insert(0, "Missing keywords that ARE in the master profile — work each into the summary/skills and a bullet: "
                         + ", ".join(have))
        notes += [t for t in result["tips"] if not t.startswith("Missing")]
        if ragged:
            n = ragged[0]["chars_per_line"]
            notes.append(
                f"LINE LENGTH — every bullet must end at the right margin: ONE full line = {n - 6}-{n} characters, or TWO full "
                f"lines = {2 * n - 10}-{2 * n} characters. These bullets stop short; lengthen them with concrete detail already in "
                "the profile (method, tools used in that entry, purpose, audience) or tighten them, never adding new facts or numbers: "
                + " | ".join(f"[{x['entry'][:30]}] “{x['text'][:60]}…” is {x['chars']} chars" for x in ragged[:10]))
        if too_short:
            notes.append("The resume is too short to fill one page. Add substance from the master profile: 3-4 bullets per "
                         "experience and project (method, tools, result), more relevant projects, coursework, certifications and "
                         "achievements. Aim for 480-600 words. Never invent facts.")
        if trimmed:
            notes.append(f"The resume ran over one page and {len(trimmed)} item(s) were cut. Keep it to one page: "
                         "tighter bullets (max 2 lines), at most 3-4 bullets per entry, drop the least relevant items yourself.")
        if not notes:
            break  # nothing actionable left that can be fixed truthfully
        say(f"Editing & humanizing (pass {rnd}/{max_rounds - 1})")
        resume = await edit(resume, profile, job, jd_ctx, country, language, notes)

    _, best_resume, best_result, best_review, best_trimmed, best_fabricated = best
    say("Fitting bullets to full lines")
    ragged_left = await fit_lines(best_resume, profile, profile_text, vocab, country, language)
    best_resume, _, _ = render.fit_one_page(best_resume, country, language, all_terms)
    best_result = ats.score(best_resume, jd, job.get("title", ""))
    final_missing = {ats.norm(x) for v in best_result["missing"].values() for x in v}
    true_gaps = [g for g in true_gaps if ats.norm(g) in final_missing]
    note = None
    if best_result["score"] < target and true_gaps:
        note = ("The score is held back by skills the job asks for that aren't in your profile. "
                "Add them only if you really have them, then regenerate.")
    return {
        "resume": best_resume,
        "keywords": jd,
        "ats": best_result,
        "style": best_review,
        "gaps": true_gaps,
        "potential": _potential(best_resume, jd, job.get("title", ""), true_gaps),
        "auto_learning": auto_added,
        "checks": quality.check(best_resume, best_result, country, language),
        "history": history,
        "target": target,
        "reached_target": best_result["score"] >= target,
        "note": note,
        "trimmed": best_trimmed,
        "removed_claims": best_fabricated,
        "ragged_bullets": ragged_left,
    }
