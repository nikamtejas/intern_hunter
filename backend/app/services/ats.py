"""Deterministic ATS-style scorer.

Real ATS systems (Workday, Greenhouse, SAP SuccessFactors, Lever, Naukri RMS...) differ,
but they share the same core checks. This scorer models them:

  Hard-skill keyword coverage ........ 40
  Tools / other JD keywords ........... 15
  Soft skills ......................... 5
  Job-title alignment ................. 10
  Required sections & contact info .... 10
  Parse-safe formatting & length ...... 10
  Impact (action verbs, numbers) ...... 10
                                       ---
                                       100
"""
from __future__ import annotations

import re

from .profile_schema import flatten_text

SYNONYMS = {
    "javascript": ["js", "ecmascript"], "typescript": ["ts"], "python": ["py"],
    "machine learning": ["ml"], "artificial intelligence": ["ai"], "deep learning": ["dl"],
    "natural language processing": ["nlp"], "computer vision": ["cv"],
    "react": ["react.js", "reactjs"], "node.js": ["node", "nodejs"], "vue": ["vue.js", "vuejs"],
    "next.js": ["nextjs"], "postgresql": ["postgres"], "mongodb": ["mongo"],
    "amazon web services": ["aws"], "google cloud": ["gcp", "google cloud platform"],
    "microsoft azure": ["azure"], "kubernetes": ["k8s"], "ci/cd": ["cicd", "continuous integration"],
    "c++": ["cpp"], "c#": ["csharp"], "microsoft excel": ["excel", "ms excel"],
    "power bi": ["powerbi"], "user experience": ["ux"], "user interface": ["ui"],
    "rest api": ["restful", "rest apis", "restful api"], "sql": ["mysql", "structured query language"],
    "data analysis": ["data analytics", "datenanalyse"], "communication": ["kommunikation", "communication skills"],
    "teamwork": ["team player", "teamfähigkeit", "collaboration"], "problem solving": ["problem-solving"],
    "german": ["deutsch"], "english": ["englisch"], "scikit-learn": ["sklearn"], "tensorflow": ["tf"],
    "object oriented programming": ["oop", "object-oriented"], "version control": ["git"],
}
SYNONYMS.update({
    "microsoft office": ["ms office", "office 365", "microsoft 365"], "dashboards": ["dashboard"],
    "full stack": ["full-stack", "fullstack"], "data validation": ["validated data", "validating data"],
})
# reverse index
_CANON: dict[str, str] = {}
for k, vs in SYNONYMS.items():
    _CANON[k] = k
    for v in vs:
        _CANON[v] = k

COMMON_SKILLS = [
    "python", "java", "javascript", "typescript", "c++", "c#", "c", "go", "rust", "kotlin", "swift", "php", "ruby", "r",
    "matlab", "scala", "sql", "nosql", "html", "css", "react", "angular", "vue", "next.js", "node.js", "express",
    "django", "flask", "fastapi", "spring", "spring boot", ".net", "flutter", "react native", "android", "ios",
    "pandas", "numpy", "scikit-learn", "tensorflow", "pytorch", "keras", "opencv", "machine learning", "deep learning",
    "natural language processing", "computer vision", "llm", "generative ai", "data analysis", "data science",
    "data visualization", "statistics", "tableau", "power bi", "microsoft excel", "git", "github", "docker",
    "kubernetes", "linux", "amazon web services", "microsoft azure", "google cloud", "ci/cd", "rest api", "graphql",
    "postgresql", "mysql", "mongodb", "redis", "firebase", "figma", "sap", "salesforce", "jira", "agile", "scrum",
    "seo", "digital marketing", "social media marketing", "content writing", "canva", "adobe photoshop",
    "autocad", "solidworks", "catia", "ansys", "simulink", "embedded systems", "plc", "iot", "cybersecurity",
    "networking", "testing", "selenium", "unit testing", "spark", "hadoop", "airflow", "etl", "big data",
    "financial modeling", "accounting", "market research", "business analysis", "project management",
    "communication", "teamwork", "problem solving", "leadership", "time management", "english", "german",
]
SOFT_SKILLS = {"communication", "teamwork", "problem solving", "leadership", "time management", "adaptability",
               "critical thinking", "creativity", "attention to detail", "presentation", "ownership", "initiative"}

ACTION_VERBS = set("""achieved analysed analyzed architected automated built collaborated completed configured conducted
created debugged delivered deployed designed developed drove engineered enhanced established evaluated executed
implemented improved increased integrated launched led managed migrated modeled optimized organized performed
planned presented prototyped published reduced refactored researched resolved scaled shipped simplified solved
streamlined supported tested trained transformed visualized wrote coordinated contributed maintained documented
entwickelt implementiert optimiert analysiert erstellt geleitet""".split())

