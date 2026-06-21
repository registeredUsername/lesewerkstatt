"""
db.py — SQLite helpers (mono-utilisateur, pas d'ORM).
"""

import os
import sqlite3
import json
from pathlib import Path

DB_PATH = os.environ.get("DB_PATH", "data/lese.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  title        TEXT NOT NULL,
  source_label TEXT NOT NULL DEFAULT 'Source',
  category     TEXT NOT NULL DEFAULT 'aktuell',
  url          TEXT,
  lang         TEXT NOT NULL DEFAULT 'de',
  text         TEXT NOT NULL,
  gloss_json   TEXT NOT NULL DEFAULT '[]',
  word_count   INTEGER NOT NULL DEFAULT 0,
  gloss_count  INTEGER NOT NULL DEFAULT 0,
  created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS saved_words (
  surface    TEXT PRIMARY KEY,
  display    TEXT NOT NULL,
  fr         TEXT NOT NULL,
  lemma      TEXT,
  source_id  INTEGER,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _ensure_dir():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)


def get_db() -> sqlite3.Connection:
    _ensure_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript(_SCHEMA)
    conn.close()


# ── Sources ──────────────────────────────────────────────────────────────

def list_sources() -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT id, title, source_label, category, lang, word_count, gloss_count, created_at "
        "FROM sources ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_source(source_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    conn.close()
    if row is None:
        return None
    d = dict(row)
    d["gloss"] = json.loads(d.pop("gloss_json"))
    return d


def insert_source(
    title: str,
    source_label: str,
    category: str,
    url: str | None,
    lang: str,
    text: str,
    gloss: list[dict],
) -> dict:
    gloss_json = json.dumps(gloss, ensure_ascii=False)
    word_count = len(text.split())
    gloss_count = len(gloss)
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO sources (title, source_label, category, url, lang, text, gloss_json, word_count, gloss_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (title, source_label, category, url, lang, text, gloss_json, word_count, gloss_count),
    )
    conn.commit()
    source_id = cur.lastrowid
    conn.close()
    return get_source(source_id)


def delete_source(source_id: int) -> bool:
    conn = get_db()
    cur = conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


# ── Saved Words ──────────────────────────────────────────────────────────

def list_words() -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT surface, display, fr, lemma, source_id, created_at "
        "FROM saved_words ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def upsert_word(
    surface: str, display: str, fr: str, lemma: str | None = None, source_id: int | None = None
) -> dict:
    conn = get_db()
    conn.execute(
        "INSERT INTO saved_words (surface, display, fr, lemma, source_id) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(surface) DO UPDATE SET display=excluded.display, fr=excluded.fr, "
        "lemma=excluded.lemma, source_id=excluded.source_id",
        (surface.lower(), display, fr, lemma, source_id),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM saved_words WHERE surface = ?", (surface.lower(),)).fetchone()
    conn.close()
    return dict(row)


def delete_word(surface: str) -> bool:
    conn = get_db()
    cur = conn.execute("DELETE FROM saved_words WHERE surface = ?", (surface.lower(),))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


def export_words() -> list[dict]:
    """Return words formatted for Anki export."""
    return list_words()
