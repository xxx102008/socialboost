from datetime import datetime, timezone

from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, ensure_campaign_unlimited_column
from app.models import (
    ActionType,
    Campaign,
    CampaignStatus,
    Platform,
    Task,
    TaskStatus,
)
from app.orchestrator import create_campaign, recompute_campaign
from app.platforms.base import StepError, run_step
from app.schemas import CampaignCreate
from app import worker as worker_module


def make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def test_create_campaign_creates_requested_initial_tasks():
    engine, factory = make_session_factory()
    try:
        with factory() as db:
            campaign = create_campaign(
                db,
                CampaignCreate(
                    url="https://www.youtube.com/shorts/abc123",
                    action=ActionType.like,
                    quantity=2,
                    unlimited=False,
                ),
            )
            tasks = list(db.scalars(select(Task).where(Task.campaign_id == campaign.id)))
            assert campaign.platform == Platform.youtube
            assert campaign.status == CampaignStatus.running
            assert campaign.unlimited is False
            assert len(tasks) == 2
            assert all(task.status == TaskStatus.pending for task in tasks)
    finally:
        engine.dispose()


def test_unlimited_campaign_remains_running_after_current_work_finishes():
    engine, factory = make_session_factory()
    try:
        with factory() as db:
            campaign = create_campaign(
                db,
                CampaignCreate(
                    url="https://www.youtube.com/watch?v=abc123",
                    action=ActionType.like,
                    quantity=1,
                    unlimited=True,
                ),
            )
            task = db.scalar(select(Task).where(Task.campaign_id == campaign.id))
            task.status = TaskStatus.success
            db.commit()

            recompute_campaign(db, campaign)

            assert campaign.status == CampaignStatus.running
            assert campaign.success_count == 1
            assert campaign.unlimited is True
    finally:
        engine.dispose()


def test_worker_enqueues_next_unlimited_task(monkeypatch):
    engine, factory = make_session_factory()
    old_session_local = worker_module.SessionLocal
    old_concurrency = worker_module.settings.worker_concurrency

    class RecordingWorker(worker_module.Worker):
        def _process(self, db, task):
            task.status = TaskStatus.success
            task.result = {"test": True}
            task.finished_at = datetime.now(timezone.utc)
            db.commit()
            campaign = db.get(Campaign, task.campaign_id)
            recompute_campaign(db, campaign)

    try:
        monkeypatch.setattr(worker_module, "SessionLocal", factory)
        monkeypatch.setattr(worker_module.settings, "worker_concurrency", 1)
        with factory() as db:
            campaign = create_campaign(
                db,
                CampaignCreate(
                    url="https://www.youtube.com/watch?v=abc123",
                    action=ActionType.view,
                    quantity=1,
                    unlimited=True,
                ),
            )
            existing_task = db.scalar(select(Task).where(Task.campaign_id == campaign.id))
            existing_task.status = TaskStatus.success
            db.commit()
            campaign_id = campaign.id

        assert RecordingWorker()._tick() is True

        with factory() as db:
            tasks = list(db.scalars(select(Task).where(Task.campaign_id == campaign_id)))
            assert len(tasks) == 2
            assert all(task.status == TaskStatus.success for task in tasks)
            assert tasks[1].idempotency_key == f"unlimited:{campaign_id}:1"
    finally:
        worker_module.SessionLocal = old_session_local
        worker_module.settings.worker_concurrency = old_concurrency
        engine.dispose()


def test_legacy_sqlite_campaign_table_gets_unlimited_column():
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE campaigns (id VARCHAR(32) PRIMARY KEY)")
            connection.exec_driver_sql("INSERT INTO campaigns (id) VALUES ('legacy')")
        ensure_campaign_unlimited_column(engine)
        columns = {column["name"]: column for column in inspect(engine).get_columns("campaigns")}
        assert "unlimited" in columns
        with engine.connect() as connection:
            value = connection.exec_driver_sql("SELECT unlimited FROM campaigns").scalar_one_or_none()
            assert value in (False, 0)
    finally:
        engine.dispose()


def test_run_step_includes_name_url_and_exception_type():
    class Page:
        url = "https://example.test/video"

    def fail():
        raise TimeoutError("locator did not appear")

    try:
        run_step(Page(), "like-button", fail)
    except StepError as exc:
        message = str(exc)
    else:
        raise AssertionError("run_step should raise StepError")

    assert "step=like-button" in message
    assert "https://example.test/video" in message
    assert "TimeoutError" in message
    assert "locator did not appear" in message
