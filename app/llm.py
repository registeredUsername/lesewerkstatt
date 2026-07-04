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

ANKI_ENTRY_PROMPT_DE = (
    "Tu aides un francophone à créer une fiche Anki pour un mot ALLEMAND.\n"
    "L'utilisateur te donne un mot allemand (possiblement fléchi). Tu dois renvoyer :\n"
    "1. \"de\" : la forme de citation / dictionnaire. Pour un nom → avec article (der/die/das). "
    "Pour un verbe → infinitif. Pour un adjectif → forme de base.\n"
    "2. \"fr\" : traduction française concise (plusieurs sens séparés par ' ou ' si pertinent).\n"
    "3. \"decomposition\" : UNIQUEMENT si le mot est un composé (Zusammensetzung), un verbe à "
    "préfixe séparable/inséparable, ou a une structure morphologique intéressante. "
    "Chaque élément : {\"part\": \"morceau\", \"meaning\": \"sens du morceau en français\"}. "
    "Liste VIDE si le mot est simple.\n\n"
    "Réponds UNIQUEMENT par un objet JSON, sans texte autour, sans balises markdown :\n"
    '{"de": "...", "fr": "...", "decomposition": [...]}'
)

ANKI_ENTRY_PROMPT_FR = (
    "Tu aides un francophone à créer une fiche Anki pour un mot FRANÇAIS qu'il veut apprendre en allemand.\n"
    "L'utilisateur te donne un mot français. Tu dois :\n"
    "1. Trouver l'équivalent allemand courant. Pour un nom → avec article (der/die/das). "
    "Pour un verbe → infinitif. Pour un adjectif → forme de base.\n"
    "2. \"fr\" : la traduction française à mettre au verso (proche du mot donné, "
    "éventuellement légèrement clarifiée si ambigu).\n"
    "3. \"decomposition\" : décomposition morphologique du mot ALLEMAND trouvé, "
    "UNIQUEMENT si pertinent (composé, verbe à préfixe, etc.). Liste VIDE sinon.\n\n"
    "Réponds UNIQUEMENT par un objet JSON, sans texte autour, sans balises markdown :\n"
    '{"de": "...", "fr": "...", "decomposition": [...]}'
)

_MAX_RETRIES = 3
_BACKOFF_SECS = [1, 2, 4]


def _call_llm_raw(
    system_prompt: str, user_content: str,
    temperature: float = 0.2, max_tokens: int = 1500, timeout: int = 90,
) -> str:
    """
    Shared HTTP call with retry/backoff. Returns raw content string.
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
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }

    last_err = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=timeout)
            if resp.status_code == 429:
                wait = _BACKOFF_SECS[min(attempt, len(_BACKOFF_SECS) - 1)]
                logger.warning(f"Rate limited (429), retrying in {wait}s (attempt {attempt + 1})")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
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


def call_llm(chunk: str) -> list[dict]:
    """
    Send a single text chunk to the LLM. Returns parsed glossary entries.
    Raises on unrecoverable errors.
    """
    raw = _call_llm_raw(SYSTEM_PROMPT, "--- TEXTE ---\n" + chunk, temperature=0.2, max_tokens=1500, timeout=90)
    return _parse_gloss(raw)


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
    raw = _call_llm_raw(TRANSLATE_PROMPT, chunk, temperature=0.3, max_tokens=3000, timeout=120)
    return raw.strip()


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


# ── Anki entry generation ────────────────────────────────────────────────

def _parse_anki_entry(raw: str) -> dict:
    """
    Tolerant JSON parsing for anki entry: strip markdown fences,
    find the JSON object, validate fields.
    """
    if not raw:
        raise RuntimeError("Empty LLM response")

    s = raw.replace("```json", "").replace("```", "").strip()

    # Find the JSON object
    idx = s.find("{")
    if idx >= 0:
        s = s[idx:]

    # Try direct parse
    obj = None
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        # Truncated: cut to last closing brace
        last_brace = s.rfind("}")
        if last_brace > 0:
            try:
                obj = json.loads(s[: last_brace + 1])
            except json.JSONDecodeError:
                pass

    if not isinstance(obj, dict):
        raise RuntimeError(f"Could not parse LLM response as JSON object: {raw[:200]}")

    de = (obj.get("de") or "").strip()
    fr = (obj.get("fr") or "").strip()
    if not de or not fr:
        raise RuntimeError(f"LLM response missing 'de' or 'fr' fields: {raw[:200]}")

    decomposition = []
    for item in (obj.get("decomposition") or []):
        if isinstance(item, dict):
            part = (item.get("part") or "").strip()
            meaning = (item.get("meaning") or "").strip()
            if part and meaning:
                decomposition.append({"part": part, "meaning": meaning})

    return {"de": de, "fr": fr, "decomposition": decomposition}


def generate_anki_entry(word: str, direction: str) -> dict:
    """
    Generate an Anki entry for a word. direction = 'de' or 'fr'.
    Returns {"de": str, "fr": str, "decomposition": [{"part": str, "meaning": str}]}.
    """
    if direction not in ("de", "fr"):
        raise ValueError(f"direction must be 'de' or 'fr', got '{direction}'")

    prompt = ANKI_ENTRY_PROMPT_DE if direction == "de" else ANKI_ENTRY_PROMPT_FR
    raw = _call_llm_raw(prompt, word, temperature=0.2, max_tokens=800, timeout=60)
    return _parse_anki_entry(raw)
