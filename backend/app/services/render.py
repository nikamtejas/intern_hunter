"""ATS-safe renderers: single column, real text, standard headings, no tables/images/columns.

Both DOCX and PDF are generated from the same resume JSON, always fitted to exactly one A4 page,
with clickable LinkedIn / GitHub / portfolio / project links.
"""
from __future__ import annotations

import copy
import io
import json
import os
import re
from datetime import date

HEADINGS = {
    "en": {"summary": "SUMMARY", "experience": "EXPERIENCE", "projects": "PROJECTS", "education": "EDUCATION",
           "skills": "SKILLS", "languages": "LANGUAGES", "certifications": "CERTIFICATIONS", "achievements": "ACHIEVEMENTS",
           "technical": "Technical", "tools": "Tools", "soft": "Soft skills", "learning": "Currently learning", "grade": "Grade", "additional": "ADDITIONAL INFORMATION",
           "work_permit": "Work permit", "availability": "Availability", "nationality": "Nationality"},
    "de": {"summary": "PROFIL", "experience": "BERUFSERFAHRUNG", "projects": "PROJEKTE", "education": "AUSBILDUNG",
           "skills": "KENNTNISSE", "languages": "SPRACHEN", "certifications": "ZERTIFIKATE", "achievements": "ERFOLGE",
           "technical": "Fachlich", "tools": "Tools", "soft": "Soziale Kompetenzen", "learning": "Lerne aktuell", "grade": "Note", "additional": "WEITERE ANGABEN",
           "work_permit": "Arbeitserlaubnis", "availability": "Verfügbarkeit", "nationality": "Staatsangehörigkeit"},
}


LINK_LABELS = {"en": {"code": "Code", "live": "Live"}, "de": {"code": "Code", "live": "Live-Demo"}}

# characters models like to emit that many fonts don't have (they print as boxes)
_CHAR_FIX = {"‑": "-", "‐": "-", "‒": "-", "−": "-", " ": " ", " ": " ", " ": " ",
             " ": " ", " ": " ", "​": "", "‌": "", "‍": "", "﻿": "", "­": "",
             "⁠": "", "⁃": "-", "●": "•", "▪": "•", "→": "->", "": "•"}


def clean(s: str) -> str:
    s = "".join(_CHAR_FIX.get(c, c) for c in (s or ""))
    return re.sub(r"[ \t]{2,}", " ", s).strip()


def _order(country: str) -> list[str]:
    if country != "india":  # Germany/DACH and the rest of Europe: experience first
        return ["summary", "experience", "projects", "education", "skills", "languages", "certifications", "achievements", "additional"]
    return ["summary", "education", "skills", "experience", "projects", "certifications", "achievements", "languages"]


def _dates(a: dict) -> str:
    s, e = clean(a.get("start", "")), clean(a.get("end", ""))
    if s and e and s != e:
        return f"{s} – {e}"
    return s or e


def _city(location: str) -> str:
    """Resume header shows "City, Country" — never a street address or postcode."""
    parts = [p.strip() for p in clean(location).split(",") if p.strip()]
    if len(parts) > 2 or any(re.search(r"\d", p) for p in parts):
        parts = [re.sub(r"\b\d[\d\s-]*\b", "", p).strip() for p in parts[-2:]]
    return ", ".join(p for p in parts if p)


def short_url(url: str) -> str:
    """Readable form a recruiter can type: linkedin.com/in/priya (no scheme, www or trailing slash)."""
    return re.sub(r"^(https?://)?(www\.)?", "", (url or "").strip(), flags=re.I).rstrip("/")


