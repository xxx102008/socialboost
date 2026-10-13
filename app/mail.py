import random
import re
import string
import time
from dataclasses import dataclass, field

import httpx

from .config import get_settings

settings = get_settings()
TIMEOUT = 25.0
CODE_RE = re.compile(r"\b(\d{4,8})\b")
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36"
}


def _rand(n: int = 10) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


@dataclass
class Mailbox:
    provider: str
    address: str
    handle: dict = field(default_factory=dict)

    @property
    def password(self) -> str | None:
        """Keep compatibility with account persistence; token-only providers have no password."""
        return self.handle.get("password")

    def messages(self) -> list[dict]:
        reader = _READERS[self.provider]
        try:
            return reader(self)
        except Exception as exc:
            print(f"[SB] mail read failed ({self.provider}): {type(exc).__name__}: {exc}", flush=True)
            return []


def _items(data, key: str = "messages") -> list[dict]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for candidate in (key, "hydra:member"):
            value = data.get(candidate)
            if isinstance(value, list):
                return value
    return []


# ---------------------- readers ----------------------


def _read_lol(mb: Mailbox) -> list[dict]:
    with httpx.Client(timeout=TIMEOUT, headers=UA) as client:
        response = client.get(
            "https://api.tempmail.lol/v2/inbox", params={"token": mb.handle["token"]}
        )
        response.raise_for_status()
        data = response.json()
    return [
        {
            "id": f"lol-{i}-{message.get('date', '')}",
            "subject": message.get("subject", ""),
            "text": message.get("body", "") or message.get("text", ""),
            "html": message.get("html", ""),
        }
        for i, message in enumerate(_items(data, "emails"))
    ]


def _read_io(mb: Mailbox) -> list[dict]:
    with httpx.Client(timeout=TIMEOUT, headers=UA) as client:
        response = client.get(
            f"https://api.internal.temp-mail.io/api/v3/email/{mb.address}/messages"
        )
        response.raise_for_status()
        data = response.json()
    return [
        {
            "id": message.get("id") or f"io-{i}",
            "subject": message.get("subject", ""),
            "text": message.get("body_text", ""),
            "html": message.get("body_html", ""),
        }
        for i, message in enumerate(_items(data))
    ]


def _read_org(mb: Mailbox) -> list[dict]:
    with httpx.Client(
        timeout=TIMEOUT,
        headers={**UA, "Authorization": f"Bearer {mb.handle['token']}"},
    ) as client:
        response = client.get("https://web2.temp-mail.org/messages")
        response.raise_for_status()
        data = response.json()
    return [
        {
            "id": message.get("_id") or f"org-{i}",
            "subject": message.get("subject", ""),
            "text": message.get("body", "") or message.get("text", ""),
            "html": message.get("html", ""),
        }
        for i, message in enumerate(_items(data))
    ]


def _read_mailtm(mb: Mailbox) -> list[dict]:
    with httpx.Client(base_url=mb.handle["base"], timeout=TIMEOUT, headers=UA) as client:
        response = client.get(
            "/messages", headers={"Authorization": f"Bearer {mb.handle['token']}"}
        )
        response.raise_for_status()
        data = response.json()
        messages = _items(data)
        output = []
        for index, message in enumerate(messages):
            message_id = message.get("id")
            text = message.get("text", "")
            html = message.get("html", "")
            # mail.tm message lists may omit message bodies; fetch the detail in that case.
            if message_id and not (text or html):
                detail_response = client.get(
                    f"/messages/{message_id}",
                    headers={"Authorization": f"Bearer {mb.handle['token']}"},
                )
                detail_response.raise_for_status()
                detail = detail_response.json()
                text = detail.get("text", "")
                html = detail.get("html", "")
            output.append(
                {
                    "id": message_id or f"mailtm-{index}",
                    "subject": message.get("subject", ""),
                    "text": text,
                    "html": html,
                }
            )
    return output


# ---------------------- creators ----------------------


def _create_lol() -> Mailbox:
    with httpx.Client(timeout=TIMEOUT, headers=UA) as client:
        response = client.post("https://api.tempmail.lol/v2/inbox/create", json={})
        if response.status_code >= 400:
            response = client.get("https://api.tempmail.lol/v2/inbox/create")
        response.raise_for_status()
        data = response.json()
    address, token = data.get("address"), data.get("token")
    if not address or not token:
        raise RuntimeError("tempmail.lol did not return an address and token")
    return Mailbox("tempmail_lol", address, {"token": token})


