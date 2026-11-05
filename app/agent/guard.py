"""Heuristic guard on the (already redacted) student question (CLAUDE.md §5 step 8, §9).

Three checks, accent-insensitive, Vietnamese + English:
1. prompt_injection      — instructions aimed at the bot (reuses the document rules + question-only rules)
2. secret_exfiltration   — asking for keys/tokens/passwords/config that belong to the system or company
3. cross_class_request   — asking for another class's material

The guard is a first line only: even if it misses something, retrieval is class-filtered in SQL and the prompt
treats every input as data (DECISIONS D-44..D-46).
"""

import re
from dataclasses import dataclass

from app.core.classes import ClassRegistry
from app.db.models import SecurityEventType
from app.ingestion.injection import find_injection
from app.ingestion.text import fold

_QUESTION_INJECTION = tuple(
    re.compile(p)
    for p in (
        r"\b(system prompt|prompt (he thong|goc|cua ban)|chi dan (he thong|cua ban)|huong dan he thong)\b",
        r"\b(your|the) (instructions|rules|prompt|configuration)\b",
        r"\b(bo qua|phot lo|khong can tuan theo|vuot qua) .{0,20}\b(quy tac|gioi han|rang buoc|kiem duyet)\b",
    )
)

_SENSITIVE_NOUN = (
    r"(api[ _-]?key|khoa api|key|token|mat khau|password|secret|credential|bien moi truong|env|\.env"
    r"|cau hinh (he thong|server|bot)|webhook (dang chay|that|production)|tai khoan (n8n|admin|quan tri))"
)
_REQUEST_VERB = (
    r"(xin|cho (toi|minh|em|tui|anh|chi)( xin| muon| xem| biet)?|gui (cho|giup)|cung cap|chia se"
    r"|share|give|send|tell|show|what is|la gi|la bao nhieu|doc|lay)"
)
_OWNER = (
    r"(noi bo|cua (gostech|gos|cong ty|he thong|bot|ban|admin|server|trung tam|giang vien)|that su|dang dung"
    r"|production|internal|company|your|system)"
)
_EXFILTRATION = re.compile(
    # "cho mình xin API key nội bộ của GOSTECH"
    rf"\b{_REQUEST_VERB}\b.{{0,40}}\b{_SENSITIVE_NOUN}\b.{{0,40}}\b{_OWNER}\b"
    # "nội bộ ... token"
    rf"|\b{_OWNER}\b.{{0,15}}\b{_SENSITIVE_NOUN}\b"
    # "token của hệ thống là gì?"
    rf"|\b{_SENSITIVE_NOUN}\b.{{0,15}}\b{_OWNER}\b.{{0,25}}\b(la gi|la bao nhieu|o dau|the nao)\b"
)
_OTHER_CLASS_GENERIC = re.compile(r"\b(lop|class|nhom) (hoc )?(khac|ben canh|kia)\b|\bother class(es)?\b")


@dataclass(frozen=True)
class GuardVerdict:
    blocked: bool
    event_type: SecurityEventType | None = None
    rule: str | None = None  # short id of the matching rule, safe to log


ALLOW = GuardVerdict(False)


def check_question(question: str, class_id: str, registry: ClassRegistry) -> GuardVerdict:
    """Return a blocking verdict for the first rule that matches, else ALLOW."""
    folded = fold(question)

    if find_injection(question) or any(p.search(folded) for p in _QUESTION_INJECTION):
        return GuardVerdict(True, SecurityEventType.PROMPT_INJECTION, "injection")
    if _EXFILTRATION.search(folded):
        return GuardVerdict(True, SecurityEventType.SECRET_EXFILTRATION, "secret_request")
    if _mentions_other_class(folded, class_id, registry):
        return GuardVerdict(True, SecurityEventType.CROSS_CLASS_REQUEST, "other_class")
    return ALLOW


def _mentions_other_class(folded: str, class_id: str, registry: ClassRegistry) -> bool:
    if _OTHER_CLASS_GENERIC.search(folded):
        return True
    for other in registry.classes:
        if other.id == class_id:
            continue
        if fold(other.id) in folded:
            return True
        # "lớp Google Sheets", "class n8n", "nhóm automation" ... (a bare tool name is fine: n8n can write to
        # Google Sheets, so only "<lớp|class|nhóm> <alias>" counts)
        for alias in other.aliases:
            if re.search(rf"\b(lop|class|nhom|khoa)( hoc)? {re.escape(fold(alias))}\b", folded):
                return True
    return False
