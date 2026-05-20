from zimbra_import.store import TaskStore


def test_create_and_get_task(tmp_path):
    store = TaskStore(str(tmp_path / "t.db"))
    tid = store.create_task(account="u@d", requester="u@d",
                            target_folder="Inbox", temp_dir="/tmp/x")
    task = store.get_task(tid)
    assert task["account"] == "u@d"
    assert task["status"] == "queued"
    assert task["done"] == 0


def test_list_tasks_filters_by_requester(tmp_path):
    store = TaskStore(str(tmp_path / "t2.db"))
    store.create_task("a@d", "admin@d", "Inbox", "/tmp/a")
    store.create_task("b@d", "admin@d", "Inbox", "/tmp/b")
    store.create_task("c@d", "other@d", "Inbox", "/tmp/c")
    assert len(store.list_tasks("admin@d")) == 2
    assert len(store.list_tasks("other@d")) == 1
