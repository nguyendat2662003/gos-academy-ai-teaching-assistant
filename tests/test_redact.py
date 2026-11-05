"""Secret redaction. All secrets below are FAKE and built at runtime: no realistic key literal in the repo."""

import pytest

from app.core.redact import MASK, redact

FAKE_OPENAI = "sk-" + "proj-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4"
FAKE_GOOGLE = "AIza" + "Sy" + "A" * 20 + "1234567890xyz"
FAKE_JWT = "eyJ" + "hbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiIxMjM0In0" + "." + "abcDEF123_-xyz"
FAKE_HEX = "0123456789abcdef" * 3


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        (f"key của em là {FAKE_OPENAI} ạ", "openai_key"),
        (f"dùng {FAKE_GOOGLE} được không", "google_key"),
        ("Authorization: Bearer opaqueToken.abc~123", "bearer"),
        (f"token {FAKE_JWT}", "jwt"),
        ("password=Hunter2xyz", "credential_assignment"),
        ("mật khẩu: abc12345", "credential_assignment"),
        ("mat khau la matkhau123", "credential_assignment"),
        (f"webhook secret {FAKE_HEX}", "long_hex"),
        ("chuỗi QWxhZGRpbjpvcGVuIHNlc2FtZTEyMzQ1Njc4OTA lạ", "long_token"),
    ],
)
def test_secrets_are_masked(text: str, kind: str) -> None:
    result = redact(text)
    assert result.found and kind in result.kinds
    assert MASK in result.text
    for secret in (
        FAKE_OPENAI,
        FAKE_GOOGLE,
        FAKE_JWT,
        FAKE_HEX,
        "opaqueToken",
        "Hunter2xyz",
        "abc12345",
        "matkhau123",
    ):
        assert secret not in result.text


@pytest.mark.parametrize(
    "text",
    [
        "Em chạy n8n bị lỗi 401 Unauthorized thì xử lý thế nào?",
        "Cần kiểm tra API key/token và header Authorization",
        '=SUMIFS(Data!$D$2:$D;Data!$A$2:$A;">="&$B$1)',
        "https://docs.google.com/spreadsheets/d/abc/edit",
        "Bài tập nộp trước 22:00 Chủ nhật",
    ],
)
def test_normal_questions_untouched(text: str) -> None:
    assert redact(text).text == text


def test_redaction_is_idempotent_and_keeps_context() -> None:
    once = redact(f"Em dùng key {FAKE_OPENAI} và password=abc12345 bị 401")
    assert redact(once.text).text == once.text
    assert once.text == f"Em dùng key {MASK} và password={MASK} bị 401"
