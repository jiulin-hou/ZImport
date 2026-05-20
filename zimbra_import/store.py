import os
import json
import uuid
import sqlite3
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  account TEXT NOT NULL,
  requester TEXT NOT NULL,
  status TEXT NOT NULL,
  kind TEXT,
  target_folder TEXT,
  temp_dir TEXT NOT NULL,
  total INTEGER DEFAULT 0,
  done INTEGER DEFAULT 0,
  failed INTEGER DEFAULT 0,
  error TEXT,
  failures TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


def _now():
    return datetime.utcnow().isoformat()


class TaskStore:
    def __init__(self, db_path):
        self.db_path = db_path
        d = os.path.dirname(db_path)
        if d:
            os.makedirs(d, exist_ok=True)
        conn = self._conn()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()

    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def create_task(self, account, requester, target_folder, temp_dir):
        tid = uuid.uuid4().hex
        ts = _now()
        conn = self._conn()
        try:
            conn.execute(
                "INSERT INTO tasks (id, account, requester, status, "
                "target_folder, temp_dir, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (tid, account, requester, "queued", target_folder,
                 temp_dir, ts, ts))
            conn.commit()
        finally:
            conn.close()
        return tid

    def get_task(self, task_id):
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM tasks WHERE id=?",
                               (task_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def list_tasks(self, requester):
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE requester=? "
                "ORDER BY created_at DESC", (requester,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def claim_next(self):
        conn = self._conn()
        conn.isolation_level = None
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM tasks WHERE status='queued' "
                "ORDER BY created_at LIMIT 1").fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None
            conn.execute("UPDATE tasks SET status='running', updated_at=? "
                         "WHERE id=?", (_now(), row["id"]))
            conn.execute("COMMIT")
            return dict(row)
        finally:
            conn.close()

    def set_totals(self, task_id, total):
        self._update(task_id, {"total": total})

    def update_progress(self, task_id, done, failed):
        self._update(task_id, {"done": done, "failed": failed})

    def set_failures(self, task_id, failures):
        self._update(task_id, {"failures": json.dumps(failures,
                                                      ensure_ascii=False)})

    def set_status(self, task_id, status, error=None, kind=None):
        fields = {"status": status}
        if error is not None:
            fields["error"] = error
        if kind is not None:
            fields["kind"] = kind
        self._update(task_id, fields)

    def count_active(self):
        conn = self._conn()
        try:
            return conn.execute(
                "SELECT COUNT(*) FROM tasks "
                "WHERE status IN ('queued','running')").fetchone()[0]
        finally:
            conn.close()

    def recover_interrupted(self):
        conn = self._conn()
        try:
            conn.execute("UPDATE tasks SET status='interrupted', updated_at=? "
                         "WHERE status='running'", (_now(),))
            conn.commit()
        finally:
            conn.close()

    def _update(self, task_id, fields):
        fields = dict(fields)
        fields["updated_at"] = _now()
        cols = ", ".join("%s=?" % k for k in fields)
        conn = self._conn()
        try:
            conn.execute("UPDATE tasks SET %s WHERE id=?" % cols,
                         list(fields.values()) + [task_id])
            conn.commit()
        finally:
            conn.close()
