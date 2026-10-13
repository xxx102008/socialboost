import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Platform(str, enum.Enum):
    youtube = "youtube"
    instagram = "instagram"
    facebook = "facebook"
    tiktok = "tiktok"


class ActionType(str, enum.Enum):
    like = "like"
    view = "view"
    follow = "follow"
    subscribe = "subscribe"
    comment = "comment"


class TaskStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"
    retry = "retry"
    cancelled = "cancelled"


class CampaignStatus(str, enum.Enum):
    draft = "draft"
    running = "running"
    paused = "paused"
    completed = "completed"
    cancelled = "cancelled"
    failed = "failed"


class AccountStatus(str, enum.Enum):
    new = "new"
    verifying = "verifying"
    active = "active"
    needs_phone = "needs_phone"
    banned = "banned"
    error = "error"


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    platform: Mapped[Platform] = mapped_column(SAEnum(Platform), index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    email_password: Mapped[str | None] = mapped_column(Text)
    username: Mapped[str | None] = mapped_column(String(255))
    password: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(64))
    proxy: Mapped[str | None] = mapped_column(String(255))
    storage_state: Mapped[str | None] = mapped_column(Text)
    status: Mapped[AccountStatus] = mapped_column(
        SAEnum(AccountStatus), default=AccountStatus.new, index=True
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tasks: Mapped[list["Task"]] = relationship(back_populates="account")


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    platform: Mapped[Platform] = mapped_column(SAEnum(Platform), index=True)
    target_url: Mapped[str] = mapped_column(Text)
    action_type: Mapped[ActionType] = mapped_column(SAEnum(ActionType))
    target_quantity: Mapped[int] = mapped_column(Integer)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[CampaignStatus] = mapped_column(
        SAEnum(CampaignStatus), default=CampaignStatus.draft, index=True
    )
    comment_text: Mapped[str | None] = mapped_column(Text)
    auto_create_accounts: Mapped[bool] = mapped_column(default=True)
    unlimited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    tasks: Mapped[list["Task"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    campaign_id: Mapped[str] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[str | None] = mapped_column(
        ForeignKey("accounts.id"), nullable=True, index=True
    )
    action_type: Mapped[ActionType] = mapped_column(SAEnum(ActionType))
    target_url: Mapped[str] = mapped_column(Text)
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus), default=TaskStatus.pending, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    campaign: Mapped[Campaign] = relationship(back_populates="tasks")
    account: Mapped[Account | None] = relationship(back_populates="tasks")
