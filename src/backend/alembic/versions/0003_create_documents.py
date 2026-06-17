"""create documents and versions tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-08
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    visibility = sa.Enum("public", "private", name="visibility")
    doc_status = sa.Enum("pending", "processing", "ready", "duplicate", "failed", name="doc_status")
    visibility.create(op.get_bind(), checkfirst=True)
    doc_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_code", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("doc_type", sa.String(length=100), nullable=True),
        sa.Column("topic", sa.String(length=255), nullable=True),
        sa.Column("subtopic", sa.String(length=255), nullable=True),
        sa.Column("author", sa.String(length=255), nullable=True),
        sa.Column(
            "visibility",
            sa.Enum("public", "private", name="visibility", create_type=False),
            server_default="private",
            nullable=False,
        ),
        sa.Column("folder_id", sa.Uuid(), nullable=True),
        sa.Column("storage_uri", sa.String(length=1000), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "processing", "ready", "duplicate", "failed",
                name="doc_status", create_type=False,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("current_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_documents_owner_code", "documents", ["owner_code"])
    op.create_index("ix_documents_content_hash", "documents", ["content_hash"])

    op.create_table(
        "versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("storage_uri", sa.String(length=1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
    )
    op.create_index("ix_versions_document_id", "versions", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_versions_document_id", table_name="versions")
    op.drop_table("versions")
    op.drop_index("ix_documents_content_hash", table_name="documents")
    op.drop_index("ix_documents_owner_code", table_name="documents")
    op.drop_table("documents")
    sa.Enum(name="doc_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="visibility").drop(op.get_bind(), checkfirst=True)
