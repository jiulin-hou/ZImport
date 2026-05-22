import io

import pytest
from zimport import web, zimbra_auth


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


def test_folders_returns_paths(app, monkeypatch):
    monkeypatch.setattr(web.zimbra_auth, "delegate_token",
                        lambda cfg, acc: "TOK")
    monkeypatch.setattr(web.zimbra_folders, "list_folders",
                        lambda cfg, tok: ["Inbox", "Sent"])
    client = _login(app, monkeypatch)
    resp = client.get("/api/folders")
    assert resp.status_code == 200
    assert resp.get_json()["folders"] == ["Inbox", "Sent"]


def test_folders_forbidden_for_non_admin_other_account(app, monkeypatch):
    client = _login(app, monkeypatch)
    resp = client.get("/api/folders?account=other@d")
    assert resp.status_code == 403


def test_admin_account_search_requires_admin(app, monkeypatch):
    # 普通用户登录
    client = _login(app, monkeypatch)
    resp = client.get("/api/admin/accounts/search?q=al")
    assert resp.status_code == 403


def test_retry_creates_new_task_for_failed(app, monkeypatch, tmp_path):
    """已 failed 的任务、temp_dir 还在 -> retry 返回新 task_id 并入队。"""
    from zimport.store import TaskStore
    # _Cfg.db_path 在 app fixture 里写到 tmp_path / "t.db"
    db_path = str(tmp_path / "t.db")
    store = TaskStore(db_path)
    temp_dir = tmp_path / "td"
    temp_dir.mkdir()
    old_id = store.create_task(account="u@d", requester="u@d",
                                target_folder="Inbox",
                                temp_dir=str(temp_dir))
    store.set_status(old_id, "failed", error="boom")

    client = _login(app, monkeypatch)
    resp = client.post("/api/tasks/" + old_id + "/retry")
    assert resp.status_code == 200, resp.get_json()
    new_id = resp.get_json()["task_id"]
    assert new_id != old_id
    new = store.get_task(new_id)
    assert new["status"] == "queued"
    assert new["temp_dir"] == str(temp_dir)
    assert new["target_folder"] == "Inbox"


def test_retry_410_when_temp_dir_gone(app, monkeypatch, tmp_path):
    """temp_dir 已被 purge -> 410。"""
    from zimport.store import TaskStore
    store = TaskStore(str(tmp_path / "t.db"))
    old_id = store.create_task(account="u@d", requester="u@d",
                                target_folder="Inbox",
                                temp_dir=str(tmp_path / "gone"))
    store.set_status(old_id, "failed", error="boom")
    client = _login(app, monkeypatch)
    assert client.post("/api/tasks/" + old_id + "/retry").status_code == 410


def test_retry_403_for_other_user(app, monkeypatch, tmp_path):
    """非 requester 且非 admin 不能重试他人任务。"""
    from zimport.store import TaskStore
    store = TaskStore(str(tmp_path / "t.db"))
    td = tmp_path / "td"; td.mkdir()
    old_id = store.create_task(account="other@d", requester="other@d",
                                target_folder="Inbox", temp_dir=str(td))
    store.set_status(old_id, "failed")
    client = _login(app, monkeypatch)  # 登的是 u@d,不是 other@d
    assert client.post("/api/tasks/" + old_id + "/retry").status_code == 403


def test_retry_404_when_missing(app, monkeypatch):
    client = _login(app, monkeypatch)
    assert client.post("/api/tasks/nosuch/retry").status_code == 404


def test_retry_400_when_status_not_failed(app, monkeypatch, tmp_path):
    """status=queued/done/running 都不应该让重试。"""
    client = _login(app, monkeypatch)
    # 用 /api/upload + /api/import 造一个 queued 任务
    monkeypatch.setattr(web.uploads, "input_dir",
                        lambda root, uid: str(tmp_path))
    monkeypatch.setattr(web.uploads, "upload_dir",
                        lambda root, uid: str(tmp_path))
    monkeypatch.setattr(web.uploads, "merge_file",
                        lambda *a, **kw: None)
    monkeypatch.setattr(web.os, "listdir", lambda p: [])  # 0 字节
    init = client.post("/api/upload/init").get_json()
    r = client.post("/api/import", json={
        "upload_id": init["upload_id"], "files": [], "folder": "Inbox"})
    task_id = r.get_json()["task_id"]
    resp = client.post("/api/tasks/" + task_id + "/retry")
    assert resp.status_code == 400


