from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "SocialBoost"
    secret_key: str = "change-me-please"
    database_url: str = "sqlite:///./data/socialboost.db"

    tempmail_providers: str = "tempmail_lol,mailtm,temp_mail_io,temp_mail_org,mailgw"
    tempmail_password: str = "S0cial!Boost#2024"

    headless: bool = True

    # Keep the default to a single browser worker for memory-constrained hosts.
    worker_concurrency: int = 1
    worker_poll_seconds: int = 3

    # Avoid downloading large assets that are not needed for browser actions.
    block_heavy_assets: bool = True

    step_timeout_ms: int = 30000
    action_timeout_ms: int = 25000


@lru_cache
def get_settings() -> Settings:
    return Settings()
