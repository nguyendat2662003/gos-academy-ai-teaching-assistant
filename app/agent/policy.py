"""Administrative / sensitive topics (DECISIONS D-05, D-47).

Such questions are handed off to staff by default. They may only be answered when retrieval returns a chunk
in which ONE sentence names the topic and gives a concrete amount or percentage. A chunk that merely says
"there is no fee information" (COMMON-03), or mentions fees next to an unrelated number (COMMON-01: "học phí"
… "trong vòng 01 ngày làm việc"), is not evidence.
"""

import re

from app.ingestion.text import fold

_TOPICS: dict[str, tuple[str, ...]] = {
    "hoc_phi": ("hoc phi", "chi phi khoa hoc", "gia khoa hoc", "bao nhieu tien", "tra gop", "tuition", "fee"),
    "uu_dai": ("giam gia", "giam hoc phi", "uu dai", "khuyen mai", "voucher", "ma giam", "discount"),
    "hoan_tien": ("hoan tien", "hoan phi", "hoan lai tien", "refund"),
    "chung_chi": ("chung chi", "chung nhan", "bang cap", "certificate"),
    "diem": ("diem so", "diem thi", "bang diem", "cham diem", "diem bai tap", "diem cuoi khoa", "grade"),
    "khieu_nai": ("khieu nai", "phan nan", "to cao", "complaint"),
    "ca_nhan": ("thong tin ca nhan", "so dien thoai", "dia chi nha", "cccd", "can cuoc", "so tai khoan"),
}
_PATTERNS = {
    topic: re.compile(r"\b(" + "|".join(re.escape(k) for k in keywords) + r")\b")
    for topic, keywords in _TOPICS.items()
}

# Concrete policy content: an amount of money or a percentage.
_CONCRETE = re.compile(r"\d[\d.,]*\s*(d|vnd|dong|nghin|trieu|k|usd|\$|%|phan tram)(?!\w)")
# Sentences declaring that the information does NOT exist.
_ABSENCE = re.compile(r"\bkhong (co|cung cap|quy dinh)\b.{0,40}\b(thong tin|muc|quy dinh|chinh sach)\b")
_SENTENCE = re.compile(r"(?<=[.!?;])\s+|\n+")


def sensitive_topic(question: str) -> str | None:
    """Return the first sensitive topic the question is about, or None."""
    folded = fold(question)
    for topic, pattern in _PATTERNS.items():
        if pattern.search(folded):
            return topic
    return None


def is_policy_evidence(chunk_text: str, topic: str) -> bool:
    """True if one sentence of the chunk names the topic together with an amount/percentage and is not a
    statement that such information does not exist."""
    return any(
        _PATTERNS[topic].search(sentence) and _CONCRETE.search(sentence) and not _ABSENCE.search(sentence)
        for sentence in _SENTENCE.split(fold(chunk_text))
    )
