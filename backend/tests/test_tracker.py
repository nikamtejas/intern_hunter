"""Profiles, links, one-page fitting, completeness check, application tracker and email classification."""
import asyncio
import io
import json
import os
import tempfile
import time

os.environ.setdefault("INTERN_HUNTER_DATA", tempfile.mkdtemp())

from fastapi.testclient import TestClient
from pypdf import PdfReader

from app import db
from app.services import completeness, mailsync, render, resume_parser
from app.services.profile_schema import normalize

BIG = normalize({
    "name": "Asha Rao", "email": "asha@example.com", "phone": "+91 90000 11111", "location": "Bengaluru, India",
    "linkedin": "https://www.linkedin.com/in/asha-rao", "github": "https://github.com/asha",
    "summary": "Computer science student who builds web apps and data tools.",
    "education": [{"institution": "RVCE", "degree": "B.E.", "field": "CSE", "start": "2022", "end": "2026", "grade": "8.9"}],
    "experience": [{"title": f"Intern {i}", "company": f"Co {i}", "start": "2024", "end": "2025",
                    "bullets": [f"Built feature {i}.{k} with React and Node.js for {k * 100} users across three regions" for k in range(1, 7)]}
                   for i in range(4)],
    "projects": [{"name": f"Project {i}", "tech": ["Python", "Flask"], "link": f"github.com/asha/p{i}", "live": f"p{i}.vercel.app",
                  "bullets": [f"Shipped part {k} of project {i} using Python and Flask with tests and CI" for k in range(1, 5)]}
                 for i in range(5)],
    "skills": {"technical": ["Python", "React", "Node.js", "SQL"], "tools": ["Git", "Docker"], "soft": ["Teamwork"]},
    "achievements": [f"Achievement number {i}" for i in range(6)],
    "certifications": [{"name": f"Cert {i}", "issuer": "Coursera"} for i in range(5)],
})


def test_links_split_and_rendered_clickable():
    p = normalize({"links": [{"url": "linkedin.com/in/x"}, {"url": "https://github.com/x"}, {"url": "kaggle.com/x"}]})
    assert p["linkedin"] == "linkedin.com/in/x" and p["github"] == "https://github.com/x"
    assert [l["url"] for l in p["links"]] == ["kaggle.com/x"]
    pdf = render.resume_pdf(BIG, "india", "en")
    uris = [a.get_object()["/A"]["/URI"] for a in PdfReader(io.BytesIO(pdf)).pages[0].get("/Annots", [])]
    assert "https://www.linkedin.com/in/asha-rao" in uris and "https://github.com/asha" in uris
    # the importer gets hidden hyperlinks back out of a PDF
    assert "https://github.com/asha" in resume_parser.extract_links("r.pdf", pdf)
    text = resume_parser.extract_text("r.pdf", pdf)
    assert "HYPERLINKS IN FILE" in text and "linkedin.com/in/asha-rao" in text


def test_fit_one_page_trims_least_relevant():
    fitted, layout, trims = render.fit_one_page(BIG, "india", "en", ["react", "node.js"])
    assert len(PdfReader(io.BytesIO(render._pdf_bytes(fitted, "india", "en", layout))).pages) == 1
    assert trims and layout["scale"] >= 0.92


def test_short_resume_fills_the_page_and_has_no_box_characters():
    short = normalize({"name": "Ravi K", "email": "r@x.in", "summary": "Student building data tools with hands\u2011on Python.",
                       "projects": [{"name": "Bot", "bullets": ["Built a Telegram bot\u00a0in Python"]}],
                       "skills": {"technical": ["Python"]}})
    _, layout, _ = render.fit_one_page(short, "india", "en")
    # far too little content: the layout grows as far as it can (the tailor then asks the AI for more detail)
    assert layout["scale"] == render.MAX_SCALE and layout["space"] == render.MAX_SPACE
    medium = normalize({**BIG, "experience": BIG["experience"][:2], "projects": BIG["projects"][:2], "achievements": [],
                        "certifications": []})
    for e in medium["experience"] + medium["projects"]:
        e["bullets"] = e["bullets"][:3]
    _, layout, trims = render.fit_one_page(medium, "india", "en")
    assert not trims and layout["fill"] > 0.8 and layout["scale"] > 1.0  # a 2/3-page resume is enlarged to fill the page
    text = PdfReader(io.BytesIO(render.resume_pdf(short))).pages[0].extract_text()
    assert "hands-on" in text and "\u2011" not in text
    import docx
    d = docx.Document(io.BytesIO(render.resume_docx(BIG, "germany", "de")))
    assert len(d.tables) == 0
    assert any("hyperlink" in r.reltype for r in d.part.rels.values())


