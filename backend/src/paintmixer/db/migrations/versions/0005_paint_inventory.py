"""paint inventory: batch code, body type, reservoir capacity / level, last refill

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-11 08:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('paint', schema=None) as batch_op:
        batch_op.add_column(sa.Column('batch_code', sqlmodel.sql.sqltypes.AutoString(), server_default='', nullable=False))
        batch_op.add_column(sa.Column('body_type', sqlmodel.sql.sqltypes.AutoString(), server_default='', nullable=False))
        batch_op.add_column(sa.Column('capacity_ml', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('level_ml', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('last_refill_at', sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('paint', schema=None) as batch_op:
        batch_op.drop_column('last_refill_at')
        batch_op.drop_column('level_ml')
        batch_op.drop_column('capacity_ml')
        batch_op.drop_column('body_type')
        batch_op.drop_column('batch_code')