def href(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if "@" in url and not url.startswith(("http", "mailto:")) and "/" not in url:
        return "mailto:" + url
    return url if re.match(r"^[a-z][a-z0-9+.-]*:", url, re.I) else "https://" + url


def _contact(r: dict) -> list[tuple[str, str]]:
    """[(visible text, link target)] — visible text is the short URL so it also works on paper and in ATS parsers."""
    items: list[tuple[str, str]] = []
    for k in ("phone", "email"):
        if r.get(k):
            items.append((clean(r[k]), "mailto:" + r[k].strip() if k == "email" else ""))
    for k in ("linkedin", "github", "portfolio"):
        if r.get(k):
            items.append((short_url(r[k]), href(r[k])))
    for l in r.get("links", []):
        if l.get("url"):
            items.append((short_url(l["url"]), href(l["url"])))
    if r.get("location"):
        items.append((_city(r["location"]), ""))
    return items


def _project_links(p: dict, lang: str) -> list[tuple[str, str, str]]:
    L = LINK_LABELS.get(lang, LINK_LABELS["en"])
    out = []
    if p.get("link"):
        out.append((L["code"], short_url(p["link"]), href(p["link"])))
    if p.get("live"):
        out.append((L["live"], short_url(p["live"]), href(p["live"])))
    return out


def _blocks(r: dict, country: str, lang: str):
    """Yield a neutral representation: (kind, payload) used by both renderers.

    entry payload: (bold title, italic suffix on the title line, right text, italic second line left, italic second line right)
    — the two-line layout (role ……… dates / company ……… location) used by most big-company resume templates.
    """
    H = HEADINGS.get(lang, HEADINGS["en"])
    yield ("name", clean(r.get("name", "")))
    if r.get("headline"):
        yield ("headline", clean(r["headline"]))
    yield ("contact", _contact(r))
    for sec in _order(country):
        if sec == "summary" and r.get("summary"):
            yield ("heading", H["summary"])
            yield ("para", clean(r["summary"]))
        elif sec == "experience" and r.get("experience"):
            yield ("heading", H["experience"])
            for e in r["experience"]:
                yield ("entry", (clean(e.get("title", "")), "", _dates(e), clean(e.get("company", "")), clean(e.get("location", ""))))
                for b in e.get("bullets", []):
                    yield ("bullet", clean(b))
        elif sec == "projects" and r.get("projects"):
            yield ("heading", H["projects"])
            for p in r["projects"]:
                yield ("entry", (clean(p.get("name", "")), clean(", ".join(p.get("tech", []))), _dates(p), "", ""))
                links = _project_links(p, lang)
                if links:
                    yield ("links", links)
                for b in p.get("bullets", []):
                    yield ("bullet", clean(b))
        elif sec == "education" and r.get("education"):
            yield ("heading", H["education"])
            for e in r["education"]:
                deg = ", ".join(clean(x) for x in (e.get("degree"), e.get("field")) if x)
                if e.get("grade"):
                    deg += f"  ·  {H['grade']}: {clean(e['grade'])}"
                yield ("entry", (clean(e.get("institution", "")) or deg, "", clean(e.get("location", "")),
                                 deg if e.get("institution") else "", _dates(e)))
                for d in e.get("details", []):
                    yield ("bullet", clean(d))
        elif sec == "skills":
            sk = r.get("skills", {})
            rows = [(H[k], sk.get(k)) for k in ("technical", "tools", "soft") if sk.get(k)]
            if r.get("learning"):
                rows.append((H["learning"], r["learning"]))
            if rows:
                yield ("heading", H["skills"])
                for label, items in rows:
                    yield ("kv", (label, clean(", ".join(items))))
        elif sec == "languages" and r.get("languages"):
            yield ("heading", H["languages"])
            yield ("para", clean(", ".join(f"{l['name']} ({l['level']})" if l.get("level") else l["name"] for l in r["languages"])))
        elif sec == "certifications" and r.get("certifications"):
            yield ("heading", H["certifications"])
            for c in r["certifications"]:
                yield ("bullet", clean(" – ".join(x for x in (c.get("name"), c.get("issuer"), c.get("date")) if x)))
        elif sec == "achievements" and r.get("achievements"):
            yield ("heading", H["achievements"])
            for a in r["achievements"]:
                yield ("bullet", clean(a))
        elif sec == "additional":
            ex = r.get("extras") or {}
            rows = [(H[k], ex.get(k)) for k in ("work_permit", "availability", "nationality") if ex.get(k)]
            if rows:
                yield ("heading", H["additional"])
                for label, v in rows:
                    yield ("kv", (label, clean(v)))


# ---------------------------------------------------------------- sizes (layout is tuned so the content fills exactly one page)
def _layout(layout) -> dict:
    if isinstance(layout, (int, float)):
        return {"scale": float(layout), "space": 1.0}
    return layout or {"scale": 1.0, "space": 1.0}


def _sizes(layout) -> dict:
    lay = _layout(layout)
    s, sp = lay["scale"], lay["space"]
    return {"name": 21 * s, "headline": 10.6 * s, "contact": 9.2 * s, "heading": 10.8 * s, "body": 10 * s,
            "entry": 10.3 * s, "small": 9.5 * s, "lead": 1.2 + 0.1 * min(sp - 1, 1), "gap": 7 * s * sp,
            "entry_gap": 3.6 * s * sp, "rule_gap": 2.5 * s * min(sp, 1.6),
            # margins grow smoothly with the text size (a step here made the fit search land on a 2-page layout)
            "margin_x": 1.35 + 0.25 * min(1.0, max(0.0, (s - 0.92) / 0.08)),
            "margin_y": 1.0 + 0.2 * min(1.0, max(0.0, (s - 0.92) / 0.08))}


NAVY = (0x1F, 0x3A, 0x5F)
LINK = (0x1D, 0x4E, 0xD8)


# ---------------------------------------------------------------- DOCX
def _docx_link(par, url: str, text: str, size_pt: float | None = None) -> None:
    """Real clickable hyperlink run (python-docx has no public API for this)."""
    from docx.opc.constants import RELATIONSHIP_TYPE
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    r_id = par.part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    h = OxmlElement("w:hyperlink")
    h.set(qn("r:id"), r_id)
    run = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "%02X%02X%02X" % LINK)
    rpr.append(color)
    if size_pt:
        sz = OxmlElement("w:sz")
        sz.set(qn("w:val"), str(int(round(size_pt * 2))))
        rpr.append(sz)
    run.append(rpr)
    t = OxmlElement("w:t")
    t.text = text
    t.set(qn("xml:space"), "preserve")
    run.append(t)
    h.append(run)
    par._p.append(h)


