"""Add active learning totals and heartbeat cursors; preserve unknown history.

Revision ID: v1zmo_study_time
Revises: e8f9a0b1c2d3
"""
from alembic import op
import sqlalchemy as sa

revision = 'v1zmo_study_time'
down_revision = 'e8f9a0b1c2d3'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    metadata = sa.MetaData()
    # Resolve referenced tables without importing evolving application models.
    for name in ('user', 'course', 'organization', 'activity'):
        sa.Table(name, metadata, autoload_with=bind)
    sa.Table(
        'course_study_time', metadata,
        sa.Column('user_id', sa.Integer, sa.ForeignKey('user.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('course_id', sa.Integer, sa.ForeignKey('course.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('org_id', sa.Integer, sa.ForeignKey('organization.id', ondelete='CASCADE'), nullable=False),
        sa.Column('active_ms', sa.BigInteger, server_default=sa.text('0'), nullable=False),
        sa.Column('partially_tracked', sa.Boolean, server_default=sa.text('false'), nullable=False),
        sa.Column('first_seen_at', sa.DateTime(timezone=True)),
        sa.Column('last_accounted_at', sa.DateTime(timezone=True)),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.Index('ix_course_study_time_org_course', 'org_id', 'course_id'),
    ).create(bind, checkfirst=True)
    sa.Table(
        'course_study_session', metadata,
        sa.Column('session_id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('course_id', sa.Integer, sa.ForeignKey('course.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('org_id', sa.Integer, sa.ForeignKey('organization.id', ondelete='CASCADE'), nullable=False),
        sa.Column('activity_id', sa.Integer, sa.ForeignKey('activity.id', ondelete='CASCADE'), nullable=False),
        sa.Column('last_total_ms', sa.BigInteger, nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    ).create(bind, checkfirst=True)
    # A zero counter with no first_seen_at is unknown, not a zero-time completion.
    op.execute(sa.text('''
        INSERT INTO course_study_time (user_id, course_id, org_id, active_ms, partially_tracked)
        SELECT DISTINCT user_id, course_id, org_id, 0, true FROM trailrun
        ON CONFLICT (user_id, course_id) DO NOTHING
    '''))


def downgrade():
    op.drop_table('course_study_session')
    op.drop_table('course_study_time')
