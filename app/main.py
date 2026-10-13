from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import Base, SessionLocal, engine, ensure_campaign_unlimited_column, get_db
from .models import (
    Account,
    AccountStatus,
    Campaign,
    CampaignStatus,
    Task,
    TaskStatus,
)
from .orchestrator import create_campaign
from .schemas import (
    AccountOut,
    CampaignCreate,
    CampaignOut,
    DashboardStats,
    TaskOut,
)
from .worker import WorkerPool

settings = get_settings()

Base.metadata.create_all(bind=engine)
ensure_campaign_unlimited_column(engine)

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ROOT = Path(__file__).resolve().parent.parent
BUILD = "v3-selftest"
pool: WorkerPool | None = None


@app.on_event("startup")
def _startup():
    global pool
    pool = WorkerPool()
    pool.start()


@app.on_event("shutdown")
def _shutdown():
    if pool:
        pool.stop()


@app.get("/")
def index():
    return FileResponse(ROOT / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/version")
def version():
    return {"build": BUILD}


@app.get("/api/debug/selftest")
def selftest():
    """Check temporary mail, Playwright/YouTube reachability, and database access."""
    from .mail import create_mailbox

    output = {"build": BUILD, "checks": {}}

    try:
        mailbox = create_mailbox()
        output["checks"]["tempmail"] = {"ok": True, "address": mailbox.address}
    except Exception as exc:
        output["checks"]["tempmail"] = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    playwright = browser = context = None
    try:
        from .worker import launch_browser

        playwright, browser = launch_browser()
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://www.youtube.com", wait_until="domcontentloaded", timeout=45000)
        output["checks"]["browser"] = {"ok": True, "title": page.title()}
    except Exception as exc:
        output["checks"]["browser"] = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        for resource in (context, browser, playwright):
            if resource is not None:
                try:
                    resource.close() if resource is not playwright else resource.stop()
                except Exception:
                    pass

    db = None
    try:
        db = SessionLocal()
        output["checks"]["db"] = {
            "ok": True,
            "campaigns": db.scalar(select(func.count()).select_from(Campaign)),
            "accounts": db.scalar(select(func.count()).select_from(Account)),
        }
    except Exception as exc:
        output["checks"]["db"] = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        if db is not None:
            db.close()

    return output


@app.post("/api/campaigns", response_model=CampaignOut)
def create(payload: CampaignCreate, db: Session = Depends(get_db)):
    try:
        return create_campaign(db, payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/campaigns", response_model=list[CampaignOut])
def list_campaigns(db: Session = Depends(get_db)):
    return list(db.scalars(select(Campaign).order_by(Campaign.created_at.desc())))


@app.get("/api/campaigns/{cid}", response_model=CampaignOut)
def get_campaign(cid: str, db: Session = Depends(get_db)):
    campaign = db.get(Campaign, cid)
    if not campaign:
        raise HTTPException(404, "קמפיין לא נמצא")
    return campaign


@app.get("/api/campaigns/{cid}/tasks", response_model=list[TaskOut])
def campaign_tasks(cid: str, db: Session = Depends(get_db)):
    return list(db.scalars(select(Task).where(Task.campaign_id == cid)))


def _set_status(cid: str, status: CampaignStatus, db: Session):
    campaign = db.get(Campaign, cid)
    if not campaign:
        raise HTTPException(404, "קמפיין לא נמצא")
    campaign.status = status
    db.commit()
    db.refresh(campaign)
    return campaign


@app.post("/api/campaigns/{cid}/pause", response_model=CampaignOut)
def pause(cid: str, db: Session = Depends(get_db)):
    return _set_status(cid, CampaignStatus.paused, db)


@app.post("/api/campaigns/{cid}/resume", response_model=CampaignOut)
def resume(cid: str, db: Session = Depends(get_db)):
    return _set_status(cid, CampaignStatus.running, db)


@app.post("/api/campaigns/{cid}/cancel", response_model=CampaignOut)
def cancel(cid: str, db: Session = Depends(get_db)):
    campaign = db.get(Campaign, cid)
    if not campaign:
        raise HTTPException(404, "קמפיין לא נמצא")
    for task in db.scalars(
        select(Task).where(
            Task.campaign_id == cid,
            Task.status.in_([TaskStatus.pending, TaskStatus.retry]),
        )
    ):
        task.status = TaskStatus.cancelled
    campaign.status = CampaignStatus.cancelled
    db.commit()
    db.refresh(campaign)
    return campaign


@app.get("/api/accounts", response_model=list[AccountOut])
def list_accounts(db: Session = Depends(get_db)):
    return list(db.scalars(select(Account).order_by(Account.created_at.desc())))


@app.get("/api/dashboard", response_model=DashboardStats)
def dashboard(db: Session = Depends(get_db)):
    def count(model, *where):
        return db.scalar(select(func.count()).select_from(model).where(*where)) or 0

    return DashboardStats(
        total_campaigns=count(Campaign),
        active_campaigns=count(Campaign, Campaign.status == CampaignStatus.running),
        total_tasks=count(Task),
        completed_tasks=count(Task, Task.status == TaskStatus.success),
        failed_tasks=count(Task, Task.status == TaskStatus.failed),
        pending_tasks=count(
            Task, Task.status.in_([TaskStatus.pending, TaskStatus.retry, TaskStatus.running])
        ),
        total_accounts=count(Account),
        active_accounts=count(Account, Account.status == AccountStatus.active),
    )
