import os
from zimport import worker, archive
from zimport.store import TaskStore


class _Cfg:
    db_path = None  # set per test


def test_process_task_eml_bundle(tmp_path, monkeypatch):
    store = TaskStore(str(tmp_path / "w.db"))
    temp_dir = tmp_path / "task1"
    (temp_dir / "input").mkdir(parents=True)
    (temp_dir / "input" / "a.eml").write_bytes(b"a")
    (temp_dir / "input" / "b.eml").write_bytes(b"b")
    tid = store.create_task("u@d", "u@d", "Inbox", str(temp_dir))
    task = store.claim_next()

    monkeypatch.setattr(worker.zimbra_auth, "delegate_token",
                        lambda cfg, acct: "TOK")
    injected = []
    monkeypatch.setattr(worker.zimbra_inject, "inject_eml",
                        lambda cfg, acct, folder, tok, p: injected.append(p))

    worker.process_task(_Cfg, store, task)
    result = store.get_task(tid)
    assert result["status"] == "done"
    assert result["total"] == 2 and result["done"] == 2
    assert len(injected) == 2


def test_process_task_records_per_eml_failure(tmp_path, monkeypatch):
    store = TaskStore(str(tmp_path / "w2.db"))
    temp_dir = tmp_path / "task2"
    (temp_dir / "input").mkdir(parents=True)
    (temp_dir / "input" / "ok.eml").write_bytes(b"a")
    (temp_dir / "input" / "bad.eml").write_bytes(b"b")
    tid = store.create_task("u@d", "u@d", "Inbox", str(temp_dir))
    task = store.claim_next()

    monkeypatch.setattr(worker.zimbra_auth, "delegate_token",
                        lambda cfg, acct: "TOK")

    def fake_inject(cfg, acct, folder, tok, p):
        if "bad" in p:
            raise worker.zimbra_inject.InjectError("boom")

    monkeypatch.setattr(worker.zimbra_inject, "inject_eml", fake_inject)
    worker.process_task(_Cfg, store, task)
    result = store.get_task(tid)
    assert result["status"] == "done"
    assert result["done"] == 1 and result["failed"] == 1
    import json
    assert json.loads(result["failures"])[0]["name"] == "bad.eml"


def test_process_task_marks_failed_on_unpack_error(tmp_path, monkeypatch):
    store = TaskStore(str(tmp_path / "w3.db"))
    temp_dir = tmp_path / "task3"
    (temp_dir / "input").mkdir(parents=True)
    tid = store.create_task("u@d", "u@d", "Inbox", str(temp_dir))
    task = store.claim_next()
    monkeypatch.setattr(worker.zimbra_auth, "delegate_token",
                        lambda cfg, acct: "TOK")

    def boom(input_dir, work_dir):
        raise ValueError("corrupt archive")

    monkeypatch.setattr(worker.archive, "normalize", boom)
    worker.process_task(_Cfg, store, task)
    result = store.get_task(tid)
    assert result["status"] == "failed"
    assert "corrupt" in result["error"]