def test_completeness_flags_missing_links():
    items = completeness.check({"name": "X", "email": "x@y.z", "skills": {"technical": ["Python"]},
                                "projects": [{"name": "Bot", "bullets": ["a"]}]}, "germany")["items"]
    fields = {i["field"] for i in items}
    assert {"linkedin", "github", "phone", "projects", "languages"} <= fields
    assert completeness.check(BIG)["score"] > completeness.check({"name": "X"})["score"]


def test_email_rules_and_transitions():
    c = mailsync.classify_rules
    assert c("Your application to Acme", "Thank you for applying. Unfortunately we will not be moving forward.") == "rejected"
    assert c("Interview invitation – Data Intern", "We'd like to schedule a call") == "interview"
    assert c("Next steps", "Please complete the HackerRank assessment within 3 days") == "assessment"
    assert c("Application received", "Thank you for your application to the Data Science Intern role") == "applied"
    assert c("Ihre Bewerbung", "Leider müssen wir Ihnen mitteilen, dass wir uns für einen anderen Kandidaten entschieden haben") == "rejected"
    assert c("Offer", "We are pleased to offer you the internship") == "offer"
    s = mailsync.should_update
    assert s("applied", "interview") and s("interview", "rejected") and s("not_applied", "applied")
    assert not s("interview", "applied") and not s("offer", "rejected") and not s("rejected", "interview")
    assert mailsync.company_keys("Siemens Healthineers AG") == ["siemens healthineers", "siemens"]


def _msg(subject, body, sender, when):
    return {"id": f"{subject}-{when}", "subject": subject, "body": body, "from": sender, "date": when}


def test_api_profiles_tracker_and_email_processing():
    from app.main import app

    with TestClient(app) as c, TestClient(app) as other:
        # a new profile always has a password and signs its browser in
        assert c.post("/api/users", json={"name": "Second student", "password": "123"}).status_code == 422  # too short
        u2 = c.post("/api/users", json={"name": "Second student", "password": "secret-pw"}).json()["id"]
        assert c.get("/api/auth/me").json()["id"] == u2
        # another browser can't see or touch it without the password
        assert other.get("/api/profile", headers={"X-User-Id": str(u2)}).status_code == 401
        assert other.post("/api/auth/login", json={"user_id": u2, "password": "wrong"}).status_code == 401
        assert "name" in other.get("/api/users").json()[0] and "applications" not in other.get("/api/users").json()[0]

        c.put("/api/profile", json={"name": "Second", "github": "github.com/second"})
        other.put("/api/profile", json={"name": "First", "github": "github.com/first"})  # user 1: no password yet
        assert c.get("/api/profile").json()["github"] == "github.com/second"
        assert any(i["field"] == "linkedin" for i in c.get("/api/profile/check").json()["items"])

        jobs = []
        for title, company in (("Data Science Intern", "Acme Analytics Pvt Ltd"), ("Backend Intern", "Zeta GmbH")):
            jobs.append(c.post("/api/jobs/manual", json={"title": title, "company": company, "country": "india",
                                                        "description": "x" * 60}).json())
        ids = [db.create_application(j["id"], {}, u2) for j in jobs]
        for i in ids:
            db.update_application(i, status="done", resume=normalize({"name": "Second"}))
        assert all(a["id"] not in ids for a in other.get("/api/applications").json())
        assert other.get(f"/api/applications/{ids[0]}").status_code == 404  # someone else's application
        assert other.get(f"/api/applications/{ids[0]}/resume.pdf").status_code == 404  # downloads are private too
        assert c.get(f"/api/applications/{ids[0]}/resume.pdf").status_code == 200

        r = c.patch(f"/api/applications/{ids[0]}/track", json={"track": "applied", "notes": "Applied via careers page"}).json()
        assert r["track"] == "applied" and r["applied_at"] and len(r["events"]) == 2

        now = time.time() + 60
        msgs = [
            _msg("Interview invitation: Data Science Intern", "Hi, we'd like to schedule an interview with you.",
                 "Acme Analytics Careers <jobs@acmeanalytics.com>", now),
            _msg("Your application to Zeta", "Thank you for applying. Unfortunately we decided to move forward with other candidates.",
                 "Zeta Recruiting <noreply@zeta.de>", now + 10),
            _msg("10 new jobs for you", "Data Science Intern at Acme Analytics and more jobs you may like",
                 "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>", now + 20),
            _msg("Old mail", "Unfortunately the position has been filled", "Acme Analytics <hr@acmeanalytics.com>", now - 10 * 86400),
        ]
        res = asyncio.run(mailsync.process(u2, msgs, use_ai=False))
        assert {u["app_id"]: u["to"] for u in res["updated"]} == {ids[0]: "interview", ids[1]: "rejected"}
        dash = c.get("/api/dashboard").json()
        assert dash["counts"]["interview"] == 1 and dash["counts"]["rejected"] == 1 and dash["applied"] == 2
        assert dash["response_rate"] == 100
        assert [e for e in dash["events"] if e["source"] == "email"][0]["detail"]["subject"]
        assert asyncio.run(mailsync.process(u2, msgs, use_ai=False))["updated"] == []

        db.save_search(u2, {"country": "india"}, [jobs[0]["id"]], {"manual": 1}, [])
        assert len(c.get("/api/searches").json()) == 1 and other.get("/api/searches").json() == []
        got = c.get(f"/api/searches/{c.get('/api/searches').json()[0]['id']}").json()
        assert got["jobs"][0]["extra"]["mine"]["track"] == "interview"

        # sign out, sign back in, then delete (needs the password)
        c.post("/api/auth/logout")
        assert c.get("/api/profile", headers={"X-User-Id": str(u2)}).status_code == 401
        assert c.post("/api/auth/login", json={"user_id": u2, "password": "secret-pw"}).status_code == 200
        assert c.request("DELETE", "/api/users/me", json={"user_id": u2, "password": "nope"}).status_code == 401
        assert c.request("DELETE", "/api/users/me", json={"user_id": u2, "password": "secret-pw"}).status_code == 200
        assert db.list_applications(u2) == []

