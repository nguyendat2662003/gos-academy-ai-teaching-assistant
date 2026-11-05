"""Short-term conversation context per (class_id, user_hash) with a TTL (CLAUDE.md §8).

Context of another class is never read: class_id is part of every query.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ConversationTurn


async def load_history(
    session: AsyncSession, *, class_id: str, user_hash: str, max_turns: int, ttl_minutes: int
) -> list[tuple[str, str]]:
    """Last `max_turns` exchanges (user + assistant messages) younger than the TTL, oldest first."""
    if max_turns <= 0:
        return []
    since = datetime.now(UTC) - timedelta(minutes=ttl_minutes)
    rows = (
        await session.execute(
            select(ConversationTurn.role, ConversationTurn.content)
            .where(
                ConversationTurn.class_id == class_id,
                ConversationTurn.user_hash == user_hash,
                ConversationTurn.created_at >= since,
            )
            .order_by(ConversationTurn.created_at.desc(), ConversationTurn.id.desc())
            .limit(max_turns * 2)
        )
    ).all()
    return [(role, content) for role, content in reversed(rows)]


def add_exchange(session: AsyncSession, *, class_id: str, user_hash: str, question: str, reply: str) -> None:
    """Queue one exchange on the session. Both texts must already be redacted."""
    session.add(ConversationTurn(class_id=class_id, user_hash=user_hash, role="user", content=question))
    session.add(ConversationTurn(class_id=class_id, user_hash=user_hash, role="assistant", content=reply))
