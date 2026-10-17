"""Phase 10 pricing: record and price input written to the provider's prompt cache.

Claude charges more for cache writes than for plain input (1.25x for the 5-minute cache), so
``usage_events`` gains ``cache_write_input_tokens`` (the part of ``input_tokens`` written to
the cache; existing rows get 0) and the ``prices`` resource check gains
``llm_cache_write_input_tokens``. Additive only: no data changes, row-level security on
``usage_events`` is unchanged, and no new table.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-17 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = (
    "'llm_input_tokens', 'llm_cached_input_tokens', 'llm_output_tokens', 'stt_seconds', "
    "'tts_characters', 'telephony_seconds'"
)
_NEW = (
    "'llm_input_tokens', 'llm_cached_input_tokens', 'llm_cache_write_input_tokens', "
    "'llm_output_tokens', 'stt_seconds', 'tts_characters', 'telephony_seconds'"
)


def _replace_check(values: str) -> None:
    op.drop_constraint(op.f("ck_prices_resource"), "prices", type_="check")
    op.create_check_constraint(op.f("ck_prices_resource"), "prices", f"resource IN ({values})")


def upgrade() -> None:
    op.add_column(
        "usage_events",
        sa.Column("cache_write_input_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    _replace_check(_NEW)


def downgrade() -> None:
    # Fails if a cache-write price exists; prices are append-only, so remove it by hand first.
    _replace_check(_OLD)
    op.drop_column("usage_events", "cache_write_input_tokens")
