"""The replay helper must map the sample file's class_id to a group_id (server never trusts class_id)."""

from pathlib import Path

from app.core.classes import get_registry
from scripts.send_mock_event import replay_payloads

SAMPLE = Path("data/samples/_meta/Tin_nhan_mo_phong_TTS.json")


def test_replay_maps_class_to_group_and_adds_trigger() -> None:
    payloads = replay_payloads(SAMPLE, get_registry(), prefix="run1-")
    assert len(payloads) == 8
    by_id = {p["event_id"]: p for p in payloads}
    assert by_id["run1-E001"]["group_id"] == "grp_gs_kpi_01"
    assert by_id["run1-E005"]["group_id"] == "grp_auto_n8n_01"
    for p in payloads:
        assert "class_id" not in p
        assert p["message"]["text"].startswith("/hoi ")
