"""job run state: step, progress, paused and running while the machine runs a job

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-12 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '0009'
down_revision: Union[str, Sequence[str], None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('job', schema=None) as batch_op:
        batch_op.add_column(sa.Column('step', sqlmodel.sql.sqltypes.AutoString(), server_default='', nullable=False))
        batch_op.add_column(sa.Column('progress', sa.Float(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('paused', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column('running', sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('job', schema=None) as batch_op:
        batch_op.drop_column('running')
        batch_op.drop_column('paused')
        batch_op.drop_column('progress')
        batch_op.drop_column('step')