def resume_docx(r: dict, country: str = "india", lang: str = "en", fit: bool = True) -> bytes:
    import docx
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    layout: dict | float = 1.0
    if fit:  # measure with the PDF engine; DOCX uses the same content and sizes
        r, layout, _ = fit_one_page(r, country, lang)
    z = _sizes(layout)
    d = docx.Document()
    sec = d.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)  # A4 for both India and Germany
    sec.left_margin = sec.right_margin = Cm(z["margin_x"])
    sec.top_margin = sec.bottom_margin = Cm(z["margin_y"])
    style = d.styles["Normal"]
    style.font.name = "Arial"  # installed on every Windows and Mac machine (Calibri isn't on Macs)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "Arial")
    style.font.size = Pt(z["body"])
    style.paragraph_format.space_after = Pt(0)
    style.paragraph_format.space_before = Pt(0)
    style.paragraph_format.line_spacing = 1.05 * z["lead"] / 1.2
    usable = sec.page_width - sec.left_margin - sec.right_margin - Pt(1)  # a stop exactly on the margin is ignored by some apps
    J = WD_ALIGN_PARAGRAPH.JUSTIFY
    grey = RGBColor(0x44, 0x44, 0x44)

    def p(text="", bold=False, size=None, align=None, space_before=0.0, color=None, italic=False):
        para = d.add_paragraph()
        if text:
            run = para.add_run(text)
            run.bold, run.italic = bold, italic
            if size:
                run.font.size = Pt(size)
            if color:
                run.font.color.rgb = RGBColor(*color) if isinstance(color, tuple) else color
        if align is not None:
            para.alignment = align
        para.paragraph_format.space_before = Pt(space_before)
        return para

    def two_sided(left_runs, right: str, italic_right=False, size=None, space_before=0.0):
        para = p(space_before=space_before)
        para.paragraph_format.tab_stops.add_tab_stop(usable, WD_TAB_ALIGNMENT.RIGHT)
        for text, bold, italic, sz, color in left_runs:
            run = para.add_run(text)
            run.bold, run.italic = bold, italic
            run.font.size = Pt(sz)
            if color:
                run.font.color.rgb = color
        if right:
            rr = para.add_run("\t" + right)
            rr.italic = italic_right
            rr.font.size = Pt(size or z["small"])
        return para

    for kind, val in _blocks(r, country, lang):
        if kind == "name":
            p(val, bold=True, size=z["name"], align=WD_ALIGN_PARAGRAPH.CENTER)
        elif kind == "headline":
            p(val, size=z["headline"], align=WD_ALIGN_PARAGRAPH.CENTER, color=NAVY)
        elif kind == "contact":
            para = p(align=WD_ALIGN_PARAGRAPH.CENTER, space_before=2)
            csize = _contact_size(val, z["contact"], usable / 12700, _font()[0])  # EMU -> points
            for i, (text, url) in enumerate(val):
                if i:
                    para.add_run("  |  ").font.size = Pt(csize)
                if url:
                    _docx_link(para, url, text, csize)
                else:
                    para.add_run(text).font.size = Pt(csize)
        elif kind == "heading":
            para = p(val, bold=True, size=z["heading"], space_before=z["gap"], color=NAVY)
            para.paragraph_format.space_after = Pt(z["rule_gap"])
            pPr = para._p.get_or_add_pPr()
            bdr = OxmlElement("w:pBdr")
            b = OxmlElement("w:bottom")
            for k, v in (("w:val", "single"), ("w:sz", "6"), ("w:space", "1"), ("w:color", "1F3A5F")):
                b.set(qn(k), v)
            bdr.append(b)
            pPr.append(bdr)
        elif kind == "para":
            p(val, align=J)
        elif kind == "entry":
            title, suffix, right, sub_l, sub_r = val
            runs = [(title, True, False, z["entry"], None)]
            if suffix:
                runs.append(("  |  " + suffix, False, True, z["small"], grey))
            two_sided(runs, right, size=z["small"], space_before=z["entry_gap"])
            if sub_l or sub_r:
                two_sided([(sub_l, False, True, z["small"], grey)], sub_r, italic_right=True)
        elif kind == "links":
            para = p()
            for i, (label, text, url) in enumerate(val):
                if i:
                    para.add_run("   ·   ").font.size = Pt(z["small"])
                lab = para.add_run(f"{label}: ")
                lab.font.size = Pt(z["small"])
                lab.bold = True
                _docx_link(para, url, text, z["small"])
        elif kind == "bullet":
            para = d.add_paragraph(style="List Bullet")
            para.alignment = J
            para.paragraph_format.left_indent = Cm(0.55)  # wrapped lines align with the text, not the bullet
            para.paragraph_format.first_line_indent = Cm(-0.35)
            para.add_run(val).font.size = Pt(z["body"])
        elif kind == "kv":
            para = p(align=J)
            para.add_run(val[0] + ": ").bold = True
            para.add_run(val[1])
    d.core_properties.title = f"{r.get('name','')} – Resume"
    d.core_properties.author = r.get("name", "")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


