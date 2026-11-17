"""Read an uploaded resume (PDF / DOCX / TXT) and turn it into a structured profile with Groq."""
from __future__ import annotations

import io

from . import groq_client
from .profile_schema import normalize


def extract_links(filename: str, data: bytes) -> list[str]:
    """Hyperlinks hidden behind text ("GitHub", "Live demo") — they are not in the extracted text."""
    name = filename.lower()
    urls: list[str] = []
    try:
        if name.endswith(".pdf"):
            from pypdf import PdfReader

            for page in PdfReader(io.BytesIO(data)).pages:
                for annot in page.get("/Annots") or []:
                    uri = (annot.get_object().get("/A") or {}).get("/URI")
                    if uri:
                        urls.append(str(uri))
        elif name.endswith(".docx"):
            import docx

            d = docx.Document(io.BytesIO(data))
            urls += [r.target_ref for r in d.part.rels.values() if "hyperlink" in r.reltype]
    except Exception:  # a broken annotation must not block the import
        pass
    return list(dict.fromkeys(u.strip() for u in urls if u.strip() and not u.lower().startswith("mailto:")))


def extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    elif name.endswith(".docx"):
        import docx

        d = docx.Document(io.BytesIO(data))
        lines = [p.text for p in d.paragraphs]
        for t in d.tables:
            for row in t.rows:
                lines.append(" | ".join(c.text for c in row.cells))
        text = "\n".join(lines)
    else:
        text = None
    if text is not None:
        links = extract_links(filename, data) if text.strip() else []
        return text + ("\n\nHYPERLINKS IN FILE (in order of appearance):\n" + "\n".join(links) if links else "")
    if name.endswith((".txt", ".md")):
        return data.decode("utf-8", errors="ignore")
    raise ValueError("Unsupported file type. Upload a PDF, DOCX or TXT resume.")


from .prompts import PARSER as SYSTEM


async def parse_resume(filename: str, data: bytes) -> tuple[dict, str]:
    text = extract_text(filename, data)
    if len(text.strip()) < 50:
        raise ValueError("Could not read text from the file (is it a scanned image?). Try a DOCX or fill the profile form.")
    out = await groq_client.chat_json(SYSTEM, f"RESUME TEXT:\n\n{text[:15000]}", temperature=0.0)
    return normalize(out), text
