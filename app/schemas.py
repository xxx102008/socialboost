from datetime import datetime

from pydantic import BaseModel, Field

from .models import (
    AccountStatus,
    ActionType,
    CampaignStatus,
    Platform,
    TaskStatus,
)


class CampaignCreate(BaseModel):
    platform: Platform | None = None
    url: str
    action: ActionType
    quantity: int = Field(gt=0, le=100000)
    comment_text: str | None = None
    auto_create_accounts: bool = True


class CampaignOut(BaseModel):
    id: str
    platform: Platform
    target_url: str
    action_type: ActionType
    target_quantity: int
    success_count: int
    failed_count: int
    status: CampaignStatus
    created_at: datetime

    class Config:
        from_attributes = True


class TaskOut(BaseModel):
    id: str
    status: TaskStatus
    action_type: ActionType
    attempts: int
    error: str | None
    account_id: str | None

    class Config:
        from_attributes = True


class AccountOut(BaseModel):
    id: str
    platform: Platform
    email: str
    username: str | None
    status: AccountStatus
    created_at: datetime

    class Config:
        from_attributes = True


class DashboardStats(BaseModel):
    total_campaigns: int
    active_campaigns: int
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    pending_tasks: int
    total_accounts: int
    active_accounts: int
