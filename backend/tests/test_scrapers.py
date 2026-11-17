import asyncio
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ["INTERN_HUNTER_DATA"] = tempfile.mkdtemp()

import httpx
import respx

from app import db, scrapers
from app.scrapers import adzuna, arbeitnow, bundesagentur, internshala, linkedin

FX = Path(__file__).parent / "fixtures"
db.init()


def _today(days_ago=0):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def li_html():
    return (FX / "linkedin_search.html").read_text().replace("2026-11-16", _today(1)).replace("2026-11-12", _today(5))


def test_linkedin_parse_cards():
    jobs = linkedin.parse_cards(li_html(), "india")
    assert [j.title for j in jobs] == ["Data Science Intern", "Software Engineering Intern"]
    assert jobs[0].company == "Acme Analytics"
    assert jobs[0].location.startswith("Bengaluru")
    assert jobs[0].external_id == "4051234567"
    assert "?" not in jobs[0].url


def test_linkedin_parse_detail():
    text = linkedin.parse_detail((FX / "linkedin_detail.html").read_text())
    assert "Pandas" in text and "• Strong Python" in text


@respx.mock
def test_linkedin_search_time_filter_and_429():
    route = respx.get(linkedin.SEARCH_URL)
    route.side_effect = [httpx.Response(200, text=li_html()), httpx.Response(200, text=""),
                         httpx.Response(429, text="")]
    jobs, warns = asyncio.run(linkedin.search("india", "24h", delay=0))
    # 24h filter (+1 day slack) keeps the 1-day-old one, drops the 5-day-old one
    assert [j.title for j in jobs] == ["Data Science Intern"]
    assert any("429" in w for w in warns)
    first = route.calls[0].request.url.params
    # LinkedIn's guest API ignores f_JT/f_E/f_WT, so the internship word goes into the query itself
    assert first["f_TPR"] == "r86400" and first["keywords"] == "intern" and first["geoId"] == "102713980"


def test_internshala_parse():
    jobs = internshala.parse_listing((FX / "internshala_listing.html").read_text(encoding="utf-8"))
    assert len(jobs) == 2  # the /job/detail/ full-time posting is excluded
    py = jobs[0]
    assert py.title == "Python Development"
    assert py.company == "Techno Labs Private Limited"
    assert py.location == "Bangalore"
    assert py.extra["stipend"].startswith("₹ 10,000")
    assert py.extra["duration"] == "3 Months"
    assert py.extra["posted_text"] == "2 days ago"
    assert py.url == "https://internshala.com/internship/detail/python-development-internship-in-bangalore-at-techno-labs1763012345"
    assert jobs[1].location == "Work from home" and jobs[1].extra["stipend"] == "Unpaid"


def test_internshala_urls():
    assert internshala.listing_url("", "", 1) == "https://internshala.com/internships/"
    assert internshala.listing_url("data science", "", 2) == "https://internshala.com/internships/keywords-data-science/page-2/"
    assert internshala.listing_url("python", "Pune", 1) == "https://internshala.com/internships/keywords-python/internship-in-pune/"


@respx.mock
def test_internshala_week_filter():
    respx.get(url__startswith="https://internshala.com/internships/").mock(
        return_value=httpx.Response(200, text=(FX / "internshala_listing.html").read_text(encoding="utf-8")))
    jobs, _ = asyncio.run(internshala.search("india", "week", delay=0, max_pages=1))
    assert [j.title for j in jobs] == ["Python Development"]  # 3-weeks-old one dropped


