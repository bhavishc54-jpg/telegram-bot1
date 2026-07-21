"""Compatibility marker for the old payment bot revision.

The project purpose changed after this revision. New installs keep this marker so
databases that already reached 20260715_01 can migrate forward cleanly without
recreating removed payment models.
"""

from __future__ import annotations

revision = "20260715_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
