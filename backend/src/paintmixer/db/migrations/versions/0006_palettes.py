"""palettes: named, ordered sets of library colours

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-11 08:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('palette',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('color_ids', sa.JSON(), nullable=True),
    sa.Column('created_at', sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
    sa.Column('updated_at', sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('palette', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_palette_name'), ['name'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('palette', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_palette_name'))
    op.drop_table('palette')
