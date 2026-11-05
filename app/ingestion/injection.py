"""Detect instruction-like sentences aimed at the AI inside documents (DECISIONS D-10).

Only imperative patterns are flagged; a bare keyword such as "API key" is legitimate course content
(AUTO-03, AUTO-04, COMMON-02). Matching is accent-insensitive (Vietnamese with/without diacritics + English).
"""

import re

from app.ingestion.text import fold

_SENSITIVE_TARGETS = (
    r"(system prompt|prompt he thong|chi dan he thong|api[ _-]?key|khoa api|token|mat khau|password|secret"
    r"|bien moi truong|environment variable|cau hinh he thong)"
)

INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        # "ignore / disregard / forget (all) previous instructions"
        r"\b(ignore|disregard|forget|override)\b.{0,30}\b(previous|prior|above|earlier|all|system)\b"
        r".{0,20}\b(instructions?|rules?|prompts?)\b",
        # "bỏ qua / phớt lờ / quên (mọi|tất cả|các) hướng dẫn|chỉ dẫn|quy tắc (trước đó)"
        r"\b(bo qua|phot lo|quen|vo hieu)\b.{0,25}\b(huong dan|chi dan|quy tac|luat|lenh|system prompt)\b",
        # "reveal / print / tiết lộ / in ra … system prompt | API key | mật khẩu …"
        r"\b(reveal|print|show|repeat|output|leak|tiet lo|in ra|hien thi|cho (toi|minh|em) (xem|biet)"
        r"|doc (to|ra))\b.{0,40}" + _SENSITIVE_TARGETS,
        # role hijack: "you are now", "act as", "từ giờ bạn là", "đóng vai"
        r"\b(you are now|act as|pretend to be|from now on you|tu (gio|bay gio|nay) (ban|may) (la|se)"
        r"|dong vai|hay nhap vai)\b",
        # "[developer mode] / jailbreak / DAN"
        r"\b(developer mode|jailbreak|do anything now)\b",
    )
)


def find_injection(text: str) -> str | None:
    """Return the first matching pattern source (for logging), or None."""
    folded = fold(text)
    for pattern in INJECTION_PATTERNS:
        if pattern.search(folded):
            return pattern.pattern
    return None
