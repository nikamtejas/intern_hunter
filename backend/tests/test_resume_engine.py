"""End-to-end resume pipeline with a fake Groq (no network)."""
import asyncio
import io
import json
import os
import tempfile

os.environ.setdefault("INTERN_HUNTER_DATA", tempfile.mkdtemp())

import httpx
import respx
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app import db
from app.services import ats, render, tailor
from app.services.groq_client import URL as GROQ_URL
from app.services.profile_schema import normalize

PROFILE = normalize({
    "name": "Priya Sharma", "email": "priya@example.com", "phone": "+91 98765 43210", "location": "Pune, India",
    "links": [{"label": "GitHub", "url": "github.com/priya"}],
    "summary": "Computer science student interested in data.",
    "education": [{"institution": "COEP Technological University", "degree": "B.Tech", "field": "Computer Engineering",
                   "start": "2022", "end": "2026", "grade": "CGPA 8.7/10"}],
    "experience": [{"title": "Data Analyst Intern", "company": "FinServe", "start": "May 2025", "end": "Jul 2025",
                    "bullets": ["Built dashboards in Tableau for 5 regional managers",
                                "Cleaned 200k rows of loan data using Pandas and SQL"]}],
    "projects": [{"name": "Churn Predictor", "tech": ["Python", "scikit-learn", "Docker"],
                  "bullets": ["Trained a random forest model reaching 87% accuracy", "Deployed with Docker and FastAPI"]}],
    "skills": {"technical": ["Python", "SQL", "Pandas", "NumPy", "Machine Learning", "Statistics"], "tools": ["Tableau", "Git"],
               "soft": ["Communication", "Teamwork"]},
    "languages": [{"name": "English", "level": "C1"}, {"name": "German", "level": "A2"}],
})

JD = """Data Science Intern. Requirements: Python, SQL, Pandas, NumPy, scikit-learn, machine learning, statistics,
Tableau or Power BI, Docker, Git, AWS. Good communication and teamwork."""

KEYWORDS = {"job_title": "Data Science Intern",
            "hard_skills": ["Python", "SQL", "Pandas", "NumPy", "scikit-learn", "Machine Learning", "Statistics"],
            "tools": ["Tableau", "Power BI", "Docker", "Git", "AWS"], "soft_skills": ["Communication", "Teamwork"],
            "languages": [], "education": ["Computer Science"], "other_keywords": []}


def tailored(fabricate=False):
    r = json.loads(json.dumps(PROFILE))
    r["headline"] = "Data Science Intern | Python, SQL, Machine Learning"
    r["summary"] = ("Data Science Intern candidate and Computer Engineering student with hands-on Python, SQL, Pandas, "
                    "NumPy and scikit-learn experience in machine learning and statistics.")
    r["experience"][0]["bullets"] = ["Built 4 Tableau dashboards used by 5 regional managers to track loan KPIs",
                                     "Cleaned 200k rows of loan data with Pandas, NumPy and SQL, cutting report prep time"]
    r["projects"][0]["bullets"] = ["Trained a scikit-learn random forest machine learning model reaching 87% accuracy",
                                   "Deployed the model with Docker and FastAPI, versioned with Git"]
    r["skills"]["technical"] = ["Python", "SQL", "Pandas", "NumPy", "scikit-learn", "Machine Learning", "Statistics"]
    if fabricate:
        r["skills"]["tools"] += ["AWS", "Kubernetes"]  # NOT in profile -> must be removed
    r["email"] = "hacked@evil.com"  # must be restored from profile
    return r


calls = {"writer": 0, "editor": 0}