def test_truth_guard_strips_invented_tech_from_every_line():
    from app.services import tailor
    from app.services.profile_schema import flatten_text

    prof = normalize({"summary": "Data student.", "skills": {"technical": ["Python", "SQL"], "tools": ["MongoDB"]},
                      "projects": [{"name": "Rentiverse", "tech": ["Node.js"], "bullets": ["Built a rental site with Node.js and MongoDB"]}]})
    res = normalize({"headline": "Full Stack Developer | React · Node.js", "summary": "I build APIs. I use React daily.",
                     "projects": [{"name": "Rentiverse", "tech": ["Node.js", "React", "PostgreSQL"],
                                   "bullets": ["Built a React front-end for listings", "Stored listings in MongoDB (NoSQL)"]}]})
    jd = {"job_title": "Full Stack Developer", "hard_skills": ["React", "NoSQL"], "tools": ["PostgreSQL"]}
    removed = tailor._enforce_truth(res, prof, flatten_text(prof), tailor._tech_vocab(jd, "Full Stack Developer"))
    assert res["projects"][0]["tech"] == ["Node.js"]
    bullets = res["projects"][0]["bullets"]
    assert "Stored listings in MongoDB (NoSQL)" in bullets  # NoSQL is proven by MongoDB
    assert not any("React" in b for b in bullets)
    assert "Built a rental site with Node.js and MongoDB" in bullets  # topped up from the original entry
    assert "React" not in res["summary"] and "React" not in res["headline"] and res["headline"].startswith("Full Stack Developer")
    assert len(removed) >= 4


def test_truth_guard_catches_invented_numbers_and_moved_tools():
    from app.services import tailor
    from app.services.profile_schema import flatten_text

    prof = normalize({"skills": {"technical": ["Python", "SQL"], "tools": ["Power BI", "Excel"]},
                      "experience": [{"title": "Data Analyst", "company": "TDM", "bullets": [
                          "Cleaned sales data with SQL and Python", "Designed Power BI dashboards for sales", "Presented results"]}],
                      "projects": [{"name": "Rentiverse", "tech": ["SQL"], "bullets": ["Built a rental platform with SQL storage",
                                                                                         "Added analytics dashboards"]}]})
    res = normalize({"experience": [{"title": "Data Analyst", "company": "TDM", "bullets": [
                        "Cleaned sales data with SQL and Python to reach 99% record accuracy",
                        "Designed Power BI dashboards for sales managers", "Wrote Excel VBA macros", "Built Python 3 scripts"]}],
                     "projects": [{"name": "Rentiverse", "tech": ["SQL", "Power BI"],
                                   "bullets": ["Built Power BI dashboards for occupancy", "Designed the SQL schema for rentals"]}]})
    removed = tailor._enforce_truth(res, prof, flatten_text(prof), tailor._tech_vocab({}, "Data Analyst Intern"))
    exp = res["experience"][0]["bullets"]
    assert not any("99%" in b or "VBA" in b for b in exp)  # invented metric and invented tool are gone
    assert "Designed Power BI dashboards for sales managers" in exp and "Built Python 3 scripts" in exp
    prj = res["projects"][0]
    assert prj["tech"] == ["SQL"] and not any("Power BI" in b for b in prj["bullets"])  # tool moved onto the wrong project
    assert any("99" in r for r in removed)


