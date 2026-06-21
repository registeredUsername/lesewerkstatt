"""
llm.py — Appel Infomaniak AI (compatible OpenAI) + parsing glossaire.
"""

import json
import os
import time
import logging

import httpx

logger = logging.getLogger(__name__)

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "google/gemma-4-31B-it")

SYSTEM_PROMPT = (
    "Tu aides un médecin-informaticien francophone (suisse) à lire de l'allemand "
    "(santé numérique, actualité, gaming, IA). On te donne un texte allemand. "
    "Extrais TOUS les mots et expressions qui pourraient poser la moindre difficulté à un apprenant B1-B2 : "
    "termes spécialisés, noms composés, verbes à préfixe, mots abstraits, peu fréquents, ou expressions idiomatiques. "
    "Traduis très généreusement (n'hésite pas à traduire 1 mot sur 3 si nécessaire). N'omets aucun mot complexe.\n"
    "Réponds UNIQUEMENT par un tableau JSON, sans texte autour, sans balises markdown. "
    'Chaque élément : {"w":"forme EXACTE telle qu\'elle apparaît dans le texte",'
    '"fr":"traduction française concise","lemma":"infinitif ou forme de base, avec '
    'article pour les noms","note":"optionnel: décomposition préfixe+racine ou nom '
    'composé, très court"}. Garde "fr" court. Omets "note" si rien d\'utile.'
)

TRANSLATE_PROMPT = (
    "Tu es un traducteur expert. Traduis le texte suivant en allemand.\n"
    "Le niveau cible doit être un allemand de tous les jours, style presse/magazine (B1-B2), "
    "ni trop enfantin ni trop académique. Conserve scrupuleusement la structure des paragraphes "
    "et le sens original du texte. Réponds UNIQUEMENT avec la traduction en allemand, sans aucun autre commentaire."
)

_MAX_RETRIES = 3
_BACKOFF_SECS = [1, 2, 4]


def call_llm(chunk: str) -> list[dict]:
    """
    Send a single text chunk to the LLM. Returns parsed glossary entries.
    Raises on unrecoverable errors.
    """
    if not LLM_BASE_URL or not LLM_API_KEY:
        raise RuntimeError("LLM_BASE_URL and LLM_API_KEY must be set")

    url = f"{LLM_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": LLM_MODEL,
        "temperature": 0.2,
        "max_tokens": 1500,
        "stream": False,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "--- TEXTE ---\n" + chunk},
        ],
    }

    last_err = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=90)
            if resp.status_code == 429:
                wait = _BACKOFF_SECS[min(attempt, len(_BACKOFF_SECS) - 1)]
                logger.warning(f"Rate limited (429), retrying in {wait}s (attempt {attempt + 1})")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            raw = data["choices"][0]["message"]["content"]
            return _parse_gloss(raw)
        except httpx.HTTPStatusError as e:
            last_err = e
            if e.response.status_code == 429:
                wait = _BACKOFF_SECS[min(attempt, len(_BACKOFF_SECS) - 1)]
                logger.warning(f"Rate limited (429), retrying in {wait}s (attempt {attempt + 1})")
                time.sleep(wait)
                continue
            raise
        except Exception as e:
            last_err = e
            if attempt < _MAX_RETRIES - 1:
                wait = _BACKOFF_SECS[min(attempt, len(_BACKOFF_SECS) - 1)]
                logger.warning(f"LLM call failed ({e}), retrying in {wait}s")
                time.sleep(wait)
            else:
                raise

    raise RuntimeError(f"LLM call failed after {_MAX_RETRIES} retries: {last_err}")


def _parse_gloss(raw: str) -> list[dict]:
    """
    Tolerant JSON parsing: strip markdown fences, find array,
    recover from truncation.
    """
    if not raw:
        return []

    # Strip markdown fences
    s = raw.replace("```json", "").replace("```", "").strip()

    # Find the JSON array
    idx = s.find("[")
    if idx >= 0:
        s = s[idx:]

    # Try direct parse
    try:
        arr = json.loads(s)
        return _validate_entries(arr)
    except json.JSONDecodeError:
        pass

    # Truncated: cut to last complete object and close array
    last_brace = s.rfind("}")
    if last_brace > 0:
        attempt = s[: last_brace + 1] + "]"
        try:
            arr = json.loads(attempt)
            return _validate_entries(arr)
        except json.JSONDecodeError:
            pass

    logger.warning(f"Could not parse LLM response: {raw[:200]}...")
    return []


