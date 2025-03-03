"""Add face_id column to users table

Revision ID: add_faceid_column
"""

from alembic import op
import sqlalchemy as sa

def upgrade():
    op.add_column('users', sa.Column('has_face_id', sa.Boolean(), nullable=False, server_default='0'))
    
    # Create the login_events table if it doesn't exist
    op.create_table('login_event',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('login_time', sa.DateTime(), nullable=False),
        sa.Column('method', sa.String(length=20), nullable=False),
        sa.Column('success', sa.Boolean(), nullable=False, default=True),
        sa.Column('failure_reason', sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

def downgrade():
    op.drop_column('users', 'has_face_id')
    op.drop_table('login_event') 