@respx.mock
def test_bundesagentur():
    payload = {"stellenangebote": [
        {"refnr": "10001-1002716922-S", "titel": "Praktikum Data Analytics (m/w/d)", "arbeitgeber": "Siemens AG",
         "arbeitsort": {"ort": "München", "region": "Bayern"}, "aktuelleVeroeffentlichungsdatum": _today(2)},
        {"refnr": "10001-2-S", "titel": "Trainee Vertrieb", "arbeitgeber": "X GmbH",
         "arbeitsort": {"ort": "Berlin"}, "aktuelleVeroeffentlichungsdatum": _today(1)}]}
    r = respx.get(bundesagentur.BASE + "/pc/v4/jobs").mock(return_value=httpx.Response(200, json=payload))
    jobs, warns = asyncio.run(bundesagentur.search("germany", "week"))
    assert len(jobs) == 2 and jobs[0].company == "Siemens AG" and jobs[0].location == "München, Bayern"
    p = r.calls[0].request
    assert p.headers["X-API-Key"] == "jobboerse-jobsuche"
    assert p.url.params["angebotsart"] == "34" and p.url.params["veroeffentlichtseit"] == "7"
    respx.get(bundesagentur.BASE + "/pc/v4/jobdetails/MTAwMDEtMTAwMjcxNjkyMi1T").mock(
        return_value=httpx.Response(200, json={"stellenangebotsTitel": "Praktikum", "stellenangebotsBeschreibung": "Python, SQL, Deutsch B2"}))
    assert "Python" in asyncio.run(bundesagentur.fetch_description("10001-1002716922-S"))


@respx.mock
def test_arbeitnow_filters_interns_and_dates():
    now = datetime.now(timezone.utc).timestamp()
    data = {"data": [
        {"slug": "a", "title": "Werkstudent Software Development (m/w/d)", "company_name": "A", "location": "Berlin",
         "remote": False, "url": "u1", "description": "<p>Python</p>", "tags": [], "job_types": [], "created_at": now - 3600},
        {"slug": "b", "title": "Senior Backend Engineer", "company_name": "B", "location": "Berlin", "remote": True,
         "url": "u2", "description": "", "tags": [], "job_types": ["full time"], "created_at": now - 3600},
        {"slug": "c", "title": "Marketing Intern", "company_name": "C", "location": "Hamburg", "remote": False,
         "url": "u3", "description": "", "tags": [], "job_types": ["internship"], "created_at": now - 40 * 86400}]}
    respx.get(arbeitnow.API).mock(side_effect=[httpx.Response(200, json=data), httpx.Response(200, json={"data": []})])
    jobs, _ = asyncio.run(arbeitnow.search("germany", "month"))
    assert [j.title for j in jobs] == ["Werkstudent Software Development (m/w/d)"]


@respx.mock
def test_adzuna():
    data = {"results": [{"id": 1, "title": "Finance <strong>Intern</strong>", "company": {"display_name": "HDFC"},
                         "location": {"display_name": "Mumbai"}, "redirect_url": "https://adzuna/1",
                         "created": "2026-11-16T10:00:00Z", "description": "Excel..."},
                        {"id": 2, "title": "Senior Accountant", "company": {"display_name": "Y"}, "location": {},
                         "redirect_url": "x", "created": "2026-11-16T10:00:00Z", "description": "full time"}]}
    r = respx.get(url__regex=r"https://api\.adzuna\.com/v1/api/jobs/in/search/\d+").mock(return_value=httpx.Response(200, json=data))
    jobs, _ = asyncio.run(adzuna.search("india", "week", app_id="i", app_key="k", max_pages=1))
    assert [j.title for j in jobs] == ["Finance Intern"]
    assert r.calls[0].request.url.params["max_days_old"] == "7"
    jobs, warns = asyncio.run(adzuna.search("india", "week"))
    assert jobs == [] and "Adzuna skipped" in warns[0]


@respx.mock
def test_search_all_merges_and_survives_failures():
    respx.get(linkedin.SEARCH_URL).mock(side_effect=[httpx.Response(200, text=li_html())] + [httpx.Response(200, text="")] * 10)
    respx.get(url__startswith="https://internshala.com/").mock(side_effect=httpx.ConnectError("boom"))
    db.set_setting("LINKEDIN_DELAY", "0")
    out = asyncio.run(scrapers.search_all("india", "week", ["linkedin", "internshala", "bundesagentur"]))
    assert out["per_source"]["linkedin"] == 2
    assert out["per_source"]["internshala"] == 0
    assert "bundesagentur" not in out["per_source"]  # Germany-only source skipped for India
    assert any("Internshala" in w for w in out["warnings"])
    assert db.get_job(out["jobs"][0]["id"])["title"]


