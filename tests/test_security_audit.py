"""Self-audit of the 4 hard constraints (docs/TEST_REPORT.md §2). Each test names the constraint it proves.

Other tests that prove them are listed in docs/TEST_REPORT.md ("Ràng buộc cứng → bằng chứng").
"""

import inspect
import logging
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from app.core.classes import get_registry
from app.core.logging import JsonFormatter
from tests.helpers import AUTO_GROUP, payload, send
from tests.test_scenarios import ask

ROOT = Path(__file__).resolve().parents[1]

# Real-looking credentials (longer than any dummy used in tests).
SECRET_SHAPES = {
    "openai": re.compile(r"\bsk-(?:proj-|live-|test-)?[A-Za-z0-9_\-]{32,}"),
    "google": re.compile(r"\bAIza[0-9A-Za-z_\-]{35}"),
    "github": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36}"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}
SECRET_VARS = (
    "WEBHOOK_SECRET",
    "ADMIN_API_KEY",
    "INSTRUCTOR_API_KEYS",
    "ASK_API_KEY",
    "USER_HASH_SALT",
    "POSTGRES_PASSWORD",
)


def _tracked_files() -> list[Path]:
    if shutil.which("git") is None:
        pytest.skip("git not available")
    out = subprocess.run(  # noqa: S603 - fixed command, no user input
        ["git", "ls-files", "-co", "--exclude-standard"],  # noqa: S607
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    return [ROOT / p for p in out.splitlines() if (ROOT / p).is_file()]


# ---------------------------------------------------------------- 1. no secret in the repository / logs


def test_c1_no_credential_in_any_committable_file() -> None:
    hits = []
    for path in _tracked_files():
        if path.suffix.lower() in {".docx", ".xlsx", ".pdf", ".png", ".jpg"}:
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        hits += [
            f"{path.relative_to(ROOT)}: {name}" for name, rx in SECRET_SHAPES.items() if rx.search(content)
        ]
    assert hits == []


def test_c1_env_is_ignored_and_example_holds_placeholders_only() -> None:
    names = {p.relative_to(ROOT).as_posix() for p in _tracked_files()}
    assert ".env" not in names and ".env.example" in names
    check = subprocess.run(  # noqa: S603
        ["git", "check-ignore", "-q", ".env"],  # noqa: S607
        cwd=ROOT, check=False,
    )  # fmt: skip
    assert check.returncode == 0  # .env is ignored
    values = dict(
        line.split("=", 1) for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    )  # fmt: skip
    for var in SECRET_VARS:
        assert "change-me" in values[var], var
    for var in ("OPENAI_API_KEY", "GEMINI_API_KEY"):
        assert values[var].strip() == "", var


@pytest.mark.db
async def test_c1_logs_never_contain_secrets_or_raw_messages(
    kb, llm, client, fake_queue, db_session, caplog
) -> None:
    fake_key = "sk-" + "proj-" + "Lg5" * 10
    caplog.set_level(logging.DEBUG)
    await ask(
        client, fake_queue, db_session, f"/hoi Lỗi 401 xử lý sao? key: {fake_key}", AUTO_GROUP, "hv_log"
    )
    await send(client, payload(text="/hoi test"), secret="wrong-secret")  # invalid signature
    await client.get("/admin/stats", headers={"X-Admin-Key": "test-admin-key"})
    await client.get("/admin/handoffs", headers={"X-Admin-Key": "test-gs-instructor-key"})
    lines = [JsonFormatter().format(r) for r in caplog.records]
    assert lines  # something was logged
    blob = "\n".join(lines)
    secrets = ("test-admin-key", "test-gs-instructor-key", "test-webhook-secret")
    for leaked in (fake_key, *secrets, "Nguyen Van A", "hv_log"):
        assert leaked not in blob, leaked
    assert "Lỗi 401 xử lý sao" not in blob  # no raw message text


# ---------------------------------------------------------------- 2. no data of another class


def test_c2_retrieval_requires_an_explicit_class_id() -> None:
    from app.retrieval import search

    for fn in (search.hybrid_search,):
        param = inspect.signature(fn).parameters["class_id"]
        assert param.default is inspect.Parameter.empty and param.kind is inspect.Parameter.KEYWORD_ONLY
    with pytest.raises(ValueError):
        search.allowed_scopes("COMMON", get_registry())  # COMMON is a shared scope, not a class


def test_c2_class_comes_from_the_group_never_from_the_message() -> None:
    """The webhook payload model has no class field; ingress resolves the class from (channel, group_id)."""
    from app.channels.mock import MockPayload

    assert "class_id" not in MockPayload.model_fields
    source = (ROOT / "app/channels/ingress.py").read_text(encoding="utf-8")
    assert "resolve_class" in source and "msg.group_id" in source


# ---------------------------------------------------------------- 4. no unofficial Zalo automation


def test_c4_no_unofficial_zalo_library_and_stub_only() -> None:
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    names = " ".join(deps["dependencies"] + sum(deps.get("optional-dependencies", {}).values(), [])).lower()
    for banned in ("zalo", "zca", "zlapi", "zalo-api", "selenium", "playwright", "pyautogui"):
        assert banned not in names, banned
    from app.channels.zalo import ZaloGMFAdapter

    with pytest.raises(NotImplementedError):
        ZaloGMFAdapter().parse({})
    # the stub documents what must be verified on the official docs instead of inventing API details
    assert "developers.zalo.me" in (ROOT / "app/channels/zalo.py").read_text(encoding="utf-8")
