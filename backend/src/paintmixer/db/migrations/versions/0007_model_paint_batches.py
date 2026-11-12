"""model paint batches: each paint's batch code when the model was made

Models made before this have an empty map, so their paints are never reported stale.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-11 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('fitted_model', schema=None) as batch_op:
        batch_op.add_column(sa.Column('paint_batches', sa.JSON(), server_default=sa.text("'{}'"), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('fitted_model', schema=None) as batch_op:
        batch_op.drop_column('paint_batches')