@respx.mock
def test_linkedin_keeps_only_internship_titles_and_uses_local_words():
    html = li_html().replace("Software Engineering Intern", "Senior Software Engineer")
    route = respx.get(linkedin.SEARCH_URL)
    route.side_effect = [httpx.Response(200, text=html)] + [httpx.Response(200, text="")] * 10
    jobs, _ = asyncio.run(linkedin.search("france", "week", keywords="data", delay=0, max_pages=1))
    assert [j.title for j in jobs] == ["Data Science Intern"]  # the senior role is dropped
    queries = [c.request.url.params["keywords"] for c in route.calls]
    assert queries[0] == "data stage" and "data intern" in queries
    assert route.calls[0].request.url.params["location"] == "France"


@respx.mock
def test_linkedin_remote_filter_reads_descriptions():
    respx.get(linkedin.SEARCH_URL).mock(side_effect=[httpx.Response(200, text=li_html())] + [httpx.Response(200, text="")] * 10)
    respx.get(url__regex=r".*/jobPosting/4051234567").mock(return_value=httpx.Response(
        200, text="<div class='show-more-less-html__markup'>This is a fully remote internship, work from home.</div>"))
    respx.get(url__regex=r".*/jobPosting/\d+").mock(return_value=httpx.Response(
        200, text="<div class='show-more-less-html__markup'>On-site in our Pune office five days a week.</div>"))
    jobs, _ = asyncio.run(linkedin.search("india", "week", delay=0, max_pages=1, work_mode="remote"))
    assert [j.title for j in jobs] == ["Data Science Intern"] and jobs[0].extra["work_mode"] == "remote"
    assert "fully remote" in jobs[0].description  # kept, so tailoring doesn't fetch it again


@respx.mock
def test_arbeitnow_europe_tags_country_and_remote_filter():
    now = datetime.now(timezone.utc).timestamp()
    row = lambda slug, title, loc, remote: {"slug": slug, "title": title, "company_name": "X", "location": loc, "remote": remote,
                                            "url": slug, "description": "", "tags": [], "job_types": [], "created_at": now - 60}
    data = {"data": [row("a", "Marketing Intern", "Amsterdam", False), row("b", "Data Intern", "Paris, France", True),
                     row("c", "Werkstudent Data", "Berlin", False), row("d", "Intern", "New York, United States", True)]}
    respx.get(arbeitnow.API).mock(side_effect=lambda req: httpx.Response(200, json=data if req.url.params.get("page") == "1" else {"data": []}))
    eu, _ = asyncio.run(arbeitnow.search("europe", "week"))
    assert {j.title: j.country for j in eu} == {"Marketing Intern": "netherlands", "Data Intern": "france", "Werkstudent Data": "germany"}
    nl, _ = asyncio.run(arbeitnow.search("netherlands", "week"))
    assert [j.title for j in nl] == ["Marketing Intern"]
    remote, _ = asyncio.run(arbeitnow.search("europe", "week", work_mode="remote"))
    assert [j.title for j in remote] == ["Data Intern"]


def test_internshala_wfh_url_and_work_mode_detection():
    from app.scrapers.base import detect_work_mode, location_country
    assert internshala.listing_url("", "", 1, wfh=True) == "https://internshala.com/internships/work-from-home-internships/"
    assert internshala.listing_url("python", "", 2, wfh=True) == "https://internshala.com/internships/work-from-home-python-internships/page-2/"
    assert detect_work_mode("Data Intern (Remote)") == "remote"
    assert detect_work_mode("Praktikum", "Berlin", "Homeoffice möglich") == "hybrid"
    assert detect_work_mode("Intern", "Paris", "Join our office") == "onsite"
    assert detect_work_mode("Benefit from up to 2 days of remote working per week.") == "hybrid"
    assert detect_work_mode("This is a remote internship role") == "remote"
    assert location_country("Lyon, Auvergne-Rhône-Alpes, France") == "france" and location_country("Köln") == "germany"
