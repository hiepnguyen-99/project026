"""create access_requests table

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-08
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    access_status = sa.Enum("pending", "approved", "denied", name="access_status")
    access_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "access_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("requester_code", sa.String(length=50), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "denied", name="access_status", create_type=False),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
    )
    op.create_index("ix_access_requests_document_id", "access_requests", ["document_id"])
    op.create_index("ix_access_requests_requester_code", "access_requests", ["requester_code"])


def downgrade() -> None:
    op.drop_index("ix_access_requests_requester_code", table_name="access_requests")
    op.drop_index("ix_access_requests_document_id", table_name="access_requests")
    op.drop_table("access_requests")
    sa.Enum(name="access_status").drop(op.get_bind(), checkfirst=True)
