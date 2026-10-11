import json
import threading
import traceback
from datetime import datetime, timezone

from sqlalchemy import select

from .config import get_settings
from .db import SessionLocal
from .mail import create_mailbox
from .models import (
    Account,
    AccountStatus,
    Campaign,
    CampaignStatus,
    Task,
    TaskStatus,
)
from .platforms import get_platform
from .security import encrypt
from .orchestrator import recompute_campaign

settings = get_settings()


def _now():
    return datetime.now(timezone.utc)


class Worker(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name="socialboost-worker")
        self._stop = threading.Event()
        self._browser = None
        self._pw = None

    def stop(self):
        self._stop.set()

    # ---------- browser ----------
    def _browser_instance(self):
        if self._browser is None:
            from playwright.sync_api import sync_playwright

            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(
                headless=settings.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
        return self._browser

    def _context(self, account=None):
        kwargs = {
            "viewport": {"width": 1366, "height": 900},
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "locale": "en-US",
        }
        if account and account.storage_state:
            try:
                kwargs["storage_state"] = json.loads(account.storage_state)
            except Exception:
                pass
        ctx = self._browser_instance().new_context(**kwargs)
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )
        return ctx

    # ---------- loop ----------
    def run(self):
        self._requeue_stale()
        while not self._stop.is_set():
            try:
                worked = self._tick()
            except Exception:
                traceback.print_exc()
                worked = False
            if not worked:
                self._stop.wait(settings.worker_poll_seconds)

    def _requeue_stale(self):
        db = SessionLocal()
        try:
            for t in db.scalars(select(Task).where(Task.status == TaskStatus.running)):
                t.status = TaskStatus.pending
            db.commit()
        finally:
            db.close()

    def _tick(self) -> bool:
        db = SessionLocal()
        try:
            task = db.scalar(
                select(Task)
                .join(Campaign)
                .where(
                    Task.status.in_([TaskStatus.pending, TaskStatus.retry]),
                    Campaign.status == CampaignStatus.running,
                )
                .order_by(Task.created_at)
                .limit(1)
            )
            if task is None:
                return False
            self._process(db, task)
            return True
        finally:
            db.close()

    def _process(self, db, task: Task):
        campaign = db.get(Campaign, task.campaign_id)

        task.status = TaskStatus.running
        task.started_at = _now()
        task.attempts += 1
        db.commit()

        account = db.get(Account, task.account_id) if task.account_id else None
        context = None
        try:
            if account is None:
                account = self._create_account(db, campaign.platform)
                task.account_id = account.id
                db.commit()

            context = self._context(account)
            result = get_platform(campaign.platform).perform(
                context, task.action_type, task.target_url, account, campaign.comment_text
            )

            account.storage_state = encrypt(json.dumps(context.storage_state()))
            account.last_used_at = _now()
            if account.status != AccountStatus.active:
                account.status = AccountStatus.active

            task.status = TaskStatus.success
            task.result = result
            task.error = None
            task.finished_at = _now()
            db.commit()
        except Exception as exc:
            task.error = str(exc)[:2000]
            task.status = (
                TaskStatus.failed if task.attempts >= task.max_attempts else TaskStatus.retry
            )
            task.finished_at = _now() if task.status == TaskStatus.failed else None
            db.commit()
        finally:
            if context:
                try:
                    context.close()
                except Exception:
                    pass
            recompute_campaign(db, campaign)

    def _create_account(self, db, platform) -> Account:
        mailbox = create_mailbox()
        local = mailbox.address.split("@")[0][:8]
        account = Account(
            platform=platform,
            email=mailbox.address,
            email_password=encrypt(mailbox.password),
            password=encrypt(f"Sb!{local}9"),
            status=AccountStatus.verifying,
        )
        db.add(account)
        db.commit()
        db.refresh(account)

        context = self._context(account)
        try:
            get_platform(platform).create_account(context, account, mailbox)
            account.storage_state = encrypt(json.dumps(context.storage_state()))
            account.status = AccountStatus.active
            account.last_error = None
        except Exception as exc:
            account.last_error = str(exc)[:1000]
            account.status = AccountStatus.error
        finally:
            context.close()
            db.commit()
            db.refresh(account)
        return account
