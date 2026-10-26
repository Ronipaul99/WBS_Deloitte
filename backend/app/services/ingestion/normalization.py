from __future__ import annotations

import re
import unicodedata

from app.services.ingestion.errors import ChunkingError, ChunkingErrorCode

_HORIZONTAL_WHITESPACE = re.compile(r"[\t \u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]+")
_BLANK_LINES = re.compile(r"\n[ \t]*\n(?:[ \t]*\n)+")
_LINE_TRAILING_SPACE = re.compile(r"[ \t]+\n")


def normalize_extracted_text(text: str) -> str:
    """Normalize parser surface artifacts without rewriting document meaning."""

    if not isinstance(text, str):
        raise ChunkingError(ChunkingErrorCode.DOCUMENT_NORMALIZATION_FAILED)
    try:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        normalized = "".join(
            character
            for character in normalized
            if character in "\n\t"
            or (
                unicodedata.category(character) not in {"Cc", "Cf", "Cs"}
                and character not in {"\ufffe", "\uffff"}
            )
        )
        lines = []
        for line in normalized.split("\n"):
            # Preserve table-cell positions: whitespace around a pipe is canonicalized, not removed.
            line = _HORIZONTAL_WHITESPACE.sub(" ", line).strip()
            line = re.sub(r"\s*\|\s*", " | ", line)
            lines.append(line)
        normalized = "\n".join(lines)
        normalized = _LINE_TRAILING_SPACE.sub("\n", normalized)
        normalized = _BLANK_LINES.sub("\n\n", normalized)
        return normalized.strip()
    except ChunkingError:
        raise
    except Exception:
        raise ChunkingError(ChunkingErrorCode.DOCUMENT_NORMALIZATION_FAILED) from None