def _validate_entries(arr: list) -> list[dict]:
    """Keep only entries with non-empty 'w' and 'fr'."""
    result = []
    for item in arr:
        if not isinstance(item, dict):
            continue
        w = (item.get("w") or "").strip()
        fr = (item.get("fr") or "").strip()
        if w and fr:
            entry = {"w": w, "fr": fr}
            lemma = (item.get("lemma") or "").strip()
            note = (item.get("note") or "").strip()
            if lemma:
                entry["lemma"] = lemma
            if note:
                entry["note"] = note
            result.append(entry)
    return result


def generate_glossary(text: str) -> list[dict]:
    """
    Generate glossary for a text. Chunks if > 6000 chars,
    deduplicates by surface (case-insensitive), caps at 60.
    """
    from app.ingest import chunk_text

    chunks = chunk_text(text, max_chars=5000) if len(text) > 6000 else [text]

    all_entries = []
    seen = set()

    for i, chunk in enumerate(chunks):
        logger.info(f"Glossing chunk {i + 1}/{len(chunks)} ({len(chunk)} chars)")
        entries = call_llm(chunk)
        for entry in entries:
            key = entry["w"].lower()
            if key not in seen:
                seen.add(key)
                all_entries.append(entry)

        # Small delay between chunks to respect rate limits
        if i < len(chunks) - 1:
            time.sleep(0.5)

    # Cap at 300 entries to prevent massive payloads
    return all_entries[:300]


def call_translation_llm(chunk: str) -> str:
    """
    Send a text chunk to the LLM for translation to German.
    """
    if not LLM_BASE_URL or not LLM_API_KEY:
        raise RuntimeError("LLM_BASE_URL and LLM_API_KEY must be set")

    url = f"{LLM_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": LLM_MODEL,
        "temperature": 0.3,  # slightly higher for translation flow
        "max_tokens": 3000,
        "stream": False,
        "messages": [
            {"role": "system", "content": TRANSLATE_PROMPT},
            {"role": "user", "content": chunk},
        ],
    }

    last_err = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=120)
            if resp.status_code == 429:
                wait = _BACKOFF_SECS[min(attempt, len(_BACKOFF_SECS) - 1)]
                logger.warning(f"Rate limited (429), retrying in {wait}s (attempt {attempt + 1})")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except httpx.HTTPStatusError as e:
            last_err = e
            if e.response.status_code == 429:
                wait = _BACKOFF_SECS[min(attempt, len(_BACKOFF_SECS) - 1)]
                logger.warning(f"Rate limited (429), retrying in {wait}s (attempt {attempt + 1})")
                time.sleep(wait)
                continue
            raise
        except Exception as e:
            last_err = e
            if attempt < _MAX_RETRIES - 1:
                wait = _BACKOFF_SECS[min(attempt, len(_BACKOFF_SECS) - 1)]
                logger.warning(f"LLM translation failed ({e}), retrying in {wait}s")
                time.sleep(wait)
            else:
                raise

    raise RuntimeError(f"LLM translation failed after {_MAX_RETRIES} retries: {last_err}")


def translate_to_german(text: str) -> str:
    """
    Translate text to German. Chunks if > 4000 chars.
    """
    from app.ingest import chunk_text

    chunks = chunk_text(text, max_chars=4000) if len(text) > 5000 else [text]
    translated_chunks = []

    for i, chunk in enumerate(chunks):
        logger.info(f"Translating chunk {i + 1}/{len(chunks)} ({len(chunk)} chars)")
        translated = call_translation_llm(chunk)
        translated_chunks.append(translated)

        # Small delay between chunks
        if i < len(chunks) - 1:
            time.sleep(0.5)

    return "\n\n".join(translated_chunks)
