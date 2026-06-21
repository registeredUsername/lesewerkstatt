"""
ingest.py — Text extraction from URLs, PDFs, and pasted text.
"""

import io
import httpx
import trafilatura
from pypdf import PdfReader
from langdetect import detect

# Browser-like UA for fetching URLs
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


def extract_from_url(url: str) -> tuple[str, str]:
    """
    Fetch URL, extract text. Returns (text, title).
    Raises ValueError on failure.
    """
    try:
        from curl_cffi import requests
        resp = requests.get(
            url,
            allow_redirects=True,
            timeout=20,
            impersonate="chrome110",
        )
        resp.raise_for_status()
    except Exception as e:
        raise ValueError(
            f"Le site bloque l'extraction automatique (anti-bot/paywall). "
            f"Copiez-collez le texte via l'onglet 'Texte'. (Détail: {str(e)[:50]})"
        )

    content_type = resp.headers.get("content-type", "")

    # PDF response
    if "application/pdf" in content_type or url.lower().endswith(".pdf"):
        text, title = extract_from_pdf(resp.content)
        if not title:
            title = url.split("/")[-1].replace(".pdf", "").replace("%20", " ")
        return text, title

    # HTML → trafilatura
    html = resp.text
    text = trafilatura.extract(
        html,
        include_comments=False,
        favor_recall=True,
    )

    # Title: try trafilatura metadata, fallback to <title>
    title = ""
    meta = trafilatura.extract(html, output_format="xmltei", include_comments=False)
    if meta:
        import re
        m = re.search(r"<title[^>]*>([^<]+)</title>", meta)
        if m:
            title = m.group(1).strip()
    if not title:
        import re
        m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
        if m:
            title = m.group(1).strip()
    if not title:
        title = url

    if not text:
        raise ValueError("Extraction trop faible")

    return text, title


def extract_from_pdf(file_bytes: bytes) -> tuple[str, str]:
    """
    Extract text from PDF bytes. Returns (text, title).
    """
    reader = PdfReader(io.BytesIO(file_bytes))

    # Try to get title from PDF metadata
    title = ""
    if reader.metadata and reader.metadata.title:
        title = reader.metadata.title

    pages = []
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            pages.append(page_text)

    text = "\n\n".join(pages)
    return text, title


def detect_language(text: str) -> str:
    """Detect language of text. Returns ISO 639-1 code."""
    try:
        return detect(text[:2000])
    except Exception:
        return "de"


def validate_text(text: str) -> str | None:
    """
    Returns an error message if text is too short, None if OK.
    """
    if not text or len(text.strip()) < 250:
        return (
            "Extraction trop faible (< 250 caractères). "
            "Le site est peut-être protégé par un paywall ou génère son contenu en JavaScript. "
            "Colle le texte manuellement."
        )
    return None


def chunk_text(text: str, max_chars: int = 5000) -> list[str]:
    """
    Split text into chunks of ~max_chars, breaking at paragraph boundaries.
    """
    if len(text) <= max_chars:
        return [text]

    chunks = []
    paragraphs = text.split("\n\n")
    current = ""

    for para in paragraphs:
        if len(current) + len(para) + 2 > max_chars and current:
            chunks.append(current.strip())
            current = para
        else:
            current = current + "\n\n" + para if current else para

    if current.strip():
        chunks.append(current.strip())

    return chunks if chunks else [text]
