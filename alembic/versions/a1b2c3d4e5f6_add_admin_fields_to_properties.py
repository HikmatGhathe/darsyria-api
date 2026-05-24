"""add admin fields to properties

Revision ID: a1b2c3d4e5f6
Revises: d062f68588b9
Create Date: 2026-05-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'd062f68588b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('properties', sa.Column('rejection_reason', sa.Text(), nullable=True))
    op.add_column('properties', sa.Column('flagged_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('properties', sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('properties', 'reviewed_at')
    op.drop_column('properties', 'flagged_at')
    op.drop_column('properties', 'rejection_reason')