def _create_io() -> Mailbox:
    with httpx.Client(timeout=TIMEOUT, headers=UA) as client:
        response = client.post(
            "https://api.internal.temp-mail.io/api/v3/email/new",
            json={"min_name_length": 10, "max_name_length": 10},
        )
        response.raise_for_status()
        data = response.json()
    address = data.get("email") or data.get("address")
    if not address:
        raise RuntimeError("temp-mail.io did not return an email address")
    handle = {"token": data.get("token")} if data.get("token") else {}
    return Mailbox("temp_mail_io", address, handle)


def _create_org() -> Mailbox:
    with httpx.Client(timeout=TIMEOUT, headers=UA) as client:
        response = client.post("https://web2.temp-mail.org/mailbox", json={})
        response.raise_for_status()
        data = response.json()
    address = data.get("mailbox") or data.get("email") or data.get("address")
    token = data.get("token") or data.get("access_token")
    if not address or not token:
        raise RuntimeError("temp-mail.org did not return an address and token")
    return Mailbox("temp_mail_org", address, {"token": token})


def _create_mailtm() -> Mailbox:
    return _create_mailtm_like("https://api.mail.tm", "mailtm")


def _create_mailgw() -> Mailbox:
    return _create_mailtm_like("https://api.mail.gw", "mailgw")


def _create_mailtm_like(base: str, name: str) -> Mailbox:
    with httpx.Client(base_url=base, timeout=TIMEOUT, headers=UA) as client:
        domains_response = client.get("/domains")
        domains_response.raise_for_status()
        domains_data = domains_response.json()
        domains = _items(domains_data, "hydra:member")
        active = [domain["domain"] for domain in domains if domain.get("isActive", True)]
        if not active:
            raise RuntimeError("אין דומיין זמין")

        address = f"sb{_rand(10)}@{random.choice(active)}"
        password = settings.tempmail_password
        account_response = client.post(
            "/accounts", json={"address": address, "password": password}
        )
        account_response.raise_for_status()
        token_response = client.post(
            "/token", json={"address": address, "password": password}
        )
        token_response.raise_for_status()
        token = token_response.json().get("token")
        if not token:
            raise RuntimeError(f"{name} did not return an access token")
    return Mailbox(name, address, {"token": token, "base": base, "password": password})


_CREATORS = {
    "tempmail_lol": _create_lol,
    "mailtm": _create_mailtm,
    "temp_mail_io": _create_io,
    "temp_mail_org": _create_org,
    "mailgw": _create_mailgw,
}

_READERS = {
    "tempmail_lol": _read_lol,
    "mailtm": _read_mailtm,
    "mailgw": _read_mailtm,
    "temp_mail_io": _read_io,
    "temp_mail_org": _read_org,
}


def _provider_order() -> list[str]:
    order = [provider.strip() for provider in settings.tempmail_providers.split(",")]
    configured = [provider for provider in order if provider in _CREATORS]
    return configured or ["tempmail_lol", "mailtm", "temp_mail_io", "temp_mail_org", "mailgw"]


def create_mailbox() -> Mailbox:
    failures = []
    for name in _provider_order():
        try:
            mailbox = _CREATORS[name]()
            if mailbox.address:
                print(f"[SB] mail provider {name} created mailbox", flush=True)
                return mailbox
            raise RuntimeError("provider returned an empty address")
        except Exception as exc:
            message = f"{name}: {type(exc).__name__}: {str(exc)[:250]}"
            failures.append(message)
            print(f"[SB] mail provider {message}", flush=True)
    raise RuntimeError("כל ספקי הדואר נכשלו: " + "; ".join(failures))


def wait_for_code(mb: Mailbox, timeout: int = 150, poll: int = 5) -> str | None:
    deadline = time.time() + timeout
    seen: set[str] = set()
    while time.time() < deadline:
        for index, message in enumerate(mb.messages()):
            message_id = str(message.get("id") or index)
            if message_id in seen:
                continue
            seen.add(message_id)
            blob = (
                f"{message.get('subject', '')}\n"
                f"{message.get('text', '')}\n"
                f"{message.get('html', '')}"
            )
            match = CODE_RE.search(blob)
            if match:
                return match.group(1)
        time.sleep(poll)
    return None
