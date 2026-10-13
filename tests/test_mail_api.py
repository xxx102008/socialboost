from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import main as main_module
from app import mail as mail_module


class NoopPool:
    def start(self):
        pass

    def stop(self):
        pass


def test_mailtest_reports_each_provider_without_network_calls(monkeypatch):
    monkeypatch.setattr(main_module, "WorkerPool", NoopPool)

    def bad_provider():
        raise RuntimeError("x" * 400)

    monkeypatch.setattr(
        mail_module,
        "_CREATORS",
        {
            "good": lambda: SimpleNamespace(address="good@example.test"),
            "bad": bad_provider,
        },
    )

    with TestClient(main_module.app) as client:
        response = client.get("/api/debug/mailtest")

    assert response.status_code == 200
    result = response.json()
    assert result["good"] == {"ok": True, "address": "good@example.test"}
    assert result["bad"]["ok"] is False
    assert result["bad"]["error"].startswith("RuntimeError:")
    assert len(result["bad"]["error"]) <= 300
