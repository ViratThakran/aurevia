"""Phase 10 (WP-10.3): record how many input tokens a model request read from the cache.

``usage_events.input_tokens`` keeps meaning "all input tokens"; the new column is the part of
them served from the provider's prompt cache. Existing rows get 0. The table keeps its
row-level security policy; no new table.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-16 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "usage_events",
        sa.Column("cached_input_tokens", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("usage_events", "cached_input_tokens")
