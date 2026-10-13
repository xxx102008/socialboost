from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TypeVar

from ..models import ActionType, Platform


T = TypeVar("T")


def click_first(page, selectors: list[str], timeout: int = 8000) -> str:
    last = None
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=timeout)
            loc.click(timeout=timeout)
            return sel
        except Exception as exc:
            last = exc
    raise RuntimeError(f"לא נמצא סלקטור: {selectors}") from last


def try_click(page, selectors: list[str], timeout: int = 6000) -> bool:
    try:
        click_first(page, selectors, timeout)
        return True
    except Exception:
        return False


def fill_first(page, selectors: list[str], value: str, timeout: int = 8000) -> str:
    last = None
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=timeout)
            loc.fill(value, timeout=timeout)
            return sel
        except Exception as exc:
            last = exc
    raise RuntimeError(f"לא נמצא שדה: {selectors}") from last


class BasePlatform(ABC):
    platform: Platform

    @abstractmethod
    def perform(
        self, context, action: ActionType, target_url: str, account, comment: str | None = None
    ) -> dict:
        ...

    def create_account(self, context, account, mailbox) -> dict:
        raise NotImplementedError(f"יצירת חשבון לא מיושמת עבור {self.platform}")


class StepError(RuntimeError):
    """Failure annotated with the browser step and the page URL."""


def run_step(page, name: str, fn: Callable[[], T]) -> T:
    """Run one browser step and annotate failures with actionable context."""
    try:
        return fn()
    except StepError:
        raise
    except Exception as exc:
        try:
            url = page.url
        except Exception:
            url = "<unknown>"
        raise StepError(f"[step={name}] url={url} :: {type(exc).__name__}: {exc}") from exc
