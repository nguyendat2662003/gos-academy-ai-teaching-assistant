"""Secret redaction. Applied before anything is stored, logged, queued or sent to an LLM.

Idempotent: redacting already-redacted text changes nothing.
"""

import re
from dataclasses import dataclass, field

MASK = "[ĐÃ_ẨN]"

# (kind, pattern). Order matters: specific formats first, generic long strings last.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private_key",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    ),
    ("openai_key", re.compile(r"\bsk-(?:proj-|live-|test-)?[A-Za-z0-9_\-]{16,}")),
    ("google_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}(?:\.[A-Za-z0-9_\-]+)?")),
    ("bearer", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=\-]{8,}")),
    # key=value / key: value for sensitive names (Vietnamese with or without diacritics, English)
    (
        "credential_assignment",
        re.compile(
            r"(?i)\b(password|passwd|pwd|pass|mật\s*khẩu|mat\s*khau|api[_\s-]?key|secret|token|access[_\s-]?key)"
            r"(\s*[:=]\s*|\s+là\s+|\s+la\s+)[\"']?[^\s\"',;]{4,}"
        ),
    ),
    ("long_hex", re.compile(r"\b[0-9a-fA-F]{32,}\b")),
    # long base64/base64url-like strings that mix letters and digits
    (
        "long_token",
        re.compile(
            r"(?<![A-Za-z0-9+/_\-])(?=[A-Za-z0-9+/_\-]*\d)(?=[A-Za-z0-9+/_\-]*[A-Za-z])"
            r"[A-Za-z0-9+/_\-]{32,}={0,2}"
        ),
    ),
)


@dataclass
class Redaction:
    text: str
    kinds: list[str] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return bool(self.kinds)


def redact(text: str) -> Redaction:
    """Replace secrets with MASK. For key=value forms only the value is masked, so the text stays readable."""
    kinds: list[str] = []
    for kind, pattern in _PATTERNS:

        def _sub(m: re.Match[str], kind: str = kind) -> str:
            kinds.append(kind)
            if kind == "credential_assignment":
                return f"{m.group(1)}{m.group(2)}{MASK}"
            return MASK

        text = pattern.sub(_sub, text)
    return Redaction(text, kinds)