def groq_router(fabricate=True):
    def handler(request):
        body = json.loads(request.content)
        sys = body["messages"][0]["content"]
        if "configures ATS searches" in sys:
            out = KEYWORDS
        elif "campus recruiter" in sys:
            out = {"overall": 64, "verdict": "Solid base, bullets need outcomes.", "strengths": ["Relevant projects"],
                   "issues": [{"severity": "high", "section": "Experience", "problem": "No metrics", "fix": "Add numbers"}],
                   "bullet_rewrites": [{"original": "Did dashboards", "improved": "Built Tableau dashboards for [N] managers", "why": "specific"}],
                   "missing_sections": [], "keywords_to_consider": ["Power BI"], "ats_risks": []}
        elif "cover letters" in sys:
            out = {"subject": "Application: Data Science Intern", "greeting": "Dear Hiring Manager,",
                   "paragraphs": ["P1", "P2", "P3"], "closing": "Best regards,"}
        elif "resize resume bullets" in sys:
            out = {"bullets": []}
        elif "convert a resume" in sys:
            out = PROFILE
        elif "strict resume editor" in sys:
            out = tailored(False)
            calls["editor"] += 1
        else:
            out = tailored(fabricate)
            calls["writer"] += 1
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(out)}}]})
    return handler


def test_ats_scoring_and_synonyms():
    kw = {"hard_skills": ["JavaScript", "React", "Node.js"], "tools": [], "soft_skills": [], "languages": [], "other_keywords": []}
    r = normalize({"skills": {"technical": ["JS", "ReactJS", "node"]}})
    res = ats.score(r, kw)
    assert res["matched"]["hard_skills"] == ["JavaScript", "React", "Node.js"]
    # 'C' must not match inside other words
    assert not ats._contains("excellent communication", "c")


@respx.mock
def test_tailor_build_guards_fabrication_and_reaches_target():
    db.init()
    db.set_setting("GROQ_API_KEY", "test")
    respx.post(GROQ_URL).mock(side_effect=groq_router(fabricate=True))
    job = {"title": "Data Science Intern", "company": "Acme", "location": "Bengaluru", "description": JD}
    out = asyncio.run(tailor.build(PROFILE, job, "india", target=95, max_rounds=2))
    tools = out["resume"]["skills"]["tools"]
    assert "Kubernetes" not in tools and "AWS" not in tools  # fabricated skills stripped
    assert out["resume"]["email"] == "priya@example.com"  # contact restored
    assert set(out["gaps"]) >= {"Power BI", "AWS"}  # true gaps reported to the user
    print("score", out["ats"]["score"], out["ats"]["breakdown"])
    assert out["ats"]["score"] >= 88  # max reachable here: Power BI & AWS are true gaps
    assert out["ats"]["missing"]["keywords"] == ["Power BI", "AWS"]


def test_render_pdf_docx_text_extractable():
    r = tailored()
    for country, lang in (("india", "en"), ("germany", "de")):
        pdf = render.resume_pdf(r, country, lang)
        text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
        assert "Priya Sharma" in text and "scikit-learn" in text and "Tableau" in text
        assert ("EDUCATION" in text) if lang == "en" else ("AUSBILDUNG" in text and "SPRACHEN" in text)
        assert len(PdfReader(io.BytesIO(pdf)).pages) == 1
        docx_bytes = render.resume_docx(r, country, lang)
        import docx
        d = docx.Document(io.BytesIO(docx_bytes))
        assert any("Priya Sharma" in p.text for p in d.paragraphs)
        assert len(d.tables) == 0  # ATS-safe: no tables in DOCX
    cl = {"subject": "Bewerbung", "greeting": "Sehr geehrte Damen und Herren,", "paragraphs": ["Ich bewerbe mich für ₹ und ü."],
          "closing": "Mit freundlichen Grüßen"}
    assert render.cover_pdf(cl, PROFILE, {"company": "Siemens"}, "de")[:4] == b"%PDF"
    assert render.cover_docx(cl, PROFILE, {"company": "Siemens"}, "de")[:2] == b"PK"


