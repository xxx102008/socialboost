from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import main as main_module
from app import mail as mail_module
from app import worker as worker_module


class NoopPool:
    def start(self):
        pass

    def stop(self):
        pass


class FakePage:
    def goto(self, *args, **kwargs):
        return None

    def title(self):
        return "YouTube test page"


class FakeContext:
    def new_page(self):
        return FakePage()

    def close(self):
        pass


class FakeBrowser:
    def new_context(self):
        return FakeContext()

    def close(self):
        pass


class FakePlaywright:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


class FakeDb:
    def __init__(self):
        self.count = 0
        self.closed = False

    def scalar(self, _query):
        self.count += 1
        return 4 if self.count == 1 else 9

    def close(self):
        self.closed = True


def test_version_and_selftest_endpoints_without_external_services(monkeypatch):
    monkeypatch.setattr(main_module, "WorkerPool", NoopPool)
    monkeypatch.setattr(
        mail_module,
        "create_mailbox",
        lambda: SimpleNamespace(address="selftest@example.test"),
    )
    playwright = FakePlaywright()
    monkeypatch.setattr(
        worker_module,
        "launch_browser",
        lambda: (playwright, FakeBrowser()),
    )
    database = FakeDb()
    monkeypatch.setattr(main_module, "SessionLocal", lambda: database)

    with TestClient(main_module.app) as client:
        assert client.get("/api/health").json() == {"ok": True}
        assert client.get("/api/version").json() == {"build": "v4-mailproviders"}
        response = client.get("/api/debug/selftest")

    assert response.status_code == 200
    result = response.json()
    assert result["build"] == "v4-mailproviders"
    assert result["checks"]["tempmail"] == {
        "ok": True,
        "address": "selftest@example.test",
    }
    assert result["checks"]["browser"] == {
        "ok": True,
        "title": "YouTube test page",
    }
    assert result["checks"]["db"] == {
        "ok": True,
        "campaigns": 4,
        "accounts": 9,
    }
    assert playwright.stopped is True
    assert database.closed is True
