"""empty message

Revision ID: 1402e0083089
Revises: 301908799267
Create Date: 2025-05-09 16:54:45.110203

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1402e0083089'
down_revision = '301908799267'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('donations', schema=None) as batch_op:
        batch_op.alter_column('program_id',
               existing_type=sa.INTEGER(),
               nullable=True)

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('donations', schema=None) as batch_op:
        batch_op.alter_column('program_id',
               existing_type=sa.INTEGER(),
               nullable=False)

    # ### end Alembic commands ###
