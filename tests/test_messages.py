"""Handoff wording variants: each one keeps the same facts, and the choice is deterministic per ticket."""

import re

import pytest

from app.agent import messages

HANDOFFS = {
    "no_context": messages.HANDOFF_NO_CONTEXT,
    "policy": messages.HANDOFF_POLICY,
    "low_confidence": messages.HANDOFF_LOW_CONFIDENCE,
    "error": messages.ERROR_FRIENDLY,
}


@pytest.mark.parametrize("reason", HANDOFFS)
def test_every_variant_keeps_the_required_facts(reason: str) -> None:
    variants = HANDOFFS[reason]
    assert len(variants) >= 2 and len(set(variants)) == len(variants)
    for v in variants:
        text = v.format(ticket=messages.ticket_code(12))
        assert text.endswith("#H-0012.") and "giảng viên" in text
        assert re.findall(r"\{\w+\}", v) == ["{ticket}"]  # no other placeholder to fill
        # the only time promise allowed is COMMON-01's "01 ngày làm việc" (COMMON-04: never promise another)
        promises = re.findall(r"\d+\s*(?:ngày|giờ|tiếng|phút|tuần)", text)
        assert promises in ([], ["01 ngày"]), promises
        if reason != "error":
            assert "trong vòng 01 ngày làm việc" in text
        assert any(w in text for w in ("chưa", "tránh", "không tự trả lời"))  # says it did not answer


def test_policy_variants_name_the_topic() -> None:
    assert all("học phí" in v for v in messages.HANDOFF_POLICY)


def test_error_variants_mention_a_temporary_problem() -> None:
    assert all("sự cố tạm thời" in v for v in messages.ERROR_FRIENDLY)


def test_pick_is_deterministic_and_rotates() -> None:
    variants = messages.HANDOFF_NO_CONTEXT
    assert messages.pick(variants, 7) == messages.pick(variants, 7)  # retried job -> same text
    rotated = {messages.pick(variants, i) for i in range(len(variants))}
    assert rotated == set(variants)  # consecutive tickets get different wordings