_FONT = None
_ITALIC = None
_GLYPHS: set[int] | None = None


def _font() -> tuple[str, str]:
    """Use a Unicode TTF if available (₹, ä, ö, ü), else Helvetica."""
    global _FONT, _ITALIC, _GLYPHS
    if _FONT:
        return _FONT
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    candidates = [  # (regular, bold, italic)
        ("C:/Windows/Fonts/calibri.ttf", "C:/Windows/Fonts/calibrib.ttf", "C:/Windows/Fonts/calibrii.ttf"),
        ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/ariali.ttf"),
        ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf", "/Library/Fonts/Arial Italic.ttf"),
        ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
         "/System/Library/Fonts/Supplemental/Arial Italic.ttf"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"),
        ("/usr/share/fonts/TTF/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", "/usr/share/fonts/TTF/DejaVuSans-Oblique.ttf"),
        ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf"),
    ]
    for reg, bold, ital in candidates:
        if os.path.exists(reg) and os.path.exists(bold):
            try:
                regular = TTFont("RFont", reg)
                pdfmetrics.registerFont(regular)
                pdfmetrics.registerFont(TTFont("RFont-Bold", bold))
                from reportlab.lib.fonts import addMapping
                addMapping("RFont", 0, 0, "RFont")
                addMapping("RFont", 1, 0, "RFont-Bold")
                _ITALIC = "RFont"
                if os.path.exists(ital):
                    pdfmetrics.registerFont(TTFont("RFont-Italic", ital))
                    addMapping("RFont", 0, 1, "RFont-Italic")
                    _ITALIC = "RFont-Italic"
                _GLYPHS = set(regular.face.charToGlyph.keys())
                _FONT = ("RFont", "RFont-Bold")
                return _FONT
            except Exception:
                continue
    _FONT, _ITALIC = ("Helvetica", "Helvetica-Bold"), "Helvetica-Oblique"
    return _FONT


def _italic_font() -> str:
    _font()
    return _ITALIC or "Helvetica-Oblique"


