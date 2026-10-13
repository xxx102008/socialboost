import json
import threading
import traceback
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select

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
from .orchestrator import _available_accounts, recompute_campaign
from .platforms import get_platform
from .security import encrypt

settings = get_settings()
_claim_lock = threading.Lock()

ARG_SETS = [
    [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--single-process",
        "--no-zygote",
        "--js-flags=--max-old-space-size=160",
    ],
    ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
]


def log(*parts):
    print("[SB]", *parts, flush=True)


def launch_browser():
    """Try the low-memory launch flags first, then retry with standard flags."""
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    last_error = None
    for args in ARG_SETS:
        try:
            browser = playwright.chromium.launch(headless=settings.headless, args=args)
            log("browser launched with", args[:3])
            return playwright, browser
        except Exception as exc:
            last_error = exc
            log("browser launch failed:", type(exc).__name__, str(exc))
    playwright.stop()
    raise RuntimeError(f"לא הצלחתי להפעיל דפדפן: {last_error}") from last_error


def _now():
    return datetime.now(timezone.utc)


class Worker(threading.Thread):
    def __init__(self, index: int = 0):
        super().__init__(daemon=True, name=f"sb-worker-{index}")
        self.index = index
        self._stop_event = threading.Event()
        self._browser = None
        self._pw = None

    def stop(self):
        self._stop_event.set()

    def _browser_instance(self):
        if self._browser is None:
            self._pw, self._browser = launch_browser()
        return self._browser

    def _context(self, account=None):
        kwargs = {
            "viewport": {"width": 1280, "height": 800},
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "locale": "en-US",
        }
        if account and account.storage_state:
            try:
                kwargs["storage_state"] = json.loads(account.storage_state)
            except (TypeError, ValueError):
                pass

        context = self._browser_instance().new_context(**kwargs)
        context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )
        if settings.block_heavy_assets:
            context.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in ("image", "media", "font")
                else route.continue_(),
            )
        return context

    def run(self):
        log(f"worker-{self.index} started")
        try:
            while not self._stop_event.is_set():
                try:
                    worked = self._tick()
                except Exception:
                    traceback.print_exc()
                    worked = False
                if not worked:
                    self._stop_event.wait(settings.worker_poll_seconds)
        finally:
            if self._browser is not None:
                try:
                    self._browser.close()
                except Exception:
                    pass
            if self._pw is not None:
                try:
                    self._pw.stop()
                except Exception:
                    pass
            log(f"worker-{self.index} stopped")

    def _tick(self) -> bool:
        """Claim a queued task, or enqueue work for an unlimited campaign."""
        with _claim_lock:
            db = SessionLocal()
            try:
                concurrency = max(1, settings.worker_concurrency)
                active_count = db.scalar(
                    select(func.count()).select_from(Task).where(Task.status == TaskStatus.running)
                ) or 0
                if active_count >= concurrency:
                    return False

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
                    campaign = db.scalar(
                        select(Campaign)
                        .where(
                            Campaign.status == CampaignStatus.running,
                            Campaign.unlimited.is_(True),
                        )
                        .order_by(Campaign.created_at)
                        .limit(1)
                    )
                    if campaign is None:
                        return False

                    ordinal = db.scalar(
                        select(func.count()).select_from(Task).where(
                            Task.campaign_id == campaign.id
                        )
                    ) or 0
                    accounts = _available_accounts(db, campaign.platform)
                    account_id = accounts[ordinal % len(accounts)].id if accounts else None
                    task = Task(
                        campaign_id=campaign.id,
                        account_id=account_id,
                        action_type=campaign.action_type,
                        target_url=campaign.target_url,
                        idempotency_key=f"unlimited:{campaign.id}:{ordinal}",
                    )
                    db.add(task)
                    db.flush()

                task.status = TaskStatus.running
                task.started_at = _now()
                task.attempts += 1
                db.commit()
                task_id = task.id
            finally:
                db.close()

        log(f"worker-{self.index} claimed task {task_id[:8]}")
        db = SessionLocal()
        try:
            task = db.get(Task, task_id)
            if task is None:
                return True
            self._process(db, task)
            return True
        finally:
            db.close()

    def _process(self, db, task: Task):
        campaign = db.get(Campaign, task.campaign_id)
        if campaign is None:
            task.status = TaskStatus.failed
            task.error = "הקמפיין של המשימה לא נמצא"
            task.finished_at = _now()
            db.commit()
            log(f"FAIL task {task.id[:8]} :: campaign not found")
            return

        account = db.get(Account, task.account_id) if task.account_id else None
        context = None
        task_id = task.id
        campaign_id = campaign.id
        try:
            if account is None:
                log(f"creating account for {campaign.platform} ...")
                account = self._create_account(db, campaign.platform)
                task.account_id = account.id
                db.commit()
                log(f"account {account.email} status={account.status} err={account.last_error}")
                if account.status != AccountStatus.active:
                    raise RuntimeError(f"יצירת חשבון נכשלה: {account.last_error}")

            log(f"performing {task.action_type} on {task.target_url[:60]}")
            context = self._context(account)
            result = get_platform(campaign.platform).perform(
                context, task.action_type, task.target_url, account, campaign.comment_text
            )

            account.storage_state = encrypt(json.dumps(context.storage_state()))
            account.last_used_at = _now()
            account.status = AccountStatus.active
            account.last_error = None

            task.status = TaskStatus.success
            task.result = result
            task.error = None
            task.finished_at = _now()
            db.commit()
            log(f"SUCCESS task {task.id[:8]} -> {result}")
        except Exception as exc:
            db.rollback()
            task = db.get(Task, task_id)
            if task is not None:
                task.error = str(exc)[:3000]
                task.status = (
                    TaskStatus.failed if task.attempts >= task.max_attempts else TaskStatus.retry
                )
                task.finished_at = _now() if task.status == TaskStatus.failed else None
                db.commit()
                log(f"FAIL task {task.id[:8]} :: {task.error}")
        finally:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass
            campaign = db.get(Campaign, campaign_id)
            if campaign is not None:
                recompute_campaign(db, campaign)
                self._refill(db, campaign)

    def _refill(self, db, campaign: Campaign):
        """Keep a small, bounded task buffer for unlimited campaigns."""
        if not campaign.unlimited or campaign.status != CampaignStatus.running:
            return

        with _claim_lock:
            active = db.scalar(
                select(func.count())
                .select_from(Task)
                .where(
                    Task.campaign_id == campaign.id,
                    Task.status.in_([TaskStatus.pending, TaskStatus.retry, TaskStatus.running]),
                )
            ) or 0
            buffer_size = max(settings.worker_concurrency * 2, 2)
            added = 0
            while active < buffer_size:
                db.add(
                    Task(
                        campaign_id=campaign.id,
                        account_id=None,
                        action_type=campaign.action_type,
                        target_url=campaign.target_url,
                        idempotency_key=f"{campaign.id}:u{uuid.uuid4().hex[:10]}",
                    )
                )
                active += 1
                added += 1
            if added:
                db.commit()
                log(f"refilled unlimited campaign {campaign.id[:8]} with {added} task(s)")

    def _create_account(self, db, platform) -> Account:
        mailbox = create_mailbox()
        log(f"mailbox created: {mailbox.address}")
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
            account.last_error = str(exc)[:2000]
            account.status = AccountStatus.error
        finally:
            context.close()
            db.commit()
            db.refresh(account)
        return account


class WorkerPool:
    def __init__(self):
        self.workers = [
            Worker(index)
            for index in range(max(1, settings.worker_concurrency))
        ]

    def start(self):
        db = SessionLocal()
        try:
            for task in db.scalars(select(Task).where(Task.status == TaskStatus.running)):
                task.status = TaskStatus.pending
                task.started_at = None
            db.commit()
        finally:
            db.close()

        for worker in self.workers:
            worker.start()

    def stop(self):
        for worker in self.workers:
            worker.stop()
        for worker in self.workers:
            if worker.is_alive():
                worker.join(timeout=10)
