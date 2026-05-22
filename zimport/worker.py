import os
import sys
import time
import shutil
import threading

from zimport import archive, zimbra_auth, zimbra_inject
from zimport.config import Config
from zimport.store import TaskStore


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
            # tgz 自带 resolve=skip,Zimbra 内部按 Message-ID 去重
            zimbra_inject.inject_tgz(cfg, task["account"], token,
                                     norm.repacked_tgz)
            store.update_progress(tid, done=1, failed=0)
        else:
            store.set_totals(tid, len(norm.eml_paths))
            done = failed = skipped = 0
            failures = []
            seen_local = set()  # 同批内重复(同 Message-ID)
            for path in norm.eml_paths:
                name = os.path.basename(path)
                try:
                    if cfg.dedupe:
                        mid = zimbra_inject.read_message_id(path)
                        if mid:
                            if mid in seen_local:
                                skipped += 1
                                failures.append({"name": name,
                                                 "reason": "duplicate (same batch)"})
                                store.update_progress(tid, done=done,
                                                      failed=failed,
                                                      skipped=skipped)
                                continue
                            seen_local.add(mid)
                            if zimbra_inject.message_exists(cfg, token, mid):
                                skipped += 1
                                failures.append({"name": name,
                                                 "reason": "duplicate (already in mailbox)"})
                                store.update_progress(tid, done=done,
                                                      failed=failed,
                                                      skipped=skipped)
                                continue
                    zimbra_inject.inject_eml(cfg, task["account"],
                                             task["target_folder"],
                                             token, path)
                    done += 1
                except zimbra_inject.InjectError as exc:
                    failed += 1
                    failures.append({"name": name, "reason": str(exc)})
                store.update_progress(tid, done=done, failed=failed,
                                      skipped=skipped)
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
