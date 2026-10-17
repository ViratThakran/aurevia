"""Phase 10 (WP-10.3): a separate price for model input read from the prompt cache.

Providers charge far less for cache-read input than for ordinary input, so the ``prices``
resource check gains ``llm_cached_input_tokens``. Only the check constraint changes; no data
is touched and existing prices keep their meaning.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-17 09:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = (
    "'llm_input_tokens', 'llm_output_tokens', 'stt_seconds', 'tts_characters', 'telephony_seconds'"
)
_NEW = (
    "'llm_input_tokens', 'llm_cached_input_tokens', 'llm_output_tokens', 'stt_seconds', "
    "'tts_characters', 'telephony_seconds'"
)


def _replace_check(values: str) -> None:
    op.drop_constraint(op.f("ck_prices_resource"), "prices", type_="check")
    op.create_check_constraint(op.f("ck_prices_resource"), "prices", f"resource IN ({values})")


def upgrade() -> None:
    _replace_check(_NEW)


def downgrade() -> None:
    # Fails if a cached-input price exists; prices are append-only, so remove it by hand first.
    _replace_check(_OLD)
