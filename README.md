# Intern Hunter

Intern Hunter finds internships in **India** and **Germany**, lets you pick the postings you want, and writes an **ATS-optimised resume and cover letter for each one with Groq AI**.

```
Find internships  →  Select postings  →  AI tailors resume (scored against the job)  →  Download PDF / DOCX
```

## What it does

| Feature | Details |
|---|---|
| Country | India or Germany |
| Time filter | Last 24 hours, past week, past month |
| Internships only | Filtered at each source (LinkedIn's job-type filter, Arbeitsagentur's `Praktikum/Trainee` filter), plus a title/description check |
| Sources (India) | LinkedIn public jobs, **Internshala** (custom scraper), Adzuna |
| Sources (Germany) | LinkedIn public jobs, **Bundesagentur für Arbeit** (custom client for the official job board), Arbeitnow, Adzuna |
| Any other site | "Paste a job from another site" works for Naukri, StepStone, Indeed, Xing, company career pages, etc. |
| Profile | Upload a PDF/DOCX resume (Groq reads it into a form) or fill the form yourself |
| Tailoring | Groq (Llama 3.3 70B) rewrites the resume for each job using **only facts from your profile** |
| ATS score | Scores keyword coverage, title match, sections, format and impact; rewrites up to 3 times, aiming for 95 |
| Honesty guard | Strips any skill the AI adds that isn't in your profile, and lists the job's missing skills so you can add the ones you really have |
| Region styles | India: education first, one page. Germany: Lebenslauf order, languages with CEFR levels, availability and work permit, optional German language |
| Resume Studio | Upload any sample resume and get a recruiter-style review: score, ranked issues, before/after bullet rewrites and ATS risks. Then one click produces an improved version for the role you name |
| Human-sounding writing | Three AI steps: a job analyst, a writer, then an editor. A local checker flags AI clichés ("leveraged", "spearheaded", "passionate"…), repeated verbs, thin bullets and first-person words, and the editor fixes them |
| Cover letters | Optional, one per job. Germany uses Anschreiben style |
| Export | ATS-safe PDF and DOCX: single column, real text, standard headings, A4 |

## Setup (about 5 minutes)

**Requirements:** Python 3.10+ and Node 18+ (Node is only needed if you change the frontend; a built copy is included).

### 1. Get a free Groq key
https://console.groq.com/keys

### 2. Start the app

**Windows:** double-click `start.bat`
**macOS / Linux:** `./start.sh`

Or do it manually:
```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # optional: you can also enter keys in the app's Settings page
uvicorn app.main:app --port 8000
```
Then open **http://localhost:8000**.

### 3. In the app
1. **Settings:** paste your Groq key. An Adzuna key (free at developer.adzuna.com) is optional and adds more results.
2. **My profile:** upload your resume, check what it read, add *everything* you genuinely know (all skills and projects), then Save. The AI picks the relevant parts for each job.
3. **Find internships:** choose a country and time range, then search. Tick the postings you want and click **Generate ATS resumes**.
4. **Resumes & letters:** open each one to see the score breakdown and the missing keywords, edit if you like, and download the PDF/DOCX.

## How the AI writes (prompting)
All prompts are in `backend/app/services/prompts.py`, so you can edit the wording in one place.

1. **JD_ANALYST** reads the posting and returns must-have skills, nice-to-haves, exact ATS keywords and a summary of the company.
2. **WRITER** drafts the resume from your master profile only, following truthfulness, completeness, region (India/Germany) and style rules:
   - every bullet says what you did, how, and the result
   - each bullet opens with a different verb
   - a banned list keeps out AI clichés
   - metrics are never invented
3. **ATS scorer + style checker** run locally and produce specific editor notes, such as "Missing keywords that ARE in your profile: Docker" or "Remove: leveraged".
4. **EDITOR** applies those notes. Steps 3–4 repeat until the score reaches your target (95 by default) with no style issues, or the pass limit is hit. The best version is kept.
5. **Safety net:** any skill not found in your profile is stripped, and contact details always come from your profile.

## Developing the frontend
```bash
cd frontend
npm install
npm run dev      # http://localhost:5173 (proxies /api to :8000)
npm run build    # rebuilds frontend/dist, which the backend serves
```

## Tests
```bash
cd backend && pytest -q
```
The tests check every scraper parser against sample pages, the time and internship filters, cross-source de-duplication, the ATS scorer, the anti-fabrication guard, PDF/DOCX text extraction, and the full API flow with a mocked Groq.

## Important notes

**About the 95% ATS score.** The score comes from this app's own model of how ATS systems rank resumes (keyword coverage weighs most). Workday, Greenhouse, SuccessFactors, Naukri RMS and others each score differently, so no tool can guarantee a number inside them. What gets you to 95 here is what helps everywhere: your profile must actually contain the skills the job asks for. When it doesn't, the app tells you exactly which skills are missing instead of inventing them. A fabricated resume gets rejected at the interview stage.

**About scraping.**
- LinkedIn: only the public, logged-out job pages are used, so your LinkedIn account is never involved and can't be banned. Scraping LinkedIn is against its Terms of Service, and LinkedIn rate-limits it (HTTP 429). The app goes slowly, stops cleanly when blocked and keeps the other sources working. If you get blocked, wait 10–30 minutes or raise `LINKEDIN_DELAY` in Settings. Use it for personal job hunting only.
- Internshala: an HTML scraper that keys off the stable detail-page links rather than CSS classes. If Internshala redesigns its site and results drop to 0, the app shows a warning. The parser is `backend/app/scrapers/internshala.py`.
- Bundesagentur für Arbeit: the public API behind arbeitsagentur.de. It is very stable and has the most German internships (`angebotsart=34`).
- Run the app from your own home internet connection. Datacenter and cloud IPs are blocked much faster.

## Project layout
```
backend/
  app/main.py                 FastAPI routes + background generation queue
  app/scrapers/               linkedin, internshala, bundesagentur, arbeitnow, adzuna
  app/services/tailor.py      Groq tailoring + ATS improve loop + honesty guard
  app/services/ats.py         ATS scorer (keywords, synonyms, sections, impact)
  app/services/render.py      ATS-safe PDF (ReportLab) and DOCX (python-docx)
  app/services/cover_letter.py
  app/services/resume_parser.py
  data/app.db                 your profile, jobs, resumes (local only)
frontend/                     React + Vite + TypeScript UI
```
