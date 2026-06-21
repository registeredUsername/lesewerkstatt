"""
main.py — FastAPI application: routes + static file serving.
"""

import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, PlainTextResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import db
from app.ingest import extract_from_url, extract_from_pdf, detect_language, validate_text
from app.llm import generate_glossary
from app.anki import generate_anki_tsv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Lesewerkstatt", version="1.0.0")

# ── Startup ──────────────────────────────────────────────────────────────

@app.on_event("startup")
def startup():
    db.init_db()
    logger.info("Database initialized")


# ── Health ───────────────────────────────────────────────────────────────

@app.get("/healthz")
def healthz():
    return {"ok": True}


# ── Source Models ────────────────────────────────────────────────────────

class SourceURLBody(BaseModel):
    url: str
    source_label: Optional[str] = None
    category: Optional[str] = "aktuell"

class SourceTextBody(BaseModel):
    text: str
    title: str
    source_label: Optional[str] = "Source"
    category: Optional[str] = "aktuell"


# ── Sources API ──────────────────────────────────────────────────────────

@app.get("/api/sources")
def list_sources():
    return db.list_sources()


@app.get("/api/sources/{source_id}")
def get_source(source_id: int):
    source = db.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source non trouvée")
    return source


@app.post("/api/sources", status_code=201)
async def create_source(
    # Support both JSON and multipart
    url: Optional[str] = Form(None),
    text: Optional[str] = Form(None),
    title: Optional[str] = Form(None),
    source_label: Optional[str] = Form("Source"),
    category: Optional[str] = Form("aktuell"),
    file: Optional[UploadFile] = File(None),
):
    """
    Add a source. Three modes:
    1. URL: provide `url` field
    2. Pasted text: provide `text` + `title`
    3. PDF upload: provide `file` (multipart)
    """
    extracted_text = None
    extracted_title = title or ""
    source_url = url
    warning = None

    try:
        if file and file.filename:
            # Mode 3: PDF upload
            contents = await file.read()
            extracted_text, pdf_title = extract_from_pdf(contents)
            if not extracted_title:
                extracted_title = pdf_title or file.filename.replace(".pdf", "")
            source_url = None

        elif url:
            # Mode 1: URL
            extracted_text, url_title = extract_from_url(url)
            if not extracted_title:
                extracted_title = url_title

        elif text:
            # Mode 2: Pasted text
            extracted_text = text
            if not extracted_title:
                raise HTTPException(status_code=400, detail="Le titre est requis pour un texte collé")

        else:
            raise HTTPException(
                status_code=400,
                detail="Fournis une URL, un texte (avec titre), ou un fichier PDF."
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        raise HTTPException(status_code=422, detail=str(e))

    # Validate text quality
    err = validate_text(extracted_text)
    if err:
        raise HTTPException(status_code=422, detail=err)

    # Detect language
    lang = detect_language(extracted_text)
    if lang != "de":
        try:
            from app.llm import translate_to_german
            extracted_text = translate_to_german(extracted_text)
            warning = f"Texte traduit automatiquement vers l'allemand (langue originale : {lang})."
            extracted_title = f"{extracted_title} [Traduit]"
        except Exception as e:
            logger.error(f"Translation failed: {e}")
            raise HTTPException(
                status_code=502,
                detail=f"La traduction vers l'allemand a échoué : {e}"
            )

    # Generate glossary via LLM
    try:
        gloss = generate_glossary(extracted_text)
    except Exception as e:
        logger.error(f"LLM glossary generation failed: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"L'appel au modèle de langue a échoué : {e}"
        )

    # Store
    source = db.insert_source(
        title=extracted_title,
        source_label=source_label or "Source",
        category=category or "aktuell",
        url=source_url,
        lang=lang,
        text=extracted_text,
        gloss=gloss,
    )

    response = source
    if warning:
        response = {**source, "warning": warning}

    return response


@app.delete("/api/sources/{source_id}")
def delete_source(source_id: int):
    if not db.delete_source(source_id):
        raise HTTPException(status_code=404, detail="Source non trouvée")
    return {"ok": True}


# ── Word Models ──────────────────────────────────────────────────────────

class WordBody(BaseModel):
    surface: str
    display: str
    fr: str
    lemma: Optional[str] = None
    source_id: Optional[int] = None


# ── Words API ────────────────────────────────────────────────────────────

@app.get("/api/words")
def list_words():
    return db.list_words()


@app.post("/api/words", status_code=201)
def create_word(body: WordBody):
    return db.upsert_word(
        surface=body.surface,
        display=body.display,
        fr=body.fr,
        lemma=body.lemma,
        source_id=body.source_id,
    )


@app.delete("/api/words/{surface}")
def delete_word(surface: str):
    if not db.delete_word(surface):
        raise HTTPException(status_code=404, detail="Mot non trouvé")
    return {"ok": True}


@app.get("/api/words/export")
def export_words():
    words = db.export_words()
    tsv = generate_anki_tsv(words)
    return PlainTextResponse(
        content=tsv,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="lesewerkstatt_anki.txt"'
        },
    )


# ── Static files + SPA fallback ─────────────────────────────────────────

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# Mount static files for assets (js, css, icons, manifest, sw)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static_assets")


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")