def _safe(s: str, font: str) -> str:
    """Escape for reportlab and make sure every character exists in the font (missing glyphs print as boxes)."""
    import unicodedata
    from xml.sax.saxutils import escape

    s = clean(s or "")
    if font.startswith("Helvetica"):
        s = s.replace("₹", "INR ").replace("–", "-").replace("•", "-")
        s = s.encode("latin-1", "replace").decode("latin-1")
    elif _GLYPHS:
        out = []
        for ch in s:
            if ord(ch) < 128 or ord(ch) in _GLYPHS:
                out.append(ch)
            else:  # closest plain form (é→e, ﬁ→fi), else drop it
                out.append(unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode())
        s = "".join(out)
    return escape(s)


def _render(r: dict, country: str, lang: str, layout) -> tuple[bytes, int, float]:
    """Build the PDF; return (bytes, page count, how full the last page is 0..1)."""
    from reportlab.lib.colors import HexColor
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import HRFlowable, ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Table, TableStyle

    class Doc(SimpleDocTemplate):
        last_y = None

        def afterFlowable(self, flowable):
            self.last_y = self.frame._y

    reg, bold = _font()
    ital = _italic_font()
    z = _sizes(layout)
    navy = HexColor("#%02X%02X%02X" % NAVY)
    link = "#%02X%02X%02X" % LINK
    grey = HexColor("#444444")
    L = z["lead"]
    st = {
        "name": ParagraphStyle("name", fontName=bold, fontSize=z["name"], leading=z["name"] * 1.15, alignment=TA_CENTER),
        "headline": ParagraphStyle("hl", fontName=reg, fontSize=z["headline"], leading=z["headline"] * 1.35,
                                   alignment=TA_CENTER, textColor=navy),
        "contact": ParagraphStyle("ct", fontName=reg, fontSize=z["contact"], leading=z["contact"] * 1.4, alignment=TA_CENTER,
                                  spaceBefore=1),
        "heading": ParagraphStyle("h", fontName=bold, fontSize=z["heading"], leading=z["heading"] * 1.2, textColor=navy,
                                  spaceBefore=z["gap"]),
        "body": ParagraphStyle("b", fontName=reg, fontSize=z["body"], leading=z["body"] * L, alignment=TA_JUSTIFY),
        "entry": ParagraphStyle("e", fontName=bold, fontSize=z["entry"], leading=z["entry"] * L),
        "right": ParagraphStyle("d", fontName=reg, fontSize=z["small"], leading=z["entry"] * L, alignment=2),
        "sub": ParagraphStyle("s", fontName=ital, fontSize=z["small"], leading=z["small"] * L, textColor=grey),
        "sub_r": ParagraphStyle("sr", fontName=ital, fontSize=z["small"], leading=z["small"] * L, textColor=grey, alignment=2),
        "small": ParagraphStyle("sm", fontName=reg, fontSize=z["small"], leading=z["small"] * L, textColor=grey),
    }
    buf = io.BytesIO()
    doc = Doc(buf, pagesize=A4, leftMargin=z["margin_x"] * cm, rightMargin=z["margin_x"] * cm,
              topMargin=z["margin_y"] * cm, bottomMargin=z["margin_y"] * cm,
              title=f"{r.get('name','')} - Resume", author=r.get("name", ""))
    width = doc.width - 12  # frame has 6pt padding on each side
    flow, bullets = [], []
    S = lambda t: _safe(t, reg)  # noqa: E731

    def a(text: str, url: str) -> str:
        return f"<a href='{S(url)}' color='{link}'>{S(text)}</a>"

    def row(left, right, top_pad):
        # 2-cell row only for right-aligned dates/locations; text order stays left→right for parsers
        t = Table([[left, right]], colWidths=[width * 0.76, width * 0.24], hAlign="LEFT")
        t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), top_pad), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                               ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        return t

    bullet_w = width - 12  # text column inside the list indent
    flush_style = ParagraphStyle("bj", parent=st["body"], justifyLastLine=1)

    def bullet_para(text: str) -> Paragraph:
        # a bullet whose last line is nearly full is stretched to the margin too, so it ends flush like the others
        par = Paragraph(S(text), st["body"])
        if last_line_fill(par, bullet_w)[1] >= FLUSH_AT:
            par = Paragraph(S(text), flush_style)
        return par

    def flush():
        nonlocal bullets
        if bullets:
            flow.append(ListFlowable([ListItem(bullet_para(b), leftIndent=10) for b in bullets],
                                     bulletType="bullet", start="•" if reg != "Helvetica" else "-", leftIndent=12,
                                     bulletFontName=reg, bulletFontSize=z["body"]))
            bullets = []

    for kind, val in _blocks(r, country, lang):
        if kind != "bullet":
            flush()
        if kind in ("name", "headline"):
            flow.append(Paragraph(S(val), st[kind]))
        elif kind == "contact":
            size = _contact_size(val, z["contact"], width, reg)
            cst = ParagraphStyle("ct1", parent=st["contact"], fontSize=size, leading=size * 1.4)
            flow.append(Paragraph("  |  ".join(a(t, u) if u else S(t) for t, u in val), cst))
        elif kind == "heading":
            flow.append(Paragraph(S(val), st["heading"]))
            flow.append(HRFlowable(width="100%", thickness=0.8, color=navy, spaceBefore=1.2, spaceAfter=z["rule_gap"]))
        elif kind == "para":
            flow.append(Paragraph(S(val), st["body"]))
        elif kind == "entry":
            title, suffix, right, sub_l, sub_r = val
            from reportlab.pdfbase.pdfmetrics import stringWidth
            if suffix and (stringWidth(title, bold, z["entry"]) + stringWidth("  |  " + suffix, ital, z["small"])) > width * 0.75:
                sub_l, suffix = sub_l or suffix, ""  # long name + tech list: tech moves to the italic second line
            left = S(title) + (f"<font name='{ital}' size='{z['small']:.2f}' color='#444444'>  |  {S(suffix)}</font>" if suffix else "")
            flow.append(row(Paragraph(left, st["entry"]), Paragraph(S(right), st["right"]), z["entry_gap"]))
            if sub_l or sub_r:
                flow.append(row(Paragraph(S(sub_l), st["sub"]), Paragraph(S(sub_r), st["sub_r"]), 0))
        elif kind == "links":
            flow.append(Paragraph("   ·   ".join(f"<font name='{bold}'>{S(lab)}:</font> {a(text, url)}"
                                                 for lab, text, url in val), st["small"]))
        elif kind == "bullet":
            bullets.append(val)
        elif kind == "kv":
            flow.append(Paragraph(f"<font name='{bold}'>{S(val[0])}:</font> {S(val[1])}", st["body"]))
    flush()
    doc.build(flow)
    frame_top = doc.pagesize[1] - doc.topMargin
    fill = (frame_top - (doc.last_y or frame_top)) / doc.height if doc.height else 1.0
    return buf.getvalue(), doc.page, max(0.0, min(1.0, fill))


