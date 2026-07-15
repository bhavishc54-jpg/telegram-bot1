"""Add credits, products, payments, events, and pending requests."""

from __future__ import annotations

from sqlalchemy import Column, Integer, inspect, text

from alembic import op
from app.models import Base, Payment, PendingRequest, ProcessedPaymentEvent, Product

revision = "20260715_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "users" not in tables:
        Base.metadata.create_all(bind)
        return

    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "credits" not in user_columns:
        op.add_column(
            "users",
            Column("credits", Integer(), nullable=False, server_default=text("0")),
        )

    Product.__table__.create(bind, checkfirst=True)
    Payment.__table__.create(bind, checkfirst=True)
    ProcessedPaymentEvent.__table__.create(bind, checkfirst=True)
    PendingRequest.__table__.create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    for table_name in (
        "pending_requests",
        "processed_payment_events",
        "payments",
        "products",
    ):
        if table_name in tables:
            op.drop_table(table_name)
    if "users" in tables:
        columns = {column["name"] for column in inspect(bind).get_columns("users")}
        if "credits" in columns:
            with op.batch_alter_table("users") as batch_op:
                batch_op.drop_column("credits")
