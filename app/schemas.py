from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

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
    quantity: int = Field(ge=0, le=100000)
    comment_text: str | None = None
    unlimited: bool = False


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    platform: Platform
    target_url: str
    action_type: ActionType
    target_quantity: int
    success_count: int
    failed_count: int
    status: CampaignStatus
    unlimited: bool
    created_at: datetime


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: TaskStatus
    action_type: ActionType
    attempts: int
    error: str | None
    account_id: str | None


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    platform: Platform
    email: str
    username: str | None
    status: AccountStatus
    last_error: str | None
    created_at: datetime


class DashboardStats(BaseModel):
    total_campaigns: int
    active_campaigns: int
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    pending_tasks: int
    total_accounts: int
    active_accounts: int
