"""Greetings and thanks addressed to the bot ("@Trợ lý chào bạn", "cảm ơn ạ"), DECISIONS D-87.

They get a fixed friendly reply: no retrieval, no LLM call, no ticket for the instructor. Only a short message
made *entirely* of greeting/thanks words (plus polite fillers) counts, so "chào bạn, cho mình hỏi SUMIFS" is a
real question and still goes through the normal pipeline. Deterministic: no LLM decides this.
"""

import re
import unicodedata
from typing import Literal

SmallTalk = Literal["greeting", "thanks"]

_GREETING = {"chao", "xin", "hello", "hi", "hey", "alo", "helo"}
_THANKS = {"cam", "on", "camon", "thanks", "thank", "tks", "thx", "ok", "oke", "okay", "okie", "vang", "da"}
_CORE = {"chao", "hello", "hi", "hey", "alo", "helo", "cam", "camon", "thanks", "thank", "tks", "thx",
         "ok", "oke", "okay", "okie"}  # fmt: skip
# Polite words that may surround a greeting: pronouns, the bot's name, particles, times of day.
_FILLER = {
    "ban", "em", "anh", "chi", "minh", "thay", "co", "ca", "nha", "moi", "nguoi", "lop", "ad", "admin",
    "tro", "ly", "bot", "giang", "a", "ah", "oi", "nhe", "nhen", "ne", "nhieu", "rat", "lam",
    "buoi", "sang", "trua", "chieu", "toi", "you", "so", "much", "all", "everyone", "hihi", "haha", "roi",
}  # fmt: skip
_MAX_WORDS = 8


def _words(text: str) -> list[str]:
    folded = unicodedata.normalize("NFD", text.casefold()).replace("đ", "d")
    folded = "".join(ch for ch in folded if unicodedata.category(ch) != "Mn")
    return re.findall(r"[a-z0-9]+", folded)


def classify_smalltalk(question: str) -> SmallTalk | None:
    """Return "greeting" / "thanks" when the whole message is just that, else None (a real question)."""
    words = _words(question)
    if not words or len(words) > _MAX_WORDS or not _CORE.intersection(words):
        return None
    if any(w not in _GREETING | _THANKS | _FILLER for w in words):
        return None
    return "thanks" if _THANKS.intersection(words) - {"da"} else "greeting"
