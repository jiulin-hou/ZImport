import os
import pytest
from zimport import worker, archive
from zimport.store import TaskStore


class _Cfg:
    db_path = None  # set per test
    dedupe = False  # 旧 tests 走非去重路径,保持行为不变


class _CfgDedupe:
    db_path = None
    dedupe = True


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


def test_process_task_dedup_within_batch(tmp_path, monkeypatch):
    """同一批内含两封同 Message-ID 的 eml,第二封算 skipped 而不是 done。"""
    store = TaskStore(str(tmp_path / "wd.db"))
    temp_dir = tmp_path / "taskd"
    (temp_dir / "input").mkdir(parents=True)
    (temp_dir / "input" / "a.eml").write_bytes(b"a")
    (temp_dir / "input" / "b.eml").write_bytes(b"b")
    tid = store.create_task("u@d", "u@d", "Inbox", str(temp_dir))
    task = store.claim_next()

    monkeypatch.setattr(worker.zimbra_auth, "delegate_token",
                        lambda cfg, a: "TOK")
    monkeypatch.setattr(worker.zimbra_inject, "read_message_id",
                        lambda p: "<dup@x>")  # 所有 eml 同 id
    monkeypatch.setattr(worker.zimbra_inject, "message_exists",
                        lambda cfg, tok, mid: False)  # 邮箱里没
    injected = []
    monkeypatch.setattr(worker.zimbra_inject, "inject_eml",
                        lambda cfg, a, f, t, p: injected.append(p))

    worker.process_task(_CfgDedupe, store, task)
    result = store.get_task(tid)
    assert result["status"] == "done"
    assert result["done"] == 1, "只第一封注入"
    assert result["skipped"] == 1, "第二封跳过"
    assert result["failed"] == 0
    assert len(injected) == 1


def test_process_task_dedup_against_mailbox(tmp_path, monkeypatch):
    """邮箱里已有同 id 的邮件,本次注入被跳过。"""
    store = TaskStore(str(tmp_path / "we.db"))
    temp_dir = tmp_path / "taske"
    (temp_dir / "input").mkdir(parents=True)
    (temp_dir / "input" / "a.eml").write_bytes(b"a")
    tid = store.create_task("u@d", "u@d", "Inbox", str(temp_dir))
    task = store.claim_next()

    monkeypatch.setattr(worker.zimbra_auth, "delegate_token",
                        lambda cfg, a: "TOK")
    monkeypatch.setattr(worker.zimbra_inject, "read_message_id",
                        lambda p: "<x@y>")
    monkeypatch.setattr(worker.zimbra_inject, "message_exists",
                        lambda cfg, tok, mid: True)
    monkeypatch.setattr(worker.zimbra_inject, "inject_eml",
                        lambda *a, **kw: pytest.fail("不应触发 inject"))

    worker.process_task(_CfgDedupe, store, task)
    result = store.get_task(tid)
    assert result["done"] == 0 and result["skipped"] == 1 and result["failed"] == 0


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