def test_groq_quota_exhausted_falls_back_then_fails_fast():
    import httpx
    import respx
    from app.services import groq_client

    db.init()
    db.set_setting("GROQ_API_KEY", "test")
    db.set_setting("GROQ_MODEL", "openai/gpt-oss-120b")
    seen = []

    def handler(request):
        model = json.loads(request.content)["model"]
        seen.append(model)
        if model == "openai/gpt-oss-120b":
            return httpx.Response(429, headers={"retry-after": "2202"}, json={"error": {"message": "TPD"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    with respx.mock:
        respx.post(groq_client.URL).mock(side_effect=handler)
        t0 = time.time()
        assert asyncio.run(groq_client.chat([{"role": "user", "content": "x"}])) == "ok"
        assert seen == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"] and time.time() - t0 < 5
    with respx.mock:  # both quotas gone: clear error instead of a 37-minute silent wait
        respx.post(groq_client.URL).mock(return_value=httpx.Response(429, headers={"retry-after": "2202"}))
        try:
            asyncio.run(groq_client.chat([{"role": "user", "content": "x"}]))
            raise AssertionError("expected GroqError")
        except groq_client.GroqError as e:
            assert "37 minutes" in str(e)
    db.set_setting("GROQ_MODEL", "")


def test_currently_learning_counts_for_ats_but_never_backs_a_claim():
    from app.services import ats, tailor
    from app.services.profile_schema import flatten_text

    prof = normalize({"skills": {"technical": ["Python"]}, "learning": ["AWS", "Kubernetes"],
                      "projects": [{"name": "Bot", "bullets": ["Built a bot in Python", "Wrote tests in Python"]}]})
    res = normalize({**prof, "projects": [{"name": "Bot", "bullets": ["Deployed the bot on AWS with Kubernetes", "Built a bot in Python"]}]})
    evidence = flatten_text({**prof, "learning": []})
    tailor._enforce_truth(res, prof, evidence, tailor._tech_vocab({"tools": ["AWS", "Kubernetes"]}))
    assert not any("AWS" in b for b in res["projects"][0]["bullets"])  # not claimed as experience
    kw = {"hard_skills": ["Python"], "tools": ["AWS", "Kubernetes"], "soft_skills": [], "languages": [], "other_keywords": []}
    assert ats.score(res, kw)["missing"]["keywords"] == []  # but the ATS sees them in "Currently learning"
    text = PdfReader(io.BytesIO(render.resume_pdf(res))).pages[0].extract_text()
    assert "Currently learning: AWS, Kubernetes" in text


def test_orphan_word_is_tightened_back_onto_one_line_without_losing_keywords():
    from app.services import tailor

    long = ("Performed data extraction, cleaning, and validation using SQL and Python (Pandas, NumPy) to ensure "
            "the high data quality for the weekly reporting")
    lines, fill = render.measure_bullet(long, 1.0)
    out = tailor._tighten(long, 1.0)
    if lines == 2 and fill <= 0.25:
        assert render.measure_bullet(out, 1.0)[0] == 1
    assert "Pandas, NumPy" in out and "SQL" in out


def test_line_fit_rejects_padding_and_dangling_endings():
    from app.services import tailor

    facts = "Designed interactive Power BI dashboards and automated reporting pipelines for operational and sales insights"
    old = "Designed interactive Power BI dashboards and automated reporting pipelines"
    assert tailor.grounded("Designed interactive Power BI dashboards and automated reporting pipelines for operational and sales insights", old, facts)
    assert not tailor.grounded("Designed Power BI dashboards and automated reporting pipelines for key sales daily insights", old, facts)
    assert not tailor.grounded("Presented findings using visual storytelling to non-technical stakeholders to guide executive", old, facts)


def test_auto_learning_lifts_score_without_claiming_and_reports_checklist():
    import respx
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    import test_resume_engine as T
    from app.services import tailor

    db.init()
    db.set_setting("GROQ_API_KEY", "test")
    job = {"title": "Data Science Intern", "company": "Acme", "description": T.JD}
    with respx.mock:
        respx.post(T.GROQ_URL).mock(side_effect=T.groq_router(fabricate=True))
        plain = asyncio.run(tailor.build(T.PROFILE, job, "india", target=95, max_rounds=2))
    with respx.mock:
        respx.post(T.GROQ_URL).mock(side_effect=T.groq_router(fabricate=True))
        auto = asyncio.run(tailor.build(T.PROFILE, job, "india", target=95, max_rounds=2, auto_learning=True))
    assert {"Power BI", "AWS"} <= set(auto["auto_learning"])
    assert {"Power BI", "AWS"} <= set(auto["resume"]["learning"])
    assert auto["ats"]["score"] > plain["ats"]["score"] and auto["ats"]["score"] >= 90
    claims = " ".join(b for s in ("experience", "projects") for e in auto["resume"][s] for b in e["bullets"]) + auto["resume"]["summary"]
    assert "AWS" not in claims  # learning skills never appear as experience
    rules = {r["id"]: r for r in auto["checks"]["rules"]}
    assert rules["ats"]["ok"] and rules["truth"]["ok"] and "page" in rules


def test_fitted_layout_is_really_one_page_for_many_content_sizes():
    for n_proj in range(0, 6):
        for n_bul in (2, 3, 4):
            r = normalize({**BIG, "projects": BIG["projects"][:n_proj], "experience": [
                {**e, "bullets": e["bullets"][:n_bul]} for e in BIG["experience"][:3]]})
            fitted, layout, _ = render.fit_one_page(r, "india", "en")
            assert render._pages(render._pdf_bytes(fitted, "india", "en", layout)) == 1, (n_proj, n_bul, layout)
            assert render._pages(render.resume_pdf(r, "india", "en")) == 1


def test_goal_streak_followups_fit_and_prep():
    import httpx
    import respx
    from app.main import app
    from app.services.groq_client import URL as GROQ_URL

    with TestClient(app) as c:
        uid = c.post("/api/users", json={"name": "Goal getter", "password": "goal-pw-1"}).json()["id"]
        c.put("/api/profile", json={"name": "Goal getter", "skills": {"technical": ["Python", "SQL"]},
                                    "linkedin": "linkedin.com/in/goal"})
        job = c.post("/api/jobs/manual", json={"title": "Data Intern", "company": "Acme", "country": "india",
                                              "description": "We need Python, SQL and Tableau skills. " * 3}).json()
        now = time.time()
        ids = []
        for days_ago in (1, 2, 8, 9, 15, 16, 20):  # 2 this week, 2 last week, ...
            aid = db.create_application(job["id"], {}, uid)
            db.update_application(aid, status="done", track="applied", applied_at=now - days_ago * 86400,
                                  resume=normalize({"name": "Goal getter", "linkedin": "linkedin.com/in/goal"}))
            ids.append(aid)
        c.put("/api/goal", json={"weekly": 2})
        dash = c.get("/api/dashboard").json()
        assert dash["goal"]["weekly"] == 2 and dash["goal"]["streak"] >= 2 and len(dash["goal"]["history"]) == 8
        assert {f["id"] for f in dash["followups"]} >= set(ids[2:])  # quiet for 7+ days
        assert ids[0] not in {f["id"] for f in dash["followups"]}

        # fit % on search results: Python + SQL present, Tableau missing
        from app.main import _fit
        jobs = [dict(job)]
        _fit(jobs, uid)
        assert jobs[0]["extra"]["fit"]["pct"] == 67 and "tableau" in jobs[0]["extra"]["fit"]["missing"]

        # follow-up: when Groq is unavailable the template is used, still personal (no real network call)
        db.set_setting("GROQ_API_KEY", "test")
        with respx.mock:
            respx.post(GROQ_URL).mock(return_value=httpx.Response(401))
            fu = c.post(f"/api/applications/{ids[3]}/followup").json()
        assert "Data Intern" in fu["body"] and "linkedin.com/in/goal" in fu["body"] and fu["ai"] is False

        db.set_setting("GROQ_API_KEY", "test")
        fake = {"elevator_pitch": "x", "questions": [{"type": "technical", "question": "SQL joins?", "why_they_ask": "",
                                                      "answer_outline": "S/T/A/R", "based_on": "profile"}],
                "brush_up": [{"skill": "Tableau", "why": "", "days": ["Day 1"], "free_resources": ["Tableau docs"]}],
                "questions_to_ask": ["?"], "red_flags": []}
        with respx.mock:
            respx.post(GROQ_URL).mock(return_value=httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(fake)}}]}))
            out = c.post(f"/api/applications/{ids[0]}/prep").json()
        assert out["brush_up"][0]["skill"] == "Tableau"
        assert c.get(f"/api/applications/{ids[0]}").json()["prep"]["questions"][0]["question"] == "SQL joins?"