@respx.mock
def test_api_end_to_end():
    from app.main import app

    respx.post(GROQ_URL).mock(side_effect=groq_router(fabricate=False))
    with TestClient(app) as c:
        assert c.put("/api/settings", json={"GROQ_API_KEY": "gsk_testkey1234"}).json()["GROQ_API_KEY"].endswith("1234")
        # upload a resume -> structured profile
        r = c.post("/api/profile/upload", files={"file": ("cv.txt", ("Priya Sharma\n" + JD * 3).encode(), "text/plain")})
        assert r.status_code == 200 and r.json()["name"] == "Priya Sharma"
        c.put("/api/profile", json=r.json())
        job = c.post("/api/jobs/manual", json={"title": "Data Science Intern", "company": "Acme", "country": "india",
                                                "description": JD}).json()
        created = c.post("/api/applications", json={"job_ids": [job["id"]], "cover_letter": True}).json()["created"]
        aid = created[0]
        import time
        for _ in range(50):
            a = c.get(f"/api/applications/{aid}").json()
            if a["status"] in ("done", "error"):
                break
            time.sleep(0.1)
        assert a["status"] == "done", a
        assert a["ats"]["ats"]["score"] > 80
        assert a["cover_letter"]["greeting"] == "Dear Hiring Manager,"
        assert c.get(f"/api/applications/{aid}/resume.pdf").content[:4] == b"%PDF"
        assert c.get(f"/api/applications/{aid}/resume.docx").status_code == 200
        assert c.get(f"/api/applications/{aid}/cover.pdf").status_code == 200
        # manual edit re-scores
        res = a["resume"]
        res["skills"]["technical"] = []
        edited = c.put(f"/api/applications/{aid}/resume", json=res).json()
        assert edited["ats"]["ats"]["score"] <= a["ats"]["ats"]["score"]
        lst = c.get("/api/applications").json()
        assert lst[0]["score"] > 0


def test_humanize_detects_ai_writing():
    from app.services import humanize
    r = normalize({"summary": "I am a passionate, results-driven student.",
                   "experience": [{"title": "Intern", "bullets": ["Leveraged Python to build tools", "Leveraged SQL", "Did stuff"]}]})
    rv = humanize.review(r)
    assert {"passionate", "results-driven", "leveraged"} <= set(rv["cliches"])
    assert any("leveraged" in v for v in rv["repeated_verbs"])
    assert rv["short_bullets"] and rv["first_person"]
    assert any("cliché" in n for n in humanize.notes(rv))


@respx.mock
def test_writer_then_editor_pass():
    db.init()
    db.set_setting("GROQ_API_KEY", "test")
    calls["writer"] = calls["editor"] = 0
    respx.post(GROQ_URL).mock(side_effect=groq_router(fabricate=True))
    job = {"title": "Data Science Intern", "description": JD}
    out = asyncio.run(tailor.build(PROFILE, job, "india", target=95, max_rounds=3))
    assert calls["writer"] == 1 and calls["editor"] >= 1  # draft + at least one editor/humanize pass
    assert out["style"]["cliches"] == []
    assert len(out["history"]) >= 2


@respx.mock
def test_studio_analyze_and_improve():
    from app.main import app
    respx.post(GROQ_URL).mock(side_effect=groq_router(fabricate=False))
    with TestClient(app) as c:
        c.put("/api/settings", json={"GROQ_API_KEY": "gsk_testkey1234"})
        r = c.post("/api/studio/analyze", data={"target_role": "Data Science Intern", "country": "india"},
                   files={"file": ("cv.txt", ("Priya Sharma\n" + JD * 3).encode(), "text/plain")})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ai"]["overall"] == 64 and d["profile"]["name"] == "Priya Sharma"
        assert d["local"]["total"] == 11
        r = c.post("/api/studio/improve", json={"target_role": "Data Science Intern", "country": "india",
                                                "profile": d["profile"], "save_as_profile": True})
        aid = r.json()["created"][0]
        import time
        for _ in range(50):
            a = c.get(f"/api/applications/{aid}").json()
            if a["status"] in ("done", "error"):
                break
            time.sleep(0.1)
        assert a["status"] == "done", a
        assert a["job"]["source"] == "studio"
        assert c.get("/api/profile").json()["name"] == "Priya Sharma"