FLUSH_AT = 0.9  # last line at least this full -> justify it to the margin (lower values open visibly wide word gaps)


def last_line_fill(par, avail: float) -> tuple[int, float]:
    """(number of lines, how full the last line is 0..1) for a reportlab Paragraph at this width."""
    par.wrap(avail, 10_000)
    lines = par.blPara.lines
    if not lines:
        return 0, 0.0
    last = lines[-1]
    extra = last[0] if isinstance(last, tuple) else getattr(last, "extraSpace", 0)
    return len(lines), max(0.0, min(1.0, 1 - extra / avail))


def measure_bullet(text: str, layout=1.0) -> tuple[int, float]:
    """(lines, last-line fill) of one bullet at the final layout."""
    from reportlab.lib.enums import TA_JUSTIFY
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph

    reg, _ = _font()
    z = _sizes(layout)
    style = ParagraphStyle("b", fontName=reg, fontSize=z["body"], leading=z["body"] * z["lead"], alignment=TA_JUSTIFY)
    return last_line_fill(Paragraph(_safe(text, reg), style), A4[0] - 2 * z["margin_x"] * cm - 24)


def bullet_lines(r: dict, country: str = "india", lang: str = "en", layout=1.0) -> list[dict]:
    """Every experience/project bullet with its line count and last-line fill at the final layout — used to ask the
    writer for bullets that end at the right margin (one or two full lines) instead of stopping halfway."""
    from reportlab.lib.enums import TA_JUSTIFY
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph

    reg, _ = _font()
    z = _sizes(layout)
    style = ParagraphStyle("b", fontName=reg, fontSize=z["body"], leading=z["body"] * z["lead"], alignment=TA_JUSTIFY)
    avail = A4[0] - 2 * z["margin_x"] * cm - 12 - 12
    out = []
    for sec in ("experience", "projects"):
        for e in r.get(sec, []):
            for b in e.get("bullets", []):
                n, fill = last_line_fill(Paragraph(_safe(b, reg), style), avail)
                out.append({"entry": e.get("title") or e.get("name", ""), "text": b, "lines": n, "fill": round(fill, 2),
                            "chars": len(b)})
    full = [x for x in out if x["lines"] == 1 and x["fill"] > 0.5]
    per_line = round(sum(x["chars"] / x["fill"] for x in full) / len(full)) if full else 110
    for x in out:
        x["chars_per_line"] = per_line
    return out


