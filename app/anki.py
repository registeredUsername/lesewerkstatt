"""
anki.py — Anki TSV export for saved words.
"""


def generate_anki_tsv(words: list[dict]) -> str:
    """
    Generate Anki-importable TSV from saved words.
    Format: Basic (and reversed card), deck Deutsch::Lesewerkstatt.
    """
    lines = [
        "#separator:Tab",
        "#notetype:Basic (and reversed card)",
        "#deck:Deutsch::Lesewerkstatt",
    ]
    for w in words:
        surface = w.get("display", w.get("surface", "")).replace("\t", " ")
        fr = w.get("fr", "").replace("\t", " ")
        lemma = (w.get("lemma") or "").replace("\t", " ")
        if lemma:
            fr = f"{fr} [{lemma}]"
        lines.append(f"{surface}\t{fr}")
    return "\n".join(lines) + "\n"
