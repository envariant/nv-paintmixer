"""model lines: named series of model versions

Existing models move into a line called "default", with revisions in version order.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-09 06:31:23.233321

"""
from datetime import UTC, datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('model_line',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('slug', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('description', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('last_revision', sa.Integer(), nullable=False),
    sa.Column('created_at', sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('model_line', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_model_line_slug'), ['slug'], unique=True)

    with op.batch_alter_table('fitted_model', schema=None) as batch_op:
        batch_op.add_column(sa.Column('line_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('revision', sa.Integer(), server_default='1', nullable=False))
        batch_op.add_column(sa.Column('label', sqlmodel.sql.sqltypes.AutoString(), server_default='', nullable=False))

    conn = op.get_bind()
    versions = [r[0] for r in conn.execute(sa.text('SELECT version FROM fitted_model ORDER BY version'))]
    if versions:
        conn.execute(
            sa.text("INSERT INTO model_line (slug, name, description, last_revision, created_at) VALUES ('default', 'Default', 'Models created before model lines existed', :n, :t)"),
            {'n': len(versions), 't': datetime.now(UTC).replace(tzinfo=None)},
        )
        line_id = conn.execute(sa.text("SELECT id FROM model_line WHERE slug = 'default'")).scalar_one()
        for rev, version in enumerate(versions, start=1):
            conn.execute(
                sa.text('UPDATE fitted_model SET line_id = :l, revision = :r WHERE version = :v'),
                {'l': line_id, 'r': rev, 'v': version},
            )

    with op.batch_alter_table('fitted_model', schema=None) as batch_op:
        batch_op.alter_column('line_id', existing_type=sa.Integer(), nullable=False)
        batch_op.create_index(batch_op.f('ix_fitted_model_line_id'), ['line_id'], unique=False)
        batch_op.create_unique_constraint('uq_fitted_model_line_rev', ['line_id', 'revision'])
        batch_op.create_foreign_key('fk_fitted_model_line_id', 'model_line', ['line_id'], ['id'])


def downgrade() -> None:
    """Downgrade schema (lines, revisions and labels are lost; versions are kept)."""
    with op.batch_alter_table('fitted_model', schema=None) as batch_op:
        batch_op.drop_constraint('fk_fitted_model_line_id', type_='foreignkey')
        batch_op.drop_constraint('uq_fitted_model_line_rev', type_='unique')
        batch_op.drop_index(batch_op.f('ix_fitted_model_line_id'))
        batch_op.drop_column('label')
        batch_op.drop_column('revision')
        batch_op.drop_column('line_id')

    with op.batch_alter_table('model_line', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_model_line_slug'))

    op.drop_table('model_line')
