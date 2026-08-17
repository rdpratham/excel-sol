"""Add cell_styles JSONB column to sheets — supports per-cell formatting
(bold/italic/font color/fill color/alignment) for the Excel-style ribbon.

Revision ID: 002
Revises: 001
Create Date: 2026-08-17 00:00:00
"""

from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE sheets ADD COLUMN cell_styles JSONB NOT NULL DEFAULT '{}'::jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE sheets DROP COLUMN cell_styles")
