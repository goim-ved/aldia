from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_id"), "users", ["id"], unique=False)
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "webhook_targets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("target_url", sa.String(length=500), nullable=False),
        sa.Column("secret_token", sa.String(length=255), nullable=False),
        sa.Column("subscribed_events", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_webhook_targets_id"), "webhook_targets", ["id"], unique=False)
    op.create_index(op.f("ix_webhook_targets_user_id"), "webhook_targets", ["user_id"], unique=False)
    op.create_index(op.f("ix_webhook_targets_is_active"), "webhook_targets", ["is_active"], unique=False)

    op.create_table(
        "webhook_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("webhook_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("response_status_code", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("execution_duration_ms", sa.Float(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["webhook_id"], ["webhook_targets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_webhook_logs_id"), "webhook_logs", ["id"], unique=False)
    op.create_index(op.f("ix_webhook_logs_webhook_id"), "webhook_logs", ["webhook_id"], unique=False)
    op.create_index(op.f("ix_webhook_logs_event_type"), "webhook_logs", ["event_type"], unique=False)
    op.create_index(op.f("ix_webhook_logs_status"), "webhook_logs", ["status"], unique=False)
    op.create_index(op.f("ix_webhook_logs_created_at"), "webhook_logs", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_webhook_logs_created_at"), table_name="webhook_logs")
    op.drop_index(op.f("ix_webhook_logs_status"), table_name="webhook_logs")
    op.drop_index(op.f("ix_webhook_logs_event_type"), table_name="webhook_logs")
    op.drop_index(op.f("ix_webhook_logs_webhook_id"), table_name="webhook_logs")
    op.drop_index(op.f("ix_webhook_logs_id"), table_name="webhook_logs")
    op.drop_table("webhook_logs")

    op.drop_index(op.f("ix_webhook_targets_is_active"), table_name="webhook_targets")
    op.drop_index(op.f("ix_webhook_targets_user_id"), table_name="webhook_targets")
    op.drop_index(op.f("ix_webhook_targets_id"), table_name="webhook_targets")
    op.drop_table("webhook_targets")

    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_index(op.f("ix_users_id"), table_name="users")
    op.drop_table("users")