_WORD = re.compile(r"[a-z0-9+#./-]+")


def norm(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[‐-―]", "-", s)
    s = re.sub(r"\s+", " ", s)
    return _CANON.get(s, s)


def _variants(term: str) -> list[str]:
    t = norm(term)
    vs = {t, *SYNONYMS.get(t, [])}
    # light plural/stem handling
    for v in list(vs):
        if v.endswith("s") and len(v) > 4:
            vs.add(v[:-1])
        else:
            vs.add(v + "s")
    return [v for v in vs if v]


# filler words job ads wrap around a skill ("dashboard creation", "SQL basics", "Power BI modeling")
FILLER = {"development", "creation", "skills", "skill", "basics", "basic", "modeling", "modelling", "knowledge", "experience",
          "concepts", "fundamentals", "techniques", "principles", "proficiency", "understanding", "familiarity", "working",
          "hands-on", "strong", "good", "solid", "advanced", "formulas", "ability", "abilities", "expertise", "practices"}


def _phrase_forms(term: str) -> list[str]:
    """The term itself, its hyphen/space twins, and its core once filler words are dropped."""
    t = norm(term)
    forms = {t, t.replace("-", " "), t.replace(" ", "-")}
    words = t.replace("-", " ").split()
    core = [w for w in words if w not in FILLER]
    if core and len(core) < len(words):
        c = " ".join(core)
        forms |= {norm(c), c, c.replace(" ", "-")}
    return [f for f in forms if f]


def _contains(text_l: str, term: str) -> bool:
    for form in _phrase_forms(term):
        for v in _variants(form):
            pat = r"(?<![a-z0-9])" + re.escape(v) + r"(?![a-z0-9])"
            if re.search(pat, text_l):
                return True
    return False


def local_keywords(jd: str) -> dict:
    """Fallback keyword extraction without the LLM."""
    jl = (jd or "").lower()
    found = [s for s in COMMON_SKILLS if _contains(jl, s)]
    hard = [s for s in found if s not in SOFT_SKILLS and s not in ("english", "german")]
    soft = [s for s in found if s in SOFT_SKILLS]
    langs = [s for s in ("english", "german") if s in found or _contains(jl, s)]
    return {"hard_skills": hard, "tools": [], "soft_skills": soft, "languages": langs, "other_keywords": [], "job_title": ""}


def _coverage(text_l: str, terms: list[str]) -> tuple[list[str], list[str]]:
    seen, matched, missing = set(), [], []
    for t in terms:
        n = norm(t)
        if not n or n in seen:
            continue
        seen.add(n)
        (matched if _contains(text_l, n) else missing).append(t)
    return matched, missing


def _bullets(resume: dict) -> list[str]:
    out = []
    for e in resume.get("experience", []):
        out += e.get("bullets", [])
    for p in resume.get("projects", []):
        out += p.get("bullets", [])
    return out


def score(resume: dict, keywords: dict, job_title: str = "") -> dict:
    text = flatten_text(resume)
    tl = text.lower()
    hard = list(dict.fromkeys((keywords.get("hard_skills") or [])))
    tools = list(dict.fromkeys((keywords.get("tools") or []) + (keywords.get("other_keywords") or [])))
    soft = list(dict.fromkeys(keywords.get("soft_skills") or []))
    langs = keywords.get("languages") or []

    h_m, h_x = _coverage(tl, hard)
    t_m, t_x = _coverage(tl, tools + langs)
    s_m, s_x = _coverage(tl, soft)

    def ratio(m, x, empty=1.0):
        n = len(m) + len(x)
        return len(m) / n if n else empty

    breakdown = {}
    breakdown["hard_skills"] = round(40 * ratio(h_m, h_x), 1)
    breakdown["keywords"] = round(15 * ratio(t_m, t_x), 1)
    breakdown["soft_skills"] = round(5 * ratio(s_m, s_x), 1)

    # Title alignment: core words of the job title appear in headline/summary/experience titles
    title = keywords.get("job_title") or job_title or ""
    core = [w for w in _WORD.findall(title.lower()) if len(w) > 2 and w not in
            {"intern", "internship", "praktikum", "praktikant", "werkstudent", "working", "student", "the", "and", "for",
             "mwd", "m/w/d", "f/m/d", "remote", "paid", "unpaid", "months", "month", "summer", "winter"}]
    head = " ".join([resume.get("headline", ""), resume.get("summary", "")]).lower()
    if core:
        hits = sum(1 for w in core if w in head)
        breakdown["title_match"] = round(10 * min(1.0, hits / max(1, min(len(core), 3))), 1)
    else:
        breakdown["title_match"] = 10.0 if resume.get("headline") else 6.0

    # Sections & contact
    sec = 0.0
    sec += 2 if re.search(r"@", resume.get("email", "")) else 0
    sec += 1.5 if re.search(r"\d{6,}", re.sub(r"\D", "", resume.get("phone", ""))) else 0
    sec += 1 if (resume.get("linkedin") or resume.get("github") or resume.get("portfolio")) else 0
    sec += 1 if len(resume.get("summary", "")) > 40 else 0
    sec += 1.5 if resume.get("education") else 0
    sk = resume.get("skills", {})
    sec += 2 if (sk.get("technical") or sk.get("tools")) else 0
    sec += 1 if (resume.get("experience") or resume.get("projects")) else 0
    breakdown["sections"] = sec

    # Formatting & length (our templates are single-column, text-based → parse-safe by design)
    words = len(text.split())
    # 6 pts: single-column text template with standard headings (always true for our renderer)
    # 4 pts: length suited to an internship resume
    if 250 <= words <= 750:
        fmt = 10.0
    elif 150 <= words <= 1000:
        fmt = 8.5
    else:
        fmt = 7.0
    breakdown["formatting"] = fmt

    # Impact
    bl = _bullets(resume)
    if bl:
        verbs = sum(1 for b in bl if (b.split() or [""])[0].lower().strip("•-*,.") in ACTION_VERBS)
        nums = sum(1 for b in bl if re.search(r"\d", b))
        breakdown["impact"] = round(5 * verbs / len(bl) + 5 * min(1.0, (nums / len(bl)) / 0.5), 1)
    else:
        breakdown["impact"] = 0.0

    total = round(sum(breakdown.values()), 1)
    tips = []
    if h_x:
        tips.append("Missing hard skills from the job description: " + ", ".join(h_x[:12]))
    if t_x:
        tips.append("Missing keywords/tools: " + ", ".join(t_x[:12]))
    if breakdown["impact"] < 7 and bl:
        tips.append("Start more bullets with action verbs and add numbers (%, users, time saved).")
    if breakdown["title_match"] < 10:
        tips.append(f"Mirror the job title in your headline (e.g. '{title or job_title}').")
    if sec < 10:
        tips.append("Make sure email, phone, a LinkedIn/GitHub link, summary, education and skills are all present.")
    if fmt < 10:
        tips.append(f"Resume length is {words} words; aim for 250–750 so it fits one page (add project/experience detail from your profile).")

    return {
        "score": total,
        "breakdown": breakdown,
        "matched": {"hard_skills": h_m, "keywords": t_m, "soft_skills": s_m},
        "missing": {"hard_skills": h_x, "keywords": t_x, "soft_skills": s_x},
        "word_count": words,
        "tips": tips,
    }


# A skill the profile proves through a more specific one: MongoDB experience IS NoSQL experience, so the
# resume may say "MongoDB (NoSQL)". Used only to decide what may be written, never to score the resume.
IMPLIED_BY = {
    "nosql": ["mongodb", "redis", "cassandra", "dynamodb", "firestore", "firebase", "couchdb", "neo4j"],
    "relational databases": ["sql", "mysql", "postgresql", "sqlite", "oracle"], "rdbms": ["mysql", "postgresql", "sqlite", "oracle"],
    "databases": ["sql", "mysql", "postgresql", "mongodb", "sqlite"],
    "data visualization": ["tableau", "power bi", "matplotlib", "seaborn", "plotly"],
    "bi tools": ["tableau", "power bi", "looker"], "cloud": ["amazon web services", "microsoft azure", "google cloud", "bigquery"],
    "version control": ["git", "github"], "containerization": ["docker", "kubernetes"],
    "frontend": ["react", "angular", "vue", "html"], "backend": ["node.js", "django", "flask", "fastapi", "spring", "express"],
    "oop": ["java", "c++", "c#"], "object oriented programming": ["java", "c++", "c#"],
}


def has_evidence(profile_text_l: str, term: str) -> bool:
    if _contains(profile_text_l, term):
        return True
    return any(_contains(profile_text_l, x) for x in IMPLIED_BY.get(norm(term), []))


def present_in_profile(profile_text: str, terms: list[str]) -> tuple[list[str], list[str]]:
    """Split missing JD terms into those the candidate genuinely has (somewhere in the
    full profile) vs. true gaps they would need to add themselves."""
    pl = profile_text.lower()
    have, gaps = [], []
    for t in terms:
        (have if has_evidence(pl, t) else gaps).append(t)
    return have, gaps
