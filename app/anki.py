"""
anki.py — Anki TSV export for saved words.
"""


def generate_anki_tsv(words: list[dict]) -> str:
    """
    Generate Anki-importable TSV from saved words.
    Format: Basic (single direction DE→FR), deck Deutsch::Lesewerkstatt.
    HTML enabled for decomposition bullets.
    """
    lines = [
        "#separator:Tab",
        "#notetype:Basic",
        "#deck:Deutsch::Lesewerkstatt",
        "#html:true",
    ]
    for w in words:
        recto = w.get("display", w.get("surface", "")).replace("\t", " ")
        fr = w.get("fr", "").replace("\t", " ")
        lemma = (w.get("lemma") or "").replace("\t", " ")
        note = (w.get("note") or "").strip()

        # Build verso: fr [lemma] + decomposition
        verso = fr
        if lemma:
            verso += f" [{lemma}]"
        if note:
            # Convert "- part : meaning" lines to "• part : meaning<br>"
            bullets = []
            for line in note.split("\n"):
                line = line.strip()
                if line.startswith("- "):
                    line = line[2:]
                if line:
                    bullets.append(f"• {line}")
            if bullets:
                verso += "<br>" + "<br>".join(bullets)

        lines.append(f"{recto}\t{verso}")
    return "\n".join(lines) + "\n"

