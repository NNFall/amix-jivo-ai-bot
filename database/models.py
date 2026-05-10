from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import JSON, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


class Customer(Base, TimestampMixin):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_client_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Chat(Base, TimestampMixin):
    __tablename__ = "chats"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_chat_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    status: Mapped[str] = mapped_column(String(64), default="active", nullable=False)


class JivoEvent(Base, TimestampMixin):
    __tablename__ = "jivo_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_event_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    external_chat_id: Mapped[str] = mapped_column(String(128), index=True)
    external_client_id: Mapped[str] = mapped_column(String(128), index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(64), default="received", nullable=False)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)


class Message(Base, TimestampMixin):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id"), index=True)
    external_event_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    sender_role: Mapped[str] = mapped_column(String(32), nullable=False)
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class Product(Base, TimestampMixin):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True, index=True)
    article: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_article: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    corporate_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    retail_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    weight: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    volume: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    free_stock: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ProductImport(Base):
    __tablename__ = "product_imports"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source_path: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(64), default="started", nullable=False)
    imported_count: Mapped[int] = mapped_column(default=0, nullable=False)
    updated_count: Mapped[int] = mapped_column(default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(default=0, nullable=False)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Handoff(Base):
    __tablename__ = "handoffs"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_chat_id: Mapped[str] = mapped_column(String(128), index=True)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC),
        nullable=False,
    )


class ProcessingError(Base):
    __tablename__ = "processing_errors"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_event_id: Mapped[str] = mapped_column(String(128), index=True)
    scope: Mapped[str] = mapped_column(String(128), nullable=False)
    error_text: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
