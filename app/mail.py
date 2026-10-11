import random
import re
import string
import time
from dataclasses import dataclass

import httpx

from .config import get_settings

settings = get_settings()
TIMEOUT = 20.0

PROVIDERS = {
    "mailtm": "https://api.mail.tm",
    "mailgw": "https://api.mail.gw",
}

CODE_RE = re.compile(r"\b(\d{4,8})\b")


@dataclass
class Mailbox:
    base_url: str
    address: str
    password: str
    token: str


def _client(base_url: str) -> httpx.Client:
    return httpx.Client(base_url=base_url, timeout=TIMEOUT)


def _random_local() -> str:
    return "sb" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10))


def create_mailbox() -> Mailbox:
    order = [p.strip() for p in settings.tempmail_providers.split(",") if p.strip()]
    last_error = None

    for name in order:
        base_url = PROVIDERS.get(name)
        if not base_url:
            continue
        try:
            with _client(base_url) as c:
                domains = c.get("/domains")
                domains.raise_for_status()
                active = [d["domain"] for d in domains.json() if d.get("isActive", True)]
                if not active:
                    continue
                address = f"{_random_local()}@{random.choice(active)}"
                password = settings.tempmail_password

                r = c.post("/accounts", json={"address": address, "password": password})
                r.raise_for_status()

                t = c.post("/token", json={"address": address, "password": password})
                t.raise_for_status()
                return Mailbox(base_url, address, password, t.json()["token"])
        except Exception as exc:
            last_error = exc

    raise RuntimeError(f"לא הצלחתי ליצור תיבת דואר זמנית: {last_error}")


def _messages(mb: Mailbox) -> list[dict]:
    with _client(mb.base_url) as c:
        r = c.get("/messages", headers={"Authorization": f"Bearer {mb.token}"})
        r.raise_for_status()
        data = r.json()
        return data.get("hydra:member", data)


def _message(mb: Mailbox, msg_id: str) -> dict:
    with _client(mb.base_url) as c:
        r = c.get(f"/messages/{msg_id}", headers={"Authorization": f"Bearer {mb.token}"})
        r.raise_for_status()
        return r.json()


def wait_for_code(mb: Mailbox, timeout: int = 150, poll: int = 5) -> str | None:
    deadline = time.time() + timeout
    seen: set[str] = set()
    while time.time() < deadline:
        try:
            for msg in _messages(mb):
                if msg["id"] in seen:
                    continue
                seen.add(msg["id"])
                full = _message(mb, msg["id"])
                text = full.get("text") or ""
                html = full.get("html") or ""
                blob = text + "\n" + (html if isinstance(html, str) else " ".join(html))
                match = CODE_RE.search(blob)
                if match:
                    return match.group(1)
        except Exception:
            pass
        time.sleep(poll)
    return None
