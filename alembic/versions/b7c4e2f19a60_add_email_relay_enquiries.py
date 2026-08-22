"""add email relay enquiries

Revision ID: b7c4e2f19a60
Revises: c7a1b2d3e4f5
Create Date: 2026-08-22 20:15:00.000000

"""
import secrets
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b7c4e2f19a60"
down_revision: Union[str, None] = "c7a1b2d3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("language_preference", sa.String(length=5), nullable=True))
    op.add_column("users", sa.Column("nationality", sa.String(length=100), nullable=True))
    op.add_column("users", sa.Column("country_of_residence", sa.String(length=100), nullable=True))
    op.add_column("users", sa.Column("has_dual_citizenship", sa.Boolean(), nullable=True))
    op.execute(
        "UPDATE users SET language_preference = locale "
        "WHERE locale IN ('ar', 'de', 'en')"
    )

    op.add_column("oauth_states", sa.Column("next_path", sa.String(length=500), nullable=True))

    op.add_column("conversations", sa.Column("reply_token", sa.String(length=64), nullable=True))
    op.add_column(
        "conversations",
        sa.Column("reply_token_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("status", sa.String(length=20), server_default="sent", nullable=False),
    )
    op.add_column(
        "conversations", sa.Column("first_reply_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "conversations",
        sa.Column("message_count", sa.Integer(), server_default="0", nullable=False),
    )

    bind = op.get_bind()
    conversation_ids = bind.execute(sa.text("SELECT id FROM conversations")).scalars().all()
    for conversation_id in conversation_ids:
        bind.execute(
            sa.text("UPDATE conversations SET reply_token = :token WHERE id = :id"),
            {"token": secrets.token_hex(32), "id": conversation_id},
        )

    op.execute(
        "UPDATE conversations SET reply_token_expires_at = "
        "created_at + interval '365 days'"
    )
    op.alter_column("conversations", "reply_token", nullable=False)
    op.create_index(
        "ix_conversations_reply_token", "conversations", ["reply_token"], unique=True
    )
    op.create_index("ix_conversations_status", "conversations", ["status"], unique=False)
    op.create_check_constraint(
        "ck_conversations_status",
        "conversations",
        "status IN ('sent', 'delivered', 'replied', 'unanswered')",
    )

    op.add_column("messages", sa.Column("direction", sa.String(length=20), nullable=True))
    op.add_column(
        "messages",
        sa.Column("delivery_status", sa.String(length=20), server_default="pending", nullable=False),
    )
    op.add_column("messages", sa.Column("outbound_email_id", sa.String(length=100), nullable=True))
    op.add_column("messages", sa.Column("inbound_message_id", sa.String(length=100), nullable=True))

    op.execute(
        "UPDATE messages AS m SET direction = "
        "CASE WHEN m.sender_id = c.buyer_id THEN 'buyer_to_seller' "
        "ELSE 'seller_to_buyer' END "
        "FROM conversations AS c WHERE c.id = m.conversation_id"
    )
    op.execute(
        "UPDATE messages SET delivery_status = "
        "CASE WHEN direction = 'seller_to_buyer' THEN 'received' ELSE 'sent' END"
    )
    op.alter_column("messages", "direction", nullable=False)
    op.create_index("ix_messages_outbound_email_id", "messages", ["outbound_email_id"], unique=True)
    op.create_index("ix_messages_inbound_message_id", "messages", ["inbound_message_id"], unique=True)
    op.create_check_constraint(
        "ck_messages_direction",
        "messages",
        "direction IN ('buyer_to_seller', 'seller_to_buyer')",
    )
    op.create_check_constraint(
        "ck_messages_delivery_status",
        "messages",
        "delivery_status IN ('pending', 'sent', 'delivered', 'delayed', 'failed', 'received')",
    )

    op.execute(
        "UPDATE conversations AS c SET message_count = counts.total "
        "FROM (SELECT conversation_id, count(*)::int AS total FROM messages "
        "GROUP BY conversation_id) AS counts WHERE counts.conversation_id = c.id"
    )
    op.execute(
        "UPDATE conversations AS c SET first_reply_at = replies.first_reply_at, status = 'replied' "
        "FROM (SELECT conversation_id, min(created_at) AS first_reply_at FROM messages "
        "WHERE direction = 'seller_to_buyer' GROUP BY conversation_id) AS replies "
        "WHERE replies.conversation_id = c.id"
    )

    op.create_table(
        "inbound_email_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("provider_message_id", sa.String(length=100), nullable=False),
        sa.Column("webhook_id", sa.String(length=100), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("processing_status", sa.String(length=30), nullable=False),
        sa.Column("rejection_reason", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_inbound_email_events_provider_message_id",
        "inbound_email_events",
        ["provider_message_id"],
        unique=True,
    )
    op.create_index(
        "ix_inbound_email_events_webhook_id",
        "inbound_email_events",
        ["webhook_id"],
        unique=False,
    )
    op.create_index(
        "ix_inbound_email_events_expires_at",
        "inbound_email_events",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_inbound_email_events_expires_at", table_name="inbound_email_events")
    op.drop_index("ix_inbound_email_events_webhook_id", table_name="inbound_email_events")
    op.drop_index("ix_inbound_email_events_provider_message_id", table_name="inbound_email_events")
    op.drop_table("inbound_email_events")

    op.drop_constraint("ck_messages_delivery_status", "messages", type_="check")
    op.drop_constraint("ck_messages_direction", "messages", type_="check")
    op.drop_index("ix_messages_inbound_message_id", table_name="messages")
    op.drop_index("ix_messages_outbound_email_id", table_name="messages")
    op.drop_column("messages", "inbound_message_id")
    op.drop_column("messages", "outbound_email_id")
    op.drop_column("messages", "delivery_status")
    op.drop_column("messages", "direction")

    op.drop_constraint("ck_conversations_status", "conversations", type_="check")
    op.drop_index("ix_conversations_status", table_name="conversations")
    op.drop_index("ix_conversations_reply_token", table_name="conversations")
    op.drop_column("conversations", "message_count")
    op.drop_column("conversations", "first_reply_at")
    op.drop_column("conversations", "status")
    op.drop_column("conversations", "reply_token_expires_at")
    op.drop_column("conversations", "reply_token")

    op.drop_column("oauth_states", "next_path")
    op.drop_column("users", "has_dual_citizenship")
    op.drop_column("users", "country_of_residence")
    op.drop_column("users", "nationality")
    op.drop_column("users", "language_preference")
