"""Small security helpers: constant-time comparison, user pseudonymisation, HMAC signing.

Secret redaction is added in Phase 4.
"""

import hashlib
import hmac


def constant_time_equals(provided: str | None, expected: str) -> bool:
    """Compare two secrets without leaking timing information."""
    if provided is None:
        return False
    return hmac.compare_digest(provided.encode(), expected.encode())


def hash_user_id(user_id: str, salt: str) -> str:
    """Pseudonymise a platform user id: HMAC-SHA256(user_id, salt), hex encoded."""
    return hmac.new(salt.encode(), user_id.encode(), hashlib.sha256).hexdigest()


def sign_webhook(secret: str, timestamp: str, raw_body: bytes) -> str:
    """Compute the mock-webhook signature: hex(HMAC_SHA256(secret, f"{timestamp}.{raw_body}"))."""
    message = timestamp.encode() + b"." + raw_body
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
