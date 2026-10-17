"""Phase 11 (WP-11.4, built early; off by default): prospect mood and the voice style used.

``calls.prospect_mood`` is the latest mood the bookkeeping pass recorded (warm, neutral,
rushed, annoyed, skeptical, confused), from the prospect's words only. ``turn_metrics
.voice_style`` is the voice setting the worker used for an agent turn, e.g. "slow/Calm".
Both are nullable and stay empty while the feature is off. Additive only: the tables keep
their tenant_id, indexes and forced row-level security; no new table.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-17 15:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MOODS = "'warm', 'neutral', 'rushed', 'annoyed', 'skeptical', 'confused'"


def upgrade() -> None:
    op.add_column("calls", sa.Column("prospect_mood", sa.String(length=20), nullable=True))
    op.create_check_constraint(
        op.f("ck_calls_prospect_mood"),
        "calls",
        f"prospect_mood IS NULL OR prospect_mood IN ({_MOODS})",
    )
    op.add_column("turn_metrics", sa.Column("voice_style", sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column("turn_metrics", "voice_style")
    op.drop_constraint(op.f("ck_calls_prospect_mood"), "calls", type_="check")
    op.drop_column("calls", "prospect_mood")
