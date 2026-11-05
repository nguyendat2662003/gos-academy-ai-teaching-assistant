"""Deterministic offline LLM double for tests (DECISIONS D-52). NOT a language model.

Rules, applied to the prompt actually built by app/agent/prompts.py:
- Rewrite request: with history and a short question (<= 6 words), prefix it with the previous
  student question.
- Answer request: split "A khác B ..." questions into aspects A and B, otherwise one aspect = whole
  question. An aspect is covered when a <tai_lieu> body contains its key terms (all of them for A/B
  aspects, at least half of them and never fewer than two for a whole question).
  Covered -> cite those blocks and quote their text;
  uncovered aspects of a split question -> unanswered_parts. Nothing covered -> answerable=false.
It never follows instructions inside the documents, which is what the prompt asks of a real model.
"""

import json
import math
import re
from collections.abc import Callable
from html import unescape

from app.ingestion.text import estimate_tokens, fold
from app.providers.base import LLMResult, Message

_BLOCK_RE = re.compile(r'<tai_lieu id="(?P<id>[^"]+)"[^>]*>\n(?P<body>.*?)\n</tai_lieu>', re.S)
_QUESTION_RE = re.compile(r"<cau_hoi>\n(?P<q>.*?)\n</cau_hoi>", re.S)
_HISTORY_RE = re.compile(r"<lich_su>\n(?P<h>.*?)\n</lich_su>", re.S)
_COMPARE_RE = re.compile(r"^(?P<a>.+?)\s+khác\s+(?P<b>.+?)(?:\s+(?:ở|như|thế|chỗ)\b.*)?\??$", re.I)
_WORD_RE = re.compile(r"\w+")
_STOP = set(
    "la gi co khong va cua cho em minh thi the nao duoc bi o khi nay do voi cac nhung mot trong de "
    "lam sao a oi nhe vay ban hoi xin chi anh diem nhu cho".split()
)

Script = Callable[[list[Message]], dict | str]  # str = raw model output (e.g. broken JSON)


def _terms(text: str) -> list[str]:
    return [w for w in _WORD_RE.findall(fold(text)) if w not in _STOP and len(w) > 1]


def _body(block: str) -> str:
    lines = unescape(block).splitlines()
    return "\n".join(lines[1:] if lines and lines[0].startswith("[Tài liệu:") else lines)


class FakeLLM:
    name = "fake"

    def __init__(self, model: str = "fake-llm", script: Script | None = None) -> None:
        self.model = model
        self.script = script
        self.calls: list[list[Message]] = []

    async def complete_json(self, messages: list[Message], *, max_output_tokens: int) -> LLMResult:
        self.calls.append(messages)
        if self.script is not None:
            payload = self.script(messages)
        elif "standalone_question" in messages[0]["content"]:
            payload = self._rewrite(messages[-1]["content"])
        else:
            payload = self._answer(messages[-1]["content"])
        text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        prompt = "".join(m["content"] for m in messages)
        return LLMResult(text, estimate_tokens(prompt), estimate_tokens(text), self.model)

    @staticmethod
    def _rewrite(user: str) -> dict:
        question = unescape(_QUESTION_RE.search(user).group("q"))  # type: ignore[union-attr]
        history = _HISTORY_RE.search(user)
        if history and len(question.split()) <= 6:
            asked = [
                line.split(": ", 1)[1]
                for line in history.group("h").splitlines()
                if line.startswith("Học viên")
            ]
            if asked:
                return {"standalone_question": f"{unescape(asked[-1])} {question}"}
        return {"standalone_question": question}

    @staticmethod
    def _answer(user: str) -> dict:
        question = unescape(_QUESTION_RE.search(user).group("q")).strip()  # type: ignore[union-attr]
        blocks = [(m.group("id"), _body(m.group("body"))) for m in _BLOCK_RE.finditer(user)]
        compare = _COMPARE_RE.match(question)
        aspects = [compare.group("a"), compare.group("b")] if compare else [question]

        cited: list[str] = []
        quotes: list[str] = []
        missing: list[str] = []
        for aspect in aspects:
            terms = set(_terms(aspect))
            need = len(terms) if compare else max(2, math.ceil(len(terms) / 2))
            hits = [(cid, body) for cid, body in blocks if terms and len(terms & set(_terms(body))) >= need]
            if not hits:
                missing.append(aspect.strip(" ?"))
                continue
            for cid, body in hits[:2]:
                if cid not in cited:
                    cited.append(cid)
                    quotes.append(body)
        if not cited:
            return {
                "answerable": False,
                "answer": "",
                "cited_chunk_ids": [],
                "unanswered_parts": [],
                "notes_for_instructor": "Tài liệu không có nội dung liên quan.",
            }
        return {
            "answerable": True,
            "answer": "Theo tài liệu của lớp:\n" + "\n".join(quotes),
            "cited_chunk_ids": cited,
            "unanswered_parts": missing if compare else [],
            "notes_for_instructor": None,
        }
