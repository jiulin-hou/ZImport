import os
import sys
import time
import shutil
import threading

from zimbra_import import archive, zimbra_auth, zimbra_inject
from zimbra_import.config import Config
from zimbra_import.store import TaskStore


def process_task(cfg, store, task):
    tid = task["id"]
    try:
        work = os.path.join(task["temp_dir"], "work")
        os.makedirs(work, exist_ok=True)
        norm = archive.normalize(os.path.join(task["temp_dir"], "input"), work)
        store.set_status(tid, "running", kind=norm.kind)
        token = zimbra_auth.delegate_token(cfg, task["account"])

        if norm.kind == "zimbra-export":
            store.set_totals(tid, 1)
            zimbra_inject.inject_tgz(cfg, task["account"], token,
                                     norm.repacked_tgz)
            store.update_progress(tid, done=1, failed=0)
        else:
            store.set_totals(tid, len(norm.eml_paths))
            done = failed = 0
            failures = []
            for path in norm.eml_paths:
                try:
                    zimbra_inject.inject_eml(cfg, task["account"],
                                             task["target_folder"],
                                             token, path)
                    done += 1
                except zimbra_inject.InjectError as exc:
                    failed += 1
                    failures.append({"name": os.path.basename(path),
                                     "reason": str(exc)})
                store.update_progress(tid, done=done, failed=failed)
            store.set_failures(tid, failures)
        store.set_status(tid, "done")
    except Exception as exc:  # noqa: BLE001 - top-level catch, any failure recorded
        store.set_status(tid, "failed", error=str(exc))


def _purge(cfg, store):
    for temp_dir in store.purge_old(cfg.retention_days):
        shutil.rmtree(temp_dir, ignore_errors=True)


def _loop(cfg, store):
    last_purge = 0.0
    while True:
        task = store.claim_next()
        if task is None:
            now = time.time()
            if now - last_purge > 3600:
                _purge(cfg, store)
                last_purge = now
            time.sleep(2)
            continue
        process_task(cfg, store, task)


def main():
    cfg = Config(sys.argv[1] if len(sys.argv) > 1 else "config.ini")
    store = TaskStore(cfg.db_path)
    store.recover_interrupted()
    threads = [threading.Thread(target=_loop, args=(cfg, store), daemon=True)
               for _ in range(cfg.concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
