import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings

settings = get_settings()

if settings.database_url.startswith("sqlite"):
    os.makedirs("data", exist_ok=True)
    connect_args = {"check_same_thread": False}
else:
    connect_args = {}

engine = create_engine(
    settings.database_url, connect_args=connect_args, pool_pre_ping=True, future=True
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


def ensure_campaign_unlimited_column(bind=engine) -> None:
    """Add the unlimited flag to pre-existing databases without losing data."""
    inspector = inspect(bind)
    if "campaigns" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("campaigns")}
    if "unlimited" in columns:
        return

    default = "0" if bind.dialect.name == "sqlite" else "FALSE"
    with bind.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE campaigns "
                f"ADD COLUMN unlimited BOOLEAN NOT NULL DEFAULT {default}"
            )
        )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
