"""Text helpers shared by parsers, chunker and guard."""

import math
import re
import unicodedata

# Section codes used by the sample material: GS-01, AUTO-03, COMMON-02, GS-CLASS-01, AUTO-CLASS-02 ...
SECTION_CODE_RE = re.compile(r"^(?P<code>[A-Z][A-Z0-9]*(?:-[A-Z][A-Z0-9]*)*-\d{2,})\s+(?P<title>\S.*)$")
DOC_CODE_RE = re.compile(r"Mã tài liệu:\s*(?P<code>[A-Z0-9][A-Z0-9-]*)")
_SENTENCE_END_RE = re.compile(r"(?<=[.!?…:;])\s+|\n+")
_SPACES_RE = re.compile(r"[ \t\u00a0]+")


def split_heading(text: str) -> tuple[str | None, str]:
    """'AUTO-03  HTTP API' -> ('AUTO-03', 'HTTP API'); headings without a code -> (None, text)."""
    m = SECTION_CODE_RE.match(text.strip())
    if not m:
        return None, text.strip()
    return m.group("code"), m.group("title").strip()


def scope_prefix(section_code: str | None) -> str | None:
    """'AUTO-CLASS-02' -> 'AUTO'. The prefix maps a section to a class (config/classes.yaml)."""
    return section_code.split("-", 1)[0] if section_code else None


def clean(text: str) -> str:
    """Collapse runs of spaces, strip each line, drop empty lines."""
    lines = (_SPACES_RE.sub(" ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def estimate_tokens(text: str) -> int:
    """Rough token estimate (≈3 characters per token for Vietnamese with diacritics).

    Used only for chunk sizing; billing uses the token counts returned by the provider."""
    return max(1, math.ceil(len(text) / 3))


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_END_RE.split(text) if s and s.strip()]


def fold(text: str) -> str:
    """Lowercase and strip Vietnamese diacritics ('Bỏ qua' -> 'bo qua') for accent-insensitive matching."""
    text = text.lower().replace("đ", "d")
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
