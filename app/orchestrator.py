from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Account, AccountStatus, Campaign, CampaignStatus, Task, TaskStatus
from .urls import detect_platform, normalize


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _available_accounts(db: Session, platform) -> list[Account]:
    stmt = (
        select(Account)
        .where(Account.platform == platform, Account.status == AccountStatus.active)
        .order_by(Account.last_used_at.asc().nullsfirst())
    )
    return list(db.scalars(stmt))


def create_campaign(db: Session, payload) -> Campaign:
    platform = payload.platform or detect_platform(payload.url)
    if platform is None:
        raise ValueError("לא הצלחתי לזהות את הפלטפורמה מהקישור")

    initial = payload.quantity if payload.quantity > 0 else 1
    campaign = Campaign(
        platform=platform,
        target_url=normalize(payload.url),
        action_type=payload.action,
        target_quantity=payload.quantity,
        comment_text=payload.comment_text,
        auto_create_accounts=True,
        unlimited=payload.unlimited,
        status=CampaignStatus.running,
    )
    db.add(campaign)
    db.flush()

    pool = _available_accounts(db, platform)
    for i in range(initial):
        account_id = pool[i].id if i < len(pool) else None
        key = f"{campaign.id}:{account_id or 'new-' + str(i)}:{payload.action.value}"
        db.add(
            Task(
                campaign_id=campaign.id,
                account_id=account_id,
                action_type=payload.action,
                target_url=campaign.target_url,
                idempotency_key=key,
            )
        )

    db.commit()
    db.refresh(campaign)
    return campaign


def recompute_campaign(db: Session, campaign: Campaign) -> None:
    counts = dict(
        db.execute(
            select(Task.status, func.count())
            .where(Task.campaign_id == campaign.id)
            .group_by(Task.status)
        ).all()
    )
    success = counts.get(TaskStatus.success, 0)
    failed = counts.get(TaskStatus.failed, 0)
    pending = sum(
        counts.get(s, 0)
        for s in (TaskStatus.pending, TaskStatus.retry, TaskStatus.running)
    )

    campaign.success_count = success
    campaign.failed_count = failed

    if campaign.status not in (CampaignStatus.paused, CampaignStatus.cancelled):
        if campaign.unlimited or pending > 0:
            campaign.status = CampaignStatus.running
        elif failed > 0 and success == 0:
            campaign.status = CampaignStatus.failed
        else:
            campaign.status = CampaignStatus.completed

    campaign.updated_at = _now()
    db.commit()