def test_admin_account_search_returns_results(app, monkeypatch):
    monkeypatch.setattr(web.zimbra_auth, "login",
                        lambda cfg, u, p: zimbra_auth.Identity(True, u))
    monkeypatch.setattr(web.zimbra_search, "search_accounts",
                        lambda cfg, q: [{"name": "a@d", "display": "A"}])
    client = app.test_client()
    client.post("/api/login", json={"username": "admin@d", "password": "x"})
    resp = client.get("/api/admin/accounts/search?q=ali")
    assert resp.status_code == 200
    assert resp.get_json()["accounts"][0]["name"] == "a@d"


def _login(app, monkeypatch):
    monkeypatch.setattr(web.zimbra_auth, "login",
                        lambda cfg, u, p: zimbra_auth.Identity(False, u))
    client = app.test_client()
    client.post("/api/login", json={"username": "u@d", "password": "pw"})
    return client


def test_upload_init_and_chunk_flow(app, monkeypatch):
    client = _login(app, monkeypatch)
    init = client.post("/api/upload/init", json={})
    assert init.status_code == 200
    upload_id = init.get_json()["upload_id"]

    resp = client.post("/api/upload/chunk", data={
        "upload_id": upload_id, "file_index": "0", "chunk_index": "0",
        "blob": (io.BytesIO(b"HELLO"), "blob"),
    }, content_type="multipart/form-data")
    assert resp.status_code == 200

    status = client.get("/api/upload/status",
                        query_string={"upload_id": upload_id,
                                      "file_index": "0",
                                      "total_chunks": "2"})
    assert status.get_json()["missing"] == [1]


def test_upload_chunk_requires_login(app):
    client = app.test_client()
    resp = client.post("/api/upload/chunk", data={"upload_id": "x"})
    assert resp.status_code == 401


def test_import_merges_and_enqueues(app, monkeypatch):
    client = _login(app, monkeypatch)
    upload_id = client.post("/api/upload/init", json={}).get_json()["upload_id"]
    client.post("/api/upload/chunk", data={
        "upload_id": upload_id, "file_index": "0", "chunk_index": "0",
        "blob": (io.BytesIO(b"From: a@b\r\n\r\nhi"), "blob"),
    }, content_type="multipart/form-data")

    resp = client.post("/api/import", json={
        "upload_id": upload_id,
        "files": [{"index": 0, "name": "msg.eml", "chunks": 1}],
        "folder": "Inbox",
    })
    assert resp.status_code == 200
    task_id = resp.get_json()["task_id"]
    task = client.get("/api/tasks/" + task_id).get_json()
    assert task["status"] == "queued"
    assert task["account"] == "u@d"


def test_normal_user_cannot_target_other_account(app, monkeypatch):
    client = _login(app, monkeypatch)
    upload_id = client.post("/api/upload/init", json={}).get_json()["upload_id"]
    client.post("/api/upload/chunk", data={
        "upload_id": upload_id, "file_index": "0", "chunk_index": "0",
        "blob": (io.BytesIO(b"x"), "blob"),
    }, content_type="multipart/form-data")
    resp = client.post("/api/import", json={
        "upload_id": upload_id,
        "files": [{"index": 0, "name": "m.eml", "chunks": 1}],
        "folder": "Inbox",
        "account": "victim@d",          # 普通用户试图指定他人
    })
    task_id = resp.get_json()["task_id"]
    # 后端强制改写为登录账户
    assert client.get("/api/tasks/" + task_id).get_json()["account"] == "u@d"


def test_import_rejected_when_queue_full(app, monkeypatch):
    app_cfg_full = app
    # 把 queue_limit 调到 0 触发拒绝
    client = _login(app, monkeypatch)
    monkeypatch.setattr(web, "_queue_limit_for", lambda store, cfg: 0)
    upload_id = client.post("/api/upload/init", json={}).get_json()["upload_id"]
    client.post("/api/upload/chunk", data={
        "upload_id": upload_id, "file_index": "0", "chunk_index": "0",
        "blob": (io.BytesIO(b"x"), "blob"),
    }, content_type="multipart/form-data")
    resp = client.post("/api/import", json={
        "upload_id": upload_id,
        "files": [{"index": 0, "name": "m.eml", "chunks": 1}],
        "folder": "Inbox",
    })
    assert resp.status_code == 429


def test_upload_chunk_rejects_bad_upload_id(app, monkeypatch):
    client = _login(app, monkeypatch)
    resp = client.post("/api/upload/chunk", data={
        "upload_id": "../../etc", "file_index": "0", "chunk_index": "0",
        "blob": (io.BytesIO(b"x"), "blob"),
    }, content_type="multipart/form-data")
    assert resp.status_code == 400


def test_me_returns_identity(app, monkeypatch):
    client = _login(app, monkeypatch)
    resp = client.get("/api/me")
    assert resp.status_code == 200
    assert resp.get_json()["account"] == "u@d"
    assert resp.get_json()["is_admin"] is False


def test_me_requires_login(app):
    assert app.test_client().get("/api/me").status_code == 401
