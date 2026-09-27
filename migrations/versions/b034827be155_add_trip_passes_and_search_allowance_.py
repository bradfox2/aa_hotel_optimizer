"""Add trip passes and attribute searches to an allowance.

Revision ID: b034827be155
Revises: 9831ce1317d3
"""

import sqlalchemy as sa
from alembic import op

revision = "b034827be155"
down_revision = "9831ce1317d3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "trip_passes",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("checkout_session_id", sa.String(150), unique=True, nullable=False),
        sa.Column("checkout_expires_at", sa.DateTime(), nullable=False),
        sa.Column("payment_intent", sa.String(150), unique=True),
        sa.Column("price_id", sa.String(150), nullable=False),
        sa.Column("search_limit", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("paid_at", sa.DateTime()),
    )
    op.create_index("ix_trip_passes_user_id", "trip_passes", ["user_id"])
    with op.batch_alter_table("searches") as batch:
        batch.add_column(
            sa.Column("allowance", sa.String(20), nullable=False, server_default="free")
        )
        batch.add_column(sa.Column("trip_pass_id", sa.String(32)))
        batch.create_index("ix_searches_trip_pass_id", ["trip_pass_id"])
        batch.create_foreign_key(
            "fk_searches_trip_pass", "trip_passes", ["trip_pass_id"], ["id"], ondelete="SET NULL"
        )
    with op.batch_alter_table("searches") as batch:
        batch.alter_column("allowance", server_default=None)


def downgrade():
    with op.batch_alter_table("searches") as batch:
        batch.drop_constraint("fk_searches_trip_pass", type_="foreignkey")
        batch.drop_index("ix_searches_trip_pass_id")
        batch.drop_column("trip_pass_id")
        batch.drop_column("allowance")
    op.drop_index("ix_trip_passes_user_id", table_name="trip_passes")
    op.drop_table("trip_passes")
