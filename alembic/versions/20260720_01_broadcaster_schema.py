"""Create source-channel broadcaster schema."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    inspect,
    text,
)

from alembic import op

revision = "20260720_01"
down_revision = "20260715_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "subscribers" not in tables:
        op.create_table(
            "subscribers",
            Column("user_id", BigInteger(), primary_key=True, autoincrement=False),
            Column("chat_id", BigInteger(), nullable=False),
            Column("username", String(64), nullable=True),
            Column("first_name", String(255), nullable=False, server_default=""),
            Column("last_name", String(255), nullable=True),
            Column(
                "started_at",
                DateTime(timezone=True),
                nullable=False,
                server_default=text("CURRENT_TIMESTAMP"),
            ),
            Column(
                "last_seen_at",
                DateTime(timezone=True),
                nullable=False,
                server_default=text("CURRENT_TIMESTAMP"),
            ),
            Column("is_active", Boolean(), nullable=False, server_default=text("1")),
            Column("blocked_at", DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_subscribers_chat_id", "subscribers", ["chat_id"], unique=True)
        op.create_index("ix_subscribers_is_active", "subscribers", ["is_active"], unique=False)

    if "bot_settings" not in tables:
        op.create_table(
            "bot_settings",
            Column("key", String(64), primary_key=True),
            Column("value", Text(), nullable=False),
            Column(
                "updated_at",
                DateTime(timezone=True),
                nullable=False,
                server_default=text("CURRENT_TIMESTAMP"),
            ),
        )

    if "source_posts" not in tables:
        op.create_table(
            "source_posts",
            Column("id", Integer(), primary_key=True),
            Column("source_chat_id", BigInteger(), nullable=False),
            Column("source_message_id", Integer(), nullable=False),
            Column("original_text_or_caption", Text(), nullable=False, server_default=""),
            Column("cleaned_text", Text(), nullable=False, server_default=""),
            Column(
                "received_at",
                DateTime(timezone=True),
                nullable=False,
                server_default=text("CURRENT_TIMESTAMP"),
            ),
            Column(
                "source_message_date",
                DateTime(timezone=True),
                nullable=False,
                server_default=text("CURRENT_TIMESTAMP"),
            ),
            Column("due_at", DateTime(timezone=True), nullable=False),
            Column(
                "status",
                Enum(
                    "pending",
                    "processing",
                    "completed",
                    "failed",
                    "skipped",
                    name="sourcepoststatus",
                ),
                nullable=False,
                server_default="pending",
            ),
            Column("attempt_count", Integer(), nullable=False, server_default=text("0")),
            Column("last_error", Text(), nullable=True),
            Column("completed_at", DateTime(timezone=True), nullable=True),
            UniqueConstraint("source_chat_id", "source_message_id", name="uq_source_chat_message"),
        )
        op.create_index(
            "ix_source_posts_source_chat_id", "source_posts", ["source_chat_id"], unique=False
        )
        op.create_index(
            "ix_source_posts_source_message_id", "source_posts", ["source_message_id"], unique=False
        )
        op.create_index("ix_source_posts_due_at", "source_posts", ["due_at"], unique=False)
        op.create_index("ix_source_posts_status", "source_posts", ["status"], unique=False)

    if "source_links" not in tables:
        op.create_table(
            "source_links",
            Column("id", Integer(), primary_key=True),
            Column(
                "source_post_id",
                Integer(),
                ForeignKey("source_posts.id", ondelete="CASCADE"),
                nullable=False,
            ),
            Column("position", Integer(), nullable=False),
            Column("original_url", Text(), nullable=False),
            Column("converted_url", Text(), nullable=True),
            Column(
                "conversion_status",
                Enum("pending", "converted", "failed", name="linkstatus"),
                nullable=False,
                server_default="pending",
            ),
            Column("last_error", Text(), nullable=True),
            UniqueConstraint("source_post_id", "position", name="uq_source_link_position"),
        )
        op.create_index(
            "ix_source_links_source_post_id", "source_links", ["source_post_id"], unique=False
        )
        op.create_index(
            "ix_source_links_conversion_status", "source_links", ["conversion_status"], unique=False
        )

    if "conversion_cache" not in tables:
        op.create_table(
            "conversion_cache",
            Column("original_url", Text(), primary_key=True),
            Column("converted_url", Text(), nullable=False),
            Column(
                "created_at",
                DateTime(timezone=True),
                nullable=False,
                server_default=text("CURRENT_TIMESTAMP"),
            ),
        )

    if "broadcast_jobs" not in tables:
        op.create_table(
            "broadcast_jobs",
            Column("id", Integer(), primary_key=True),
            Column(
                "source_post_id",
                Integer(),
                ForeignKey("source_posts.id", ondelete="CASCADE"),
                nullable=False,
            ),
            Column(
                "status",
                Enum("pending", "sending", "completed", "failed", "paused", name="broadcaststatus"),
                nullable=False,
                server_default="pending",
            ),
            Column("started_at", DateTime(timezone=True), nullable=True),
            Column("finished_at", DateTime(timezone=True), nullable=True),
            Column("sent_count", Integer(), nullable=False, server_default=text("0")),
            Column("failed_count", Integer(), nullable=False, server_default=text("0")),
            Column("blocked_count", Integer(), nullable=False, server_default=text("0")),
            Column("last_error", Text(), nullable=True),
        )
        op.create_index(
            "ix_broadcast_jobs_source_post_id", "broadcast_jobs", ["source_post_id"], unique=True
        )
        op.create_index("ix_broadcast_jobs_status", "broadcast_jobs", ["status"], unique=False)

    if "broadcast_deliveries" not in tables:
        op.create_table(
            "broadcast_deliveries",
            Column("id", Integer(), primary_key=True),
            Column(
                "broadcast_job_id",
                Integer(),
                ForeignKey("broadcast_jobs.id", ondelete="CASCADE"),
                nullable=False,
            ),
            Column(
                "subscriber_id", BigInteger(), ForeignKey("subscribers.user_id"), nullable=False
            ),
            Column(
                "status",
                Enum("pending", "sent", "failed", "blocked", name="deliverystatus"),
                nullable=False,
                server_default="pending",
            ),
            Column("attempt_count", Integer(), nullable=False, server_default=text("0")),
            Column("sent_at", DateTime(timezone=True), nullable=True),
            Column("last_error", Text(), nullable=True),
            UniqueConstraint("broadcast_job_id", "subscriber_id", name="uq_job_subscriber"),
        )
        op.create_index(
            "ix_broadcast_deliveries_broadcast_job_id",
            "broadcast_deliveries",
            ["broadcast_job_id"],
            unique=False,
        )
        op.create_index(
            "ix_broadcast_deliveries_subscriber_id",
            "broadcast_deliveries",
            ["subscriber_id"],
            unique=False,
        )
        op.create_index(
            "ix_broadcast_deliveries_status", "broadcast_deliveries", ["status"], unique=False
        )

    _migrate_legacy_users(bind, tables)


def downgrade() -> None:
    for table in (
        "broadcast_deliveries",
        "broadcast_jobs",
        "conversion_cache",
        "source_links",
        "source_posts",
        "subscribers",
    ):
        op.drop_table(table)


def _migrate_legacy_users(bind, tables: set[str]) -> None:
    if "users" not in tables or "subscribers" not in set(inspect(bind).get_table_names()):
        return
    users = inspect(bind).get_columns("users")
    names = {column["name"] for column in users}
    if not {"telegram_id", "username", "first_name", "joined_at", "last_active_at"}.issubset(names):
        return

    rows = bind.execute(
        text(
            """
            SELECT telegram_id, username, first_name, joined_at, last_active_at, is_banned
            FROM users
            """
        )
    ).mappings()
    existing = set(bind.execute(text("SELECT user_id FROM subscribers")).scalars())
    for row in rows:
        if row["telegram_id"] in existing:
            continue
        is_banned = bool(row["is_banned"]) if "is_banned" in row else False
        bind.execute(
            text(
                """
                INSERT INTO subscribers
                (user_id, chat_id, username, first_name, last_name,
                 started_at, last_seen_at, is_active)
                VALUES
                (:user_id, :chat_id, :username, :first_name, NULL,
                 :started_at, :last_seen_at, :is_active)
                """
            ),
            {
                "user_id": row["telegram_id"],
                "chat_id": row["telegram_id"],
                "username": row["username"],
                "first_name": row["first_name"] or "",
                "started_at": row["joined_at"],
                "last_seen_at": row["last_active_at"],
                "is_active": not is_banned,
            },
        )
