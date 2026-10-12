from fastapi.testclient import TestClient

from app import main as main_module


class NoopPool:
    def start(self):
        pass

    def stop(self):
        pass


def test_read_only_api_endpoints(monkeypatch):
    monkeypatch.setattr(main_module, "WorkerPool", NoopPool)
    with TestClient(main_module.app) as client:
        assert client.get("/api/health").json() == {"ok": True}
        assert client.get("/api/campaigns").status_code == 200
        assert client.get("/api/accounts").status_code == 200
        dashboard = client.get("/api/dashboard")
        assert dashboard.status_code == 200
        assert "total_tasks" in dashboard.json()
