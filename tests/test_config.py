from app.core.classes import get_registry, load_registry
from app.core.config import Settings, get_settings


def test_secrets_never_appear_in_repr() -> None:
    settings = get_settings()
    dumped = repr(settings) + str(settings.model_dump())
    for secret in ("test-webhook-secret", "test-admin-key", "test-ask-key", "test-salt"):
        assert secret not in dumped


def test_trigger_prefixes_parsed_from_csv(monkeypatch) -> None:
    monkeypatch.setenv("TRIGGER_PREFIXES", "/hoi, /ask ,")
    assert Settings().trigger_prefixes == ["/hoi", "/ask"]  # type: ignore[call-arg]


def test_classes_yaml_is_valid() -> None:
    registry = get_registry()
    ids = {c.id for c in registry.classes}
    assert ids == {"GS-KPI-01", "AUTO-N8N-01"}
    assert registry.shared_scope.id == "COMMON"


def test_registry_rejects_group_mapped_twice(tmp_path) -> None:
    bad = tmp_path / "classes.yaml"
    bad.write_text(
        """
shared_scope: {id: COMMON, name: x}
classes:
  - {id: A-1, name: a, instructor_name: x, instructor_contact: x,
     groups: [{channel: mock, external_group_id: g1}]}
  - {id: B-1, name: b, instructor_name: x, instructor_contact: x,
     groups: [{channel: mock, external_group_id: g1}]}
""",
        encoding="utf-8",
    )
    try:
        load_registry(bad)
    except ValueError as exc:
        assert "more than one class" in str(exc)
    else:
        raise AssertionError("expected ValueError")
