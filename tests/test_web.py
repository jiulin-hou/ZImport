import pytest
from zimbra_import import web, zimbra_auth


class _Cfg:
    secret_key = "test-secret"
    temp_root = None       # set per test
    db_path = None
    queue_limit = 50
    max_task_bytes = 10 ** 12
    chunk_size = 1024


@pytest.fixture
def app(tmp_path, monkeypatch):
    cfg = _Cfg()
    cfg.temp_root = str(tmp_path / "tmp")
    cfg.db_path = str(tmp_path / "t.db")
    application = web.create_app(cfg)
    application.config["TESTING"] = True
    return application


def test_login_success_sets_session(app, monkeypatch):
    monkeypatch.setattr(web.zimbra_auth, "login",
                        lambda cfg, u, p: zimbra_auth.Identity(False, u))
    client = app.test_client()
    resp = client.post("/api/login", json={"username": "u@d",
                                            "password": "pw"})
    assert resp.status_code == 200
    assert resp.get_json()["account"] == "u@d"
    assert resp.get_json()["is_admin"] is False


def test_login_failure_returns_401(app, monkeypatch):
    def boom(cfg, u, p):
        raise zimbra_auth.AuthError("bad")
    monkeypatch.setattr(web.zimbra_auth, "login", boom)
    client = app.test_client()
    resp = client.post("/api/login", json={"username": "u@d",
                                            "password": "x"})
    assert resp.status_code == 401


def test_tasks_requires_login(app):
    client = app.test_client()
    assert client.get("/api/tasks").status_code == 401
