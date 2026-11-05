from app.core.security import constant_time_equals, hash_user_id, sign_webhook


def test_constant_time_equals() -> None:
    assert constant_time_equals("abc", "abc")
    assert not constant_time_equals("abd", "abc")
    assert not constant_time_equals(None, "abc")


def test_user_hash_is_stable_salted_and_not_reversible() -> None:
    h1 = hash_user_id("user_001", "salt-a")
    assert h1 == hash_user_id("user_001", "salt-a")
    assert h1 != hash_user_id("user_001", "salt-b")
    assert "user_001" not in h1 and len(h1) == 64


def test_sign_webhook_matches_spec() -> None:
    import hashlib
    import hmac

    expected = hmac.new(b"s", b"1700000000." + b'{"a":1}', hashlib.sha256).hexdigest()
    assert sign_webhook("s", "1700000000", b'{"a":1}') == expected