def _contact_size(items: list[tuple[str, str]], size: float, width: float, font: str) -> float:
    """Shrink the contact line just enough to keep it on one line (a wrapped header looks broken)."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    text = "  |  ".join(t for t, _ in items)
    w = stringWidth(text, font, size)
    return size if w <= width else max(7.5, size * width / w * 0.99)


def _pdf_bytes(r: dict, country: str, lang: str, layout=1.0) -> bytes:
    return _render(r, country, lang, layout)[0]


def _pages(pdf: bytes) -> int:
    from pypdf import PdfReader

    return len(PdfReader(io.BytesIO(pdf)).pages)


# ---------------------------------------------------------------- one-page fitting
MIN_SCALE, MAX_SCALE = 0.92, 1.12  # body text 9.2pt .. 11.2pt
MAX_SPACE = 2.2


def _relevance(text: str, terms: list[str]) -> int:
    tl = text.lower()
    return sum(1 for t in terms if t and t.lower() in tl)


def _trim_once(r: dict, terms: list[str], lang: str) -> str | None:
    """Remove the single least valuable item; return a human description, or None if nothing sensible is left."""
    def drop_bullet(cap: int) -> str | None:
        best = None  # (relevance, -index, section, entry, bullet_idx)
        for sec in ("experience", "projects"):
            for e in r.get(sec, []):
                bl = e.get("bullets", [])
                if len(bl) > cap:
                    for i, b in enumerate(bl):
                        key = (_relevance(b, terms), -i)
                        if best is None or key < best[0]:
                            best = (key, e, i)
        if best:
            _, e, i = best
            b = e["bullets"].pop(i)
            return f"bullet from {e.get('title') or e.get('name')}: “{b[:70]}…”"
        return None

    def drop_entry(sec: str, cap: int, label: str) -> str | None:
        items = r.get(sec, [])
        if len(items) > cap:
            if sec == "projects":  # least relevant project goes
                i = min(range(len(items)), key=lambda k: (_relevance(json.dumps(items[k]), terms), -k))
            else:  # oldest (last) entry goes
                i = len(items) - 1
            it = items.pop(i)
            return f"{label}: {it.get('name') or it.get('title') or it.get('institution') or str(it)[:40]}"
        return None

    steps = [
        lambda: (r["achievements"].pop() and "achievement") if len(r.get("achievements", [])) > 3 else None,
        lambda: drop_entry("certifications", 3, "certification"),
        lambda: drop_bullet(4),
        lambda: drop_bullet(3),
        lambda: next((f"coursework line from {e.get('institution')}" for e in r.get("education", [])
                      if e.get("details") and e["details"].pop() is not None), None),
        lambda: (r["skills"].pop("soft") and "soft-skills row") if r.get("skills", {}).get("soft") else None,
        lambda: drop_entry("projects", 3, "project"),
        lambda: drop_entry("experience", 3, "experience"),
        lambda: drop_bullet(2),
        lambda: (r["achievements"].pop() and "achievement") if r.get("achievements") else None,
        lambda: drop_entry("certifications", 1, "certification"),
        lambda: drop_entry("projects", 2, "project"),
    ]
    for step in steps:
        done = step()
        if done:
            return done
    return None


def _largest(fits, lo: float, hi: float, steps: int = 7) -> float:
    """Largest x in [lo, hi] with fits(x) (fits is monotone: True for small x)."""
    if fits(hi):
        return hi
    for _ in range(steps):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if fits(mid) else (lo, mid)
    return lo


def fit_one_page(r: dict, country: str = "india", lang: str = "en", terms: list[str] | None = None) -> tuple[dict, dict, list[str]]:
    """Make the resume fill exactly one A4 page.

    Too long: trim the least job-relevant content until it fits at the smallest readable size.
    Too short: grow the font (up to ~11pt), then the spacing between sections, until the page is full.
    Returns (resume, layout {scale, space, fill}, removed items)."""
    r = copy.deepcopy(r)
    r.setdefault("skills", {})
    terms = terms or []
    one = lambda s, sp=1.0: _render(r, country, lang, {"scale": s, "space": sp})[1] <= 1  # noqa: E731
    trims: list[str] = []
    while not one(MIN_SCALE):
        what = _trim_once(r, terms, lang)
        if not what:
            break
        trims.append(what)
    scale = _largest(lambda s: one(s), MIN_SCALE, MAX_SCALE)
    space = _largest(lambda sp: one(scale, sp), 1.0, MAX_SPACE, steps=6)
    _, pages, fill = _render(r, country, lang, {"scale": scale, "space": space})
    if pages > 1:  # safety net: never hand back a layout that spills
        scale, space = MIN_SCALE, 1.0
        _, pages, fill = _render(r, country, lang, {"scale": scale, "space": space})
    # exact values (not rounded): rounding could push the layout over the one-page edge
    return r, {"scale": scale, "space": space, "fill": round(fill, 3), "pages": pages}, trims


def resume_pdf(r: dict, country: str = "india", lang: str = "en", fit: bool = True) -> bytes:
    layout: dict | float = 1.0
    if fit:
        r, layout, _ = fit_one_page(r, country, lang)
    return _pdf_bytes(r, country, lang, layout)


# ---------------------------------------------------------------- Cover letter
def _letter_lines(cl: dict, profile: dict, job: dict, lang: str) -> dict:
    today = date.today().strftime("%d.%m.%Y" if lang == "de" else "%d %B %Y")
    sender = [profile.get("name", ""), profile.get("location", ""), profile.get("phone", ""), profile.get("email", ""),
              short_url(profile.get("linkedin", "")), short_url(profile.get("portfolio", "") or profile.get("github", ""))]
    recipient = [job.get("company", ""), job.get("location", "")]
    return {"sender": [s for s in sender if s], "recipient": [s for s in recipient if s], "date": today,
            "subject": cl.get("subject", ""), "greeting": cl.get("greeting", ""), "paragraphs": cl.get("paragraphs", []),
            "closing": cl.get("closing", "Best regards," if lang != "de" else "Mit freundlichen Grüßen"),
            "signature": cl.get("signature") or profile.get("name", "")}


def cover_docx(cl: dict, profile: dict, job: dict, lang: str = "en") -> bytes:
    import docx
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt

    L = _letter_lines(cl, profile, job, lang)
    d = docx.Document()
    s = d.sections[0]
    s.page_width, s.page_height = Cm(21.0), Cm(29.7)
    s.left_margin = s.right_margin = Cm(2.2)
    d.styles["Normal"].font.name = "Calibri"
    d.styles["Normal"].font.size = Pt(11)
    for line in L["sender"]:
        d.add_paragraph(line).paragraph_format.space_after = Pt(0)
    d.add_paragraph()
    for line in L["recipient"]:
        d.add_paragraph(line).paragraph_format.space_after = Pt(0)
    dp = d.add_paragraph(L["date"])
    dp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    d.add_paragraph().add_run(L["subject"]).bold = True
    d.add_paragraph(L["greeting"])
    for para in L["paragraphs"]:
        d.add_paragraph(para).paragraph_format.space_after = Pt(8)
    d.add_paragraph(L["closing"])
    d.add_paragraph(L["signature"])
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def cover_pdf(cl: dict, profile: dict, job: dict, lang: str = "en") -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    reg, bold = _font()
    L = _letter_lines(cl, profile, job, lang)
    body = ParagraphStyle("b", fontName=reg, fontSize=11, leading=15, spaceAfter=8)
    tight = ParagraphStyle("t", parent=body, spaceAfter=0)
    right = ParagraphStyle("r", parent=body, alignment=2)
    subj = ParagraphStyle("s", parent=body, fontName=bold)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2.2 * cm, rightMargin=2.2 * cm, topMargin=2 * cm, bottomMargin=2 * cm)
    f = [Paragraph(_safe(x, reg), tight) for x in L["sender"]] + [Spacer(1, 14)]
    f += [Paragraph(_safe(x, reg), tight) for x in L["recipient"]]
    f += [Paragraph(_safe(L["date"], reg), right), Spacer(1, 6), Paragraph(_safe(L["subject"], reg), subj),
          Paragraph(_safe(L["greeting"], reg), body)]
    f += [Paragraph(_safe(x, reg), body) for x in L["paragraphs"]]
    f += [Paragraph(_safe(L["closing"], reg), tight), Spacer(1, 18), Paragraph(_safe(L["signature"], reg), body)]
    doc.build(f)
    return buf.getvalue()
