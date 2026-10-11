from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "SocialBoost"
    secret_key: str = "change-me-please"

    database_url: str = "sqlite:///./data/socialboost.db"

    tempmail_providers: str = "mailtm,mailgw"
    tempmail_password: str = "S0cial!Boost#2024"

    headless: bool = True
    worker_poll_seconds: int = 3
    max_tasks_per_account: int = 1

    allowed_origins: str = "*"


@lru_cache
def get_settings() -> Settings:
    return Settings()
