# Zimbra 数据导入页面 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个独立的 Web 工具,支持多 `.eml` 上传和大体积 `.tgz`(>5GB)上传,把邮件数据可靠地导入 Zimbra 账户,从根本上规避 `PaxHeader` 导入失败问题。

**Architecture:** 双进程 Python 应用部署在 Zimbra 服务器本机:web 进程处理登录/分片上传/API,worker 进程消费 SQLite 任务队列、解包归一化并通过 Zimbra REST 注入邮件。两进程经 SQLite 解耦。注入认证用一个专用 Zimbra 管理员"服务账号"做委托认证。

**Tech Stack:** Python 3.6+、Flask(`<2.1` 兼容 CentOS 7)、requests、标准库 `tarfile`/`sqlite3`/`email`、pytest;前端原生 JS 单页。

设计依据见 `docs/superpowers/specs/2026-05-20-zimbra-import-page-design.md`。

---

## 文件结构

所有路径相对项目根目录 `zimbra-import/`。

| 文件 | 职责 |
|---|---|
| `requirements.txt` | 依赖声明 |
| `config.example.ini` | 配置模板 |
| `zimbra_import/__init__.py` | 包标记 |
| `zimbra_import/config.py` | 读取 ini 配置 |
| `zimbra_import/archive.py` | 解包 tgz、判别类型、归一化(核心) |
| `zimbra_import/store.py` | SQLite 任务队列与进度状态 |
| `zimbra_import/uploads.py` | 分片接收、断点续传、合并 |
| `zimbra_import/zimbra_auth.py` | SOAP 用户登录验证 + 服务账号委托认证 |
| `zimbra_import/zimbra_inject.py` | Zimbra REST 注入(eml 逐封 / tgz 整包) |
| `zimbra_import/worker.py` | 后台队列消费进程 |
| `zimbra_import/web.py` | Flask 应用:登录/上传/任务 API |
| `zimbra_import/static/index.html` | 单页前端 |
| `zimbra_import/static/app.js` | 前端逻辑:登录、分片上传、进度轮询 |
| `zimbra_import/static/style.css` | 样式 |
| `tests/test_*.py` | 单元/集成测试 |
| `deploy/zimbra-import-web.service` | web 进程 systemd 单元 |
| `deploy/zimbra-import-worker.service` | worker 进程 systemd 单元 |
| `deploy/README.md` | 部署说明 |

**共享约定(贯穿所有任务,务必一致):**

- 任务状态字符串:`queued` / `running` / `done` / `failed` / `interrupted`
- 归一化类型字符串:`eml-bundle` / `zimbra-export`
- `NormalizedInput` 具名元组字段:`kind`、`eml_paths`(list)、`repacked_tgz`(str 或 None)
- `Identity` 具名元组字段:`is_admin`(bool)、`account`(str)
- 时间戳统一用 UTC ISO 字符串(`datetime.utcnow().isoformat()`)

---

## Task 1: 项目脚手架与配置模块

**Files:**
- Create: `zimbra-import/requirements.txt`
- Create: `zimbra-import/config.example.ini`
- Create: `zimbra-import/zimbra_import/__init__.py`
- Create: `zimbra-import/zimbra_import/config.py`
- Create: `zimbra-import/tests/__init__.py`
- Test: `zimbra-import/tests/test_config.py`

- [ ] **Step 1: 初始化项目目录与 git**

```bash
mkdir -p zimbra-import/zimbra_import/static zimbra-import/tests zimbra-import/deploy
cd zimbra-import
git init
printf '%s\n' '__pycache__/' '*.pyc' '.pytest_cache/' 'venv/' '*.db' 'tmp/' > .gitignore
touch zimbra_import/__init__.py tests/__init__.py
```

- [ ] **Step 2: 写依赖与配置模板**

`requirements.txt`:
```
Flask>=1.1,<2.1
requests>=2.20
pytest>=6.0
```

`config.example.ini`:
```ini
[server]
listen_host = 127.0.0.1
listen_port = 8088
secret_key = CHANGE-ME-TO-RANDOM-STRING

[zimbra]
soap_url = https://mail.msauto.com.cn:8443/service/soap
admin_soap_url = https://mail.msauto.com.cn:7071/service/admin/soap
rest_base = https://mail.msauto.com.cn:8443
verify_tls = true

[service_account]
name = importsvc@msauto.com.cn
password = CHANGE-ME

[storage]
temp_root = /var/lib/zimbra-import/tmp
db_path = /var/lib/zimbra-import/tasks.db
max_task_bytes = 10737418240
retention_days = 7

[scheduler]
concurrency = 1
queue_limit = 50

[upload]
chunk_size = 10485760
```

> 注:`soap_url` 等用主机名 `mail.msauto.com.cn`(经 `/etc/hosts` 解析到本机 `192.168.31.175`),使 TLS 证书 CN 匹配,`verify_tls` 可设 true。

- [ ] **Step 3: 写失败测试**

`tests/test_config.py`:
```python
import textwrap
from zimbra_import.config import Config


def test_config_loads_all_fields(tmp_path):
    ini = tmp_path / "c.ini"
    ini.write_text(textwrap.dedent("""
        [server]
        listen_host = 127.0.0.1
        listen_port = 9000
        secret_key = abc
        [zimbra]
        soap_url = https://h/service/soap
        admin_soap_url = https://h:7071/service/admin/soap
        rest_base = https://h
        verify_tls = false
        [service_account]
        name = svc@d
        password = pw
        [storage]
        temp_root = /t
        db_path = /t/x.db
        max_task_bytes = 123
        retention_days = 5
        [scheduler]
        concurrency = 1
        queue_limit = 10
        [upload]
        chunk_size = 4096
    """))
    cfg = Config(str(ini))
    assert cfg.listen_port == 9000
    assert cfg.verify_tls is False
    assert cfg.svc_name == "svc@d"
    assert cfg.max_task_bytes == 123
    assert cfg.chunk_size == 4096
```

- [ ] **Step 4: 运行测试确认失败**

Run: `cd zimbra-import && python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'zimbra_import.config'`

- [ ] **Step 5: 实现 config.py**

`zimbra_import/config.py`:
```python
import configparser


class Config:
    def __init__(self, path):
        cp = configparser.ConfigParser()
        if not cp.read(path):
            raise FileNotFoundError("config not found: %s" % path)
        self.listen_host = cp.get("server", "listen_host", fallback="127.0.0.1")
        self.listen_port = cp.getint("server", "listen_port", fallback=8088)
        self.secret_key = cp.get("server", "secret_key")
        self.soap_url = cp.get("zimbra", "soap_url")
        self.admin_soap_url = cp.get("zimbra", "admin_soap_url")
        self.rest_base = cp.get("zimbra", "rest_base").rstrip("/")
        self.verify_tls = cp.getboolean("zimbra", "verify_tls", fallback=True)
        self.svc_name = cp.get("service_account", "name")
        self.svc_password = cp.get("service_account", "password")
        self.temp_root = cp.get("storage", "temp_root")
        self.db_path = cp.get("storage", "db_path")
        self.max_task_bytes = cp.getint("storage", "max_task_bytes",
                                        fallback=10 * 1024 ** 3)
        self.retention_days = cp.getint("storage", "retention_days", fallback=7)
        self.concurrency = cp.getint("scheduler", "concurrency", fallback=1)
        self.queue_limit = cp.getint("scheduler", "queue_limit", fallback=50)
        self.chunk_size = cp.getint("upload", "chunk_size", fallback=10 * 1024 * 1024)
```

- [ ] **Step 6: 运行测试确认通过**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add -A
git commit -m "chore: project scaffold and config module"
```

---

## Task 2: archive.py — 安全解包 tgz

**Files:**
- Create: `zimbra-import/zimbra_import/archive.py`
- Test: `zimbra-import/tests/test_archive.py`

- [ ] **Step 1: 写失败测试**

`tests/test_archive.py`:
```python
import os
import tarfile
import pytest
from zimbra_import import archive


def _make_tgz(path, files, fmt=tarfile.PAX_FORMAT):
    """files: dict of arcname -> bytes content."""
    with tarfile.open(path, "w:gz", format=fmt) as tar:
        for arcname, content in files.items():
            data = content
            import io
            info = tarfile.TarInfo(name=arcname)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def test_unpack_pax_archive(tmp_path):
    tgz = tmp_path / "a.tgz"
    longname = "Re_ " + "入出库通知" * 6 + ".eml"  # >100 bytes, non-ASCII
    _make_tgz(str(tgz), {longname: b"From: a@b\r\n\r\nhi"})
    dest = tmp_path / "out"
    archive.unpack_tgz(str(tgz), str(dest))
    assert (dest / longname).read_bytes() == b"From: a@b\r\n\r\nhi"


def test_unpack_rejects_path_traversal(tmp_path):
    tgz = tmp_path / "evil.tgz"
    _make_tgz(str(tgz), {"../escape.eml": b"x"})
    with pytest.raises(ValueError):
        archive.unpack_tgz(str(tgz), str(tmp_path / "out2"))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_archive.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'zimbra_import.archive'`

- [ ] **Step 3: 实现 unpack_tgz**

`zimbra_import/archive.py`:
```python
import os
import tarfile


def _safe_members(tar, dest):
    dest = os.path.realpath(dest)
    members = tar.getmembers()
    for m in members:
        target = os.path.realpath(os.path.join(dest, m.name))
        if target != dest and not target.startswith(dest + os.sep):
            raise ValueError("unsafe path in archive: %s" % m.name)
    return members


def unpack_tgz(tgz_path, dest_dir):
    """Extract a .tgz to dest_dir. Handles pax/gnu formats. Rejects path traversal."""
    os.makedirs(dest_dir, exist_ok=True)
    with tarfile.open(tgz_path, "r:*") as tar:
        members = _safe_members(tar, dest_dir)
        tar.extractall(dest_dir, members=members)
    return dest_dir
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_archive.py -v`
Expected: PASS(2 passed)

- [ ] **Step 5: 提交**

```bash
git add -A && git commit -m "feat: safe tgz extraction with path-traversal guard"
```

---

## Task 3: archive.py — 判别归档类型

**Files:**
- Modify: `zimbra-import/zimbra_import/archive.py`
- Test: `zimbra-import/tests/test_archive.py`

- [ ] **Step 1: 追加失败测试**

在 `tests/test_archive.py` 末尾追加:
```python
def test_detect_eml_bundle(tmp_path):
    d = tmp_path / "b1"
    d.mkdir()
    (d / "1.eml").write_bytes(b"x")
    (d / "2.eml").write_bytes(b"y")
    assert archive.detect_kind(str(d)) == "eml-bundle"


def test_detect_zimbra_export(tmp_path):
    d = tmp_path / "b2"
    sub = d / "Inbox"
    sub.mkdir(parents=True)
    (sub / "100").write_bytes(b"msg")
    (sub / "100.meta").write_bytes(b"<meta/>")
    assert archive.detect_kind(str(d)) == "zimbra-export"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_archive.py -k detect -v`
Expected: FAIL — `AttributeError: module 'zimbra_import.archive' has no attribute 'detect_kind'`

- [ ] **Step 3: 实现 detect_kind**

在 `archive.py` 追加:
```python
def detect_kind(extracted_dir):
    """Zimbra 完整导出 tgz 的每个条目都带一个 .meta 旁挂文件;
    据此区分 'zimbra-export' 与纯 'eml-bundle'。"""
    for root, dirs, files in os.walk(extracted_dir):
        for f in files:
            if f.endswith(".meta"):
                return "zimbra-export"
    return "eml-bundle"
```

> 集成测试(Task 17)会用真实 Zimbra 导出验证此判别;若真实导出不使用 `.meta` 旁挂文件,在那里据实修正。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_archive.py -k detect -v`
Expected: PASS(2 passed)

- [ ] **Step 5: 提交**

```bash
git add -A && git commit -m "feat: detect eml-bundle vs zimbra-export archive"
```

---

## Task 4: archive.py — 归一化

**Files:**
- Modify: `zimbra-import/zimbra_import/archive.py`
- Test: `zimbra-import/tests/test_archive.py`

- [ ] **Step 1: 追加失败测试**

在 `tests/test_archive.py` 末尾追加:
```python
def test_normalize_eml_bundle_from_pax_tgz(tmp_path):
    """回归:用长中文名 eml 打的 pax 包,归一化后应得到可读 eml 列表。"""
    inp = tmp_path / "input"
    inp.mkdir()
    longname = "Re_ " + "入出库通知采购" * 6 + ".eml"
    _make_tgz(str(inp / "bundle.tgz"), {longname: b"From: a@b\r\n\r\nbody"})
    work = tmp_path / "work"
    work.mkdir()
    result = archive.normalize(str(inp), str(work))
    assert result.kind == "eml-bundle"
    assert len(result.eml_paths) == 1
    assert open(result.eml_paths[0], "rb").read() == b"From: a@b\r\n\r\nbody"
    assert result.repacked_tgz is None


def test_normalize_loose_eml_files(tmp_path):
    inp = tmp_path / "input2"
    inp.mkdir()
    (inp / "m1.eml").write_bytes(b"a")
    (inp / "m2.eml").write_bytes(b"b")
    work = tmp_path / "work2"
    work.mkdir()
    result = archive.normalize(str(inp), str(work))
    assert result.kind == "eml-bundle"
    assert len(result.eml_paths) == 2


def test_normalize_zimbra_export_repacks_clean(tmp_path):
    inp = tmp_path / "input3"
    inp.mkdir()
    src = tmp_path / "src"
    (src / "Inbox").mkdir(parents=True)
    (src / "Inbox" / "100").write_bytes(b"msg")
    (src / "Inbox" / "100.meta").write_bytes(b"<meta/>")
    import tarfile as _t
    with _t.open(str(inp / "export.tgz"), "w:gz", format=_t.PAX_FORMAT) as tar:
        tar.add(str(src), arcname=".")
    work = tmp_path / "work3"
    work.mkdir()
    result = archive.normalize(str(inp), str(work))
    assert result.kind == "zimbra-export"
    assert result.repacked_tgz and os.path.exists(result.repacked_tgz)
    # 重打包后不含 pax 扩展头
    raw = open(result.repacked_tgz, "rb").read()
    import gzip
    assert b"PaxHeader" not in gzip.decompress(raw)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_archive.py -k normalize -v`
Expected: FAIL — `AttributeError: ... has no attribute 'normalize'`

- [ ] **Step 3: 实现 normalize**

在 `archive.py` 顶部 import 区追加 `import collections`,然后追加:
```python
NormalizedInput = collections.namedtuple(
    "NormalizedInput", ["kind", "eml_paths", "repacked_tgz"])


def _collect_emls(directory):
    out = []
    for root, dirs, files in os.walk(directory):
        for f in sorted(files):
            if f.lower().endswith(".eml"):
                out.append(os.path.join(root, f))
    return out


def _repack_clean(src_dir, dest_tgz):
    """重新打包成 GNU 格式 tgz(无 pax 扩展头,长名用 @LongLink)。"""
    entries = []
    for root, dirs, files in os.walk(src_dir):
        for f in sorted(files):
            full = os.path.join(root, f)
            entries.append((full, os.path.relpath(full, src_dir)))
    entries.sort(key=lambda x: x[1])
    with tarfile.open(dest_tgz, "w:gz", format=tarfile.GNU_FORMAT) as tar:
        for full, arc in entries:
            tar.add(full, arcname=arc, recursive=False)
    return dest_tgz


def normalize(input_dir, work_dir):
    """把任务输入目录归一化。input_dir 内或是一个 .tgz,或是若干 .eml。"""
    os.makedirs(work_dir, exist_ok=True)
    entries = sorted(os.listdir(input_dir))
    tgzs = [e for e in entries if e.endswith((".tgz", ".tar.gz"))]
    if tgzs:
        extracted = os.path.join(work_dir, "extracted")
        unpack_tgz(os.path.join(input_dir, tgzs[0]), extracted)
        kind = detect_kind(extracted)
        if kind == "zimbra-export":
            repacked = os.path.join(work_dir, "clean.tgz")
            _repack_clean(extracted, repacked)
            return NormalizedInput("zimbra-export", [], repacked)
        return NormalizedInput("eml-bundle", _collect_emls(extracted), None)
    emls = [os.path.join(input_dir, e) for e in entries
            if e.lower().endswith(".eml")]
    return NormalizedInput("eml-bundle", emls, None)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_archive.py -v`
Expected: PASS(全部 7 项)

- [ ] **Step 5: 提交**

```bash
git add -A && git commit -m "feat: normalize archives, repack zimbra-export without pax headers"
```

---

## Task 5: store.py — 任务表与创建/查询

**Files:**
- Create: `zimbra-import/zimbra_import/store.py`
- Test: `zimbra-import/tests/test_store.py`

- [ ] **Step 1: 写失败测试**

`tests/test_store.py`:
```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'zimbra_import.store'`

- [ ] **Step 3: 实现 store.py(建表 + 创建/查询)**

`zimbra_import/store.py`:
```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_store.py -v`
Expected: PASS(2 passed)

- [ ] **Step 5: 提交**

```bash
git add -A && git commit -m "feat: SQLite task store with create/get/list"
```

---

## Task 6: store.py — 调度与进度更新

**Files:**
- Modify: `zimbra-import/zimbra_import/store.py`
- Test: `zimbra-import/tests/test_store.py`

- [ ] **Step 1: 追加失败测试**

在 `tests/test_store.py` 末尾追加:
```python
def test_claim_next_is_fifo_and_marks_running(tmp_path):
    store = TaskStore(str(tmp_path / "c.db"))
    t1 = store.create_task("a@d", "a@d", "Inbox", "/tmp/a")
    t2 = store.create_task("b@d", "b@d", "Inbox", "/tmp/b")
    claimed = store.claim_next()
    assert claimed["id"] == t1
    assert store.get_task(t1)["status"] == "running"
    assert store.claim_next()["id"] == t2
    assert store.claim_next() is None


def test_progress_and_status_updates(tmp_path):
    store = TaskStore(str(tmp_path / "p.db"))
    tid = store.create_task("a@d", "a@d", "Inbox", "/tmp/a")
    store.set_totals(tid, 10)
    store.update_progress(tid, done=4, failed=1)
    store.set_failures(tid, [{"name": "x.eml", "reason": "bad"}])
    store.set_status(tid, "done")
    task = store.get_task(tid)
    assert task["total"] == 10 and task["done"] == 4 and task["failed"] == 1
    assert task["status"] == "done"
    import json
    assert json.loads(task["failures"])[0]["name"] == "x.eml"


def test_count_active_and_recover_interrupted(tmp_path):
    store = TaskStore(str(tmp_path / "r.db"))
    t1 = store.create_task("a@d", "a@d", "Inbox", "/tmp/a")
    store.create_task("b@d", "b@d", "Inbox", "/tmp/b")
    assert store.count_active() == 2
    store.claim_next()  # t1 -> running
    store.recover_interrupted()  # running -> interrupted
    assert store.get_task(t1)["status"] == "interrupted"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_store.py -k "claim or progress or recover" -v`
Expected: FAIL — `AttributeError: 'TaskStore' object has no attribute 'claim_next'`

- [ ] **Step 3: 实现调度方法**

在 `store.py` 的 `TaskStore` 类末尾追加方法:
```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_store.py -v`
Expected: PASS(全部 5 项)

- [ ] **Step 5: 提交**

```bash
git add -A && git commit -m "feat: task scheduling, progress updates, crash recovery"
```

---

## Task 7: uploads.py — 分片接收与合并

**Files:**
- Create: `zimbra-import/zimbra_import/uploads.py`
- Test: `zimbra-import/tests/test_uploads.py`

- [ ] **Step 1: 写失败测试**

`tests/test_uploads.py`:
```python
from zimbra_import import uploads


def test_chunk_save_resume_and_merge(tmp_path):
    root = str(tmp_path)
    uid = uploads.new_upload(root)
    # 乱序保存分片 2,0(故意漏 1)
    uploads.save_chunk(root, uid, 0, 2, b"CCC")
    uploads.save_chunk(root, uid, 0, 0, b"AAA")
    missing = uploads.missing_chunks(root, uid, 0, total_chunks=3)
    assert missing == [1]
    # 补上漏掉的分片
    uploads.save_chunk(root, uid, 0, 1, b"BBB")
    assert uploads.missing_chunks(root, uid, 0, total_chunks=3) == []
    dest = uploads.merge_file(root, uid, 0, total_chunks=3,
                              filename="big.tgz")
    assert open(dest, "rb").read() == b"AAABBBCCC"


def test_merge_rejects_when_chunk_missing(tmp_path):
    root = str(tmp_path)
    uid = uploads.new_upload(root)
    uploads.save_chunk(root, uid, 0, 0, b"AAA")
    import pytest
    with pytest.raises(ValueError):
        uploads.merge_file(root, uid, 0, total_chunks=2, filename="x.tgz")


def test_filename_sanitized_on_merge(tmp_path):
    root = str(tmp_path)
    uid = uploads.new_upload(root)
    uploads.save_chunk(root, uid, 0, 0, b"data")
    dest = uploads.merge_file(root, uid, 0, total_chunks=1,
                              filename="../../etc/passwd")
    # 合并后的文件必须落在该上传的 input 目录内
    assert uploads.upload_dir(root, uid) in dest
    assert "passwd" in dest and ".." not in dest.split(uid)[1]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_uploads.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'zimbra_import.uploads'`

- [ ] **Step 3: 实现 uploads.py**

`zimbra_import/uploads.py`:
```python
import os
import uuid


def new_upload(temp_root):
    uid = uuid.uuid4().hex
    os.makedirs(os.path.join(temp_root, "uploads", uid, "input"))
    return uid


def upload_dir(temp_root, upload_id):
    return os.path.join(temp_root, "uploads", upload_id)


def _chunk_dir(temp_root, upload_id, file_index):
    return os.path.join(upload_dir(temp_root, upload_id), "chunks",
                        str(file_index))


def input_dir(temp_root, upload_id):
    return os.path.join(upload_dir(temp_root, upload_id), "input")


def save_chunk(temp_root, upload_id, file_index, chunk_index, data):
    d = _chunk_dir(temp_root, upload_id, file_index)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, str(chunk_index)), "wb") as fh:
        fh.write(data)


def missing_chunks(temp_root, upload_id, file_index, total_chunks):
    d = _chunk_dir(temp_root, upload_id, file_index)
    have = set(os.listdir(d)) if os.path.isdir(d) else set()
    return [i for i in range(total_chunks) if str(i) not in have]


def _safe_name(filename):
    return os.path.basename(filename.replace("\\", "/")) or "upload.bin"


def merge_file(temp_root, upload_id, file_index, total_chunks, filename):
    missing = missing_chunks(temp_root, upload_id, file_index, total_chunks)
    if missing:
        raise ValueError("missing chunks: %s" % missing)
    d = _chunk_dir(temp_root, upload_id, file_index)
    dest = os.path.join(input_dir(temp_root, upload_id), _safe_name(filename))
    with open(dest, "wb") as out:
        for i in range(total_chunks):
            with open(os.path.join(d, str(i)), "rb") as part:
                out.write(part.read())
    return dest
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_uploads.py -v`
Expected: PASS(3 passed)

- [ ] **Step 5: 提交**

```bash
git add -A && git commit -m "feat: chunked upload receive, resume and merge"
```

---

## Task 8: zimbra_auth.py — 用户登录验证

**Files:**
- Create: `zimbra-import/zimbra_import/zimbra_auth.py`
- Test: `zimbra-import/tests/test_zimbra_auth.py`

- [ ] **Step 1: 写失败测试**

`tests/test_zimbra_auth.py`:
```python
import pytest
from zimbra_import import zimbra_auth


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _Cfg:
    soap_url = "https://h:8443/service/soap"
    admin_soap_url = "https://h:7071/service/admin/soap"
    verify_tls = False
    svc_name = "svc@d"
    svc_password = "svcpw"


def _fault():
    return {"Body": {"Fault": {"Reason": {"Text": "auth failed"}}}}


def _admin_ok():
    return {"Body": {"AuthResponse": {"authToken": [{"_content": "ADMTOK"}]}}}


def _account_ok():
    return {"Body": {"AuthResponse": {"authToken": [{"_content": "USRTOK"}]}}}


def test_login_admin(monkeypatch):
    def fake_post(url, **kw):
        return _Resp(_admin_ok())  # admin 端点直接成功
    monkeypatch.setattr(zimbra_auth.requests, "post", fake_post)
    ident = zimbra_auth.login(_Cfg, "admin@d", "pw")
    assert ident.is_admin is True
    assert ident.account == "admin@d"


def test_login_normal_user(monkeypatch):
    def fake_post(url, **kw):
        if "7071" in url:
            return _Resp(_fault())      # admin 登录失败
        return _Resp(_account_ok())     # account 登录成功
    monkeypatch.setattr(zimbra_auth.requests, "post", fake_post)
    ident = zimbra_auth.login(_Cfg, "user@d", "pw")
    assert ident.is_admin is False
    assert ident.account == "user@d"


def test_login_bad_credentials(monkeypatch):
    def fake_post(url, **kw):
        return _Resp(_fault())
    monkeypatch.setattr(zimbra_auth.requests, "post", fake_post)
    with pytest.raises(zimbra_auth.AuthError):
        zimbra_auth.login(_Cfg, "user@d", "wrong")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_zimbra_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'zimbra_import.zimbra_auth'`

- [ ] **Step 3: 实现 login**

`zimbra_import/zimbra_auth.py`:
```python
import collections
import requests

Identity = collections.namedtuple("Identity", ["is_admin", "account"])


class AuthError(Exception):
    pass


def _soap(url, body, verify, header=None):
    payload = {"Body": body}
    if header:
        payload["Header"] = header
    r = requests.post(url, json=payload, verify=verify, timeout=30)
    data = r.json()
    inner = data.get("Body", {})
    if "Fault" in inner:
        raise AuthError(inner["Fault"]["Reason"]["Text"])
    return inner


def login(cfg, username, password):
    """admin 端口能登录成功即视为管理员;否则尝试普通账户登录。"""
    admin_body = {"AuthRequest": {"_jsns": "urn:zimbraAdmin",
                                  "name": username, "password": password}}
    try:
        _soap(cfg.admin_soap_url, admin_body, cfg.verify_tls)
        return Identity(is_admin=True, account=username)
    except AuthError:
        pass
    acct_body = {"AuthRequest": {
        "_jsns": "urn:zimbraAccount",
        "account": {"by": "name", "_content": username},
        "password": {"_content": password}}}
    try:
        _soap(cfg.soap_url, acct_body, cfg.verify_tls)
    except AuthError:
        raise AuthError("登录失败:账号或密码错误")
    return Identity(is_admin=False, account=username)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_zimbra_auth.py -v`
Expected: PASS(3 passed)

- [ ] **Step 5: 提交**

```bash
git add -A && git commit -m "feat: Zimbra SOAP user login with admin detection"
```

---

## Task 9: zimbra_auth.py — 服务账号委托认证

**Files:**
- Modify: `zimbra-import/zimbra_import/zimbra_auth.py`
- Test: `zimbra-import/tests/test_zimbra_auth.py`

- [ ] **Step 1: 追加失败测试**

在 `tests/test_zimbra_auth.py` 末尾追加:
```python
def test_delegate_token(monkeypatch):
    calls = []

    def fake_post(url, **kw):
        calls.append(kw.get("json"))
        body = kw["json"]["Body"]
        if "AuthRequest" in body:
            return _Resp(_admin_ok())
        if "DelegateAuthRequest" in body:
            return _Resp({"Body": {"DelegateAuthResponse": {
                "authToken": [{"_content": "DELEGTOK"}]}}})
        return _Resp(_fault())

    monkeypatch.setattr(zimbra_auth.requests, "post", fake_post)
    tok = zimbra_auth.delegate_token(_Cfg, "target@d")
    assert tok == "DELEGTOK"
    # 第二次调用必须带上 admin token 的 Header
    assert calls[1]["Header"]["context"]["authToken"]["_content"] == "ADMTOK"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_zimbra_auth.py -k delegate -v`
Expected: FAIL — `AttributeError: ... has no attribute 'delegate_token'`

- [ ] **Step 3: 实现 delegate_token**

在 `zimbra_auth.py` 末尾追加:
```python
def _admin_token(cfg):
    body = {"AuthRequest": {"_jsns": "urn:zimbraAdmin",
                            "name": cfg.svc_name,
                            "password": cfg.svc_password}}
    resp = _soap(cfg.admin_soap_url, body, cfg.verify_tls)
    return resp["AuthResponse"]["authToken"][0]["_content"]


def delegate_token(cfg, target_account):
    """用服务账号取得目标账户的委托 token。worker 注入前即时调用。"""
    admin_tok = _admin_token(cfg)
    header = {"context": {"_jsns": "urn:zimbra",
                          "authToken": {"_content": admin_tok}}}
    body = {"DelegateAuthRequest": {
        "_jsns": "urn:zimbraAdmin",
        "account": {"by": "name", "_content": target_account}}}
    resp = _soap(cfg.admin_soap_url, body, cfg.verify_tls, header=header)
    return resp["DelegateAuthResponse"]["authToken"][0]["_content"]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_zimbra_auth.py -v`
Expected: PASS(4 passed)

- [ ] **Step 5: 提交**

```bash
git add -A && git commit -m "feat: service-account delegated auth for injection"
```

---

## Task 10: zimbra_inject.py — REST 注入

**Files:**
- Create: `zimbra-import/zimbra_import/zimbra_inject.py`
- Test: `zimbra-import/tests/test_zimbra_inject.py`

- [ ] **Step 1: 写失败测试**

`tests/test_zimbra_inject.py`:
```python
import pytest
from zimbra_import import zimbra_inject


class _Cfg:
    rest_base = "https://h:8443"
    verify_tls = False


class _Resp:
    def __init__(self, status):
        self.status_code = status
        self.text = "err" if status >= 300 else "ok"


def test_inject_eml_builds_correct_request(tmp_path, monkeypatch):
    eml = tmp_path / "m.eml"
    eml.write_bytes(b"From: a@b\r\n\r\nhello")
    captured = {}

    def fake_post(url, **kw):
        captured["url"] = url
        captured["params"] = kw.get("params")
        captured["cookies"] = kw.get("cookies")
        captured["data"] = kw.get("data")
        return _Resp(200)

    monkeypatch.setattr(zimbra_inject.requests, "post", fake_post)
    zimbra_inject.inject_eml(_Cfg, "u@d", "Inbox", "TOK", str(eml))
    assert captured["url"] == "https://h:8443/home/u@d/Inbox"
    assert captured["params"]["fmt"] == "eml"
    assert captured["cookies"]["ZM_AUTH_TOKEN"] == "TOK"
    assert captured["data"] == b"From: a@b\r\n\r\nhello"


def test_inject_eml_raises_on_http_error(tmp_path, monkeypatch):
    eml = tmp_path / "m.eml"
    eml.write_bytes(b"x")
    monkeypatch.setattr(zimbra_inject.requests, "post",
                        lambda url, **kw: _Resp(500))
    with pytest.raises(zimbra_inject.InjectError):
        zimbra_inject.inject_eml(_Cfg, "u@d", "Inbox", "TOK", str(eml))


def test_inject_tgz_builds_correct_request(tmp_path, monkeypatch):
    tgz = tmp_path / "a.tgz"
    tgz.write_bytes(b"TGZDATA")
    captured = {}

    def fake_post(url, **kw):
        captured["url"] = url
        captured["params"] = kw.get("params")
        return _Resp(200)

    monkeypatch.setattr(zimbra_inject.requests, "post", fake_post)
    zimbra_inject.inject_tgz(_Cfg, "u@d", "TOK", str(tgz))
    assert captured["url"] == "https://h:8443/home/u@d/"
    assert captured["params"]["fmt"] == "tgz"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_zimbra_inject.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'zimbra_import.zimbra_inject'`

- [ ] **Step 3: 实现 zimbra_inject.py**

`zimbra_import/zimbra_inject.py`:
```python
import requests


class InjectError(Exception):
    pass


def inject_eml(cfg, account, folder, token, eml_path):
    url = "%s/home/%s/%s" % (cfg.rest_base, account, folder.strip("/"))
    with open(eml_path, "rb") as fh:
        data = fh.read()
    r = requests.post(url, params={"fmt": "eml"}, data=data,
                      cookies={"ZM_AUTH_TOKEN": token},
                      headers={"Content-Type": "message/rfc822"},
                      verify=cfg.verify_tls, timeout=120)
    if r.status_code >= 300:
        raise InjectError("HTTP %s: %s" % (r.status_code, r.text[:200]))


def inject_tgz(cfg, account, token, tgz_path):
    url = "%s/home/%s/" % (cfg.rest_base, account)
    with open(tgz_path, "rb") as fh:
        r = requests.post(url, params={"fmt": "tgz", "resolve": "skip"},
                          data=fh, cookies={"ZM_AUTH_TOKEN": token},
                          verify=cfg.verify_tls, timeout=3600)
    if r.status_code >= 300:
        raise InjectError("HTTP %s: %s" % (r.status_code, r.text[:200]))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_zimbra_inject.py -v`
Expected: PASS(3 passed)

- [ ] **Step 5: 提交**

```bash
git add -A && git commit -m "feat: Zimbra REST injection for eml and tgz"
```

---

## Task 11: worker.py — 后台任务处理

**Files:**
- Create: `zimbra-import/zimbra_import/worker.py`
- Test: `zimbra-import/tests/test_worker.py`

- [ ] **Step 1: 写失败测试**

`tests/test_worker.py`:
```python
import os
from zimbra_import import worker, archive
from zimbra_import.store import TaskStore


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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_worker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'zimbra_import.worker'`

- [ ] **Step 3: 实现 worker.py**

`zimbra_import/worker.py`:
```python
import os
import sys
import time
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
    except Exception as exc:  # noqa: BLE001 - 顶层兜底,任何失败都记录
        store.set_status(tid, "failed", error=str(exc))


def _loop(cfg, store):
    while True:
        task = store.claim_next()
        if task is None:
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_worker.py -v`
Expected: PASS(3 passed)

- [ ] **Step 5: 提交**

```bash
git add -A && git commit -m "feat: background worker processing tasks from queue"
```

---

## Task 12: web.py — Flask 应用与登录

**Files:**
- Create: `zimbra-import/zimbra_import/web.py`
- Test: `zimbra-import/tests/test_web.py`

- [ ] **Step 1: 写失败测试**

`tests/test_web.py`:
```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_web.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'zimbra_import.web'`

- [ ] **Step 3: 实现 web.py(应用工厂 + 登录 + 会话守卫)**

`zimbra_import/web.py`:
```python
import os
import functools

from flask import Flask, request, session, jsonify, send_from_directory

from zimbra_import import zimbra_auth, uploads, archive
from zimbra_import.store import TaskStore

_STATIC = os.path.join(os.path.dirname(__file__), "static")


def create_app(cfg):
    app = Flask(__name__, static_folder=None)
    app.secret_key = cfg.secret_key
    app.config["MAX_CONTENT_LENGTH"] = None  # 分片自身不大,不限总量
    store = TaskStore(cfg.db_path)
    os.makedirs(cfg.temp_root, exist_ok=True)

    def login_required(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            if "account" not in session:
                return jsonify({"error": "未登录"}), 401
            return fn(*a, **kw)
        return wrapper

    @app.route("/")
    def index():
        return send_from_directory(_STATIC, "index.html")

    @app.route("/static/<path:name>")
    def static_files(name):
        return send_from_directory(_STATIC, name)

    @app.route("/api/login", methods=["POST"])
    def login():
        body = request.get_json(force=True, silent=True) or {}
        username = body.get("username", "")
        password = body.get("password", "")
        try:
            ident = zimbra_auth.login(cfg, username, password)
        except zimbra_auth.AuthError as exc:
            return jsonify({"error": str(exc)}), 401
        session["account"] = ident.account
        session["is_admin"] = ident.is_admin
        return jsonify({"account": ident.account,
                        "is_admin": ident.is_admin})

    @app.route("/api/logout", methods=["POST"])
    def logout():
        session.clear()
        return jsonify({"ok": True})

    @app.route("/api/tasks")
    @login_required
    def list_tasks():
        return jsonify(store.list_tasks(session["account"]))

    @app.route("/api/tasks/<task_id>")
    @login_required
    def get_task(task_id):
        task = store.get_task(task_id)
        if task is None or task["requester"] != session["account"]:
            return jsonify({"error": "任务不存在"}), 404
        return jsonify(task)

    # 上传与导入端点在 Task 13 / 14 注册
    _register_uploads(app, cfg, store, login_required)
    _register_import(app, cfg, store, login_required)
    return app


def _register_uploads(app, cfg, store, login_required):
    pass  # Task 13 实现


def _register_import(app, cfg, store, login_required):
    pass  # Task 14 实现
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_web.py -v`
Expected: PASS(3 passed)

- [ ] **Step 5: 提交**

```bash
git add -A && git commit -m "feat: Flask app factory, login and session guard"
```

---

## Task 13: web.py — 上传端点

**Files:**
- Modify: `zimbra-import/zimbra_import/web.py`
- Test: `zimbra-import/tests/test_web.py`

- [ ] **Step 1: 追加失败测试**

在 `tests/test_web.py` 末尾追加:
```python
import io


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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_web.py -k upload -v`
Expected: FAIL — 404(端点未注册)

- [ ] **Step 3: 实现 _register_uploads**

替换 `web.py` 中的 `_register_uploads` 函数体:
```python
def _register_uploads(app, cfg, store, login_required):
    @app.route("/api/upload/init", methods=["POST"])
    @login_required
    def upload_init():
        upload_id = uploads.new_upload(cfg.temp_root)
        return jsonify({"upload_id": upload_id})

    @app.route("/api/upload/chunk", methods=["POST"])
    @login_required
    def upload_chunk():
        upload_id = request.form["upload_id"]
        file_index = int(request.form["file_index"])
        chunk_index = int(request.form["chunk_index"])
        blob = request.files["blob"].read()
        uploads.save_chunk(cfg.temp_root, upload_id, file_index,
                           chunk_index, blob)
        return jsonify({"ok": True})

    @app.route("/api/upload/status")
    @login_required
    def upload_status():
        upload_id = request.args["upload_id"]
        file_index = int(request.args["file_index"])
        total = int(request.args["total_chunks"])
        missing = uploads.missing_chunks(cfg.temp_root, upload_id,
                                         file_index, total)
        return jsonify({"missing": missing})
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_web.py -v`
Expected: PASS(全部 5 项)

- [ ] **Step 5: 提交**

```bash
git add -A && git commit -m "feat: chunked upload endpoints with resume support"
```

---

## Task 14: web.py — 导入入队与任务查询

**Files:**
- Modify: `zimbra-import/zimbra_import/web.py`
- Test: `zimbra-import/tests/test_web.py`

- [ ] **Step 1: 追加失败测试**

在 `tests/test_web.py` 末尾追加:
```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_web.py -k "import or queue or target" -v`
Expected: FAIL — 404 / `AttributeError: module 'web' has no attribute '_queue_limit_for'`

- [ ] **Step 3: 实现导入端点**

在 `web.py` 顶部 import 区追加 `import shutil`,然后替换 `_register_import` 函数体,并在其上方新增 `_queue_limit_for`:
```python
def _queue_limit_for(store, cfg):
    """返回当前还能接受的队列余量(供测试 monkeypatch)。"""
    return cfg.queue_limit - store.count_active()


def _register_import(app, cfg, store, login_required):
    @app.route("/api/import", methods=["POST"])
    @login_required
    def start_import():
        if _queue_limit_for(store, cfg) <= 0:
            return jsonify({"error": "任务队列已满,请稍后再试"}), 429

        body = request.get_json(force=True, silent=True) or {}
        upload_id = body["upload_id"]
        files = body.get("files", [])
        folder = body.get("folder") or "Inbox"

        # 越权防护:管理员可指定目标账户,普通用户强制为本人
        account = session["account"]
        if session.get("is_admin") and body.get("account"):
            account = body["account"]

        # 合并每个文件的分片到该上传的 input 目录
        for f in files:
            uploads.merge_file(cfg.temp_root, upload_id, int(f["index"]),
                               int(f["chunks"]), f["name"])

        # 磁盘空间预检
        input_path = uploads.input_dir(cfg.temp_root, upload_id)
        used = sum(os.path.getsize(os.path.join(input_path, n))
                   for n in os.listdir(input_path))
        free = shutil.disk_usage(cfg.temp_root).free
        if used > cfg.max_task_bytes:
            return jsonify({"error": "本次数据超过单任务大小上限"}), 413
        if free < used:
            return jsonify({"error": "服务器临时磁盘空间不足"}), 507

        task_id = store.create_task(
            account=account, requester=session["account"],
            target_folder=folder,
            temp_dir=uploads.upload_dir(cfg.temp_root, upload_id))
        return jsonify({"task_id": task_id})
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_web.py -v`
Expected: PASS(全部 8 项)

- [ ] **Step 5: 提交**

```bash
git add -A && git commit -m "feat: import enqueue with auth enforcement and guards"
```

---

## Task 15: 前端单页

**Files:**
- Create: `zimbra-import/zimbra_import/static/index.html`
- Create: `zimbra-import/zimbra_import/static/app.js`
- Create: `zimbra-import/zimbra_import/static/style.css`

> 前端为浏览器单页,无单元测试框架;验证方式为 Step 4 的手动浏览器测试。

- [ ] **Step 1: 写 index.html**

`zimbra_import/static/index.html`:
```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Zimbra 数据导入</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <div id="login" class="card">
    <h2>Zimbra 数据导入</h2>
    <input id="username" placeholder="账号 (name@msauto.com.cn)">
    <input id="password" type="password" placeholder="密码">
    <button id="loginBtn">登录</button>
    <p id="loginErr" class="err"></p>
  </div>

  <div id="main" class="card hidden">
    <p>当前登录:<b id="who"></b> <button id="logoutBtn">退出</button></p>
    <div id="adminBox" class="hidden">
      <label>目标账户(管理员):<input id="targetAccount"
        placeholder="留空=导入到自己"></label>
    </div>
    <label>目标文件夹:<input id="folder" value="Inbox"></label>
    <label>选择文件(多个 .eml 或一个 .tgz):
      <input id="files" type="file" multiple accept=".eml,.tgz,.tar.gz">
    </label>
    <button id="startBtn">开始导入</button>
    <div id="uploadProgress"></div>

    <h3>我的任务</h3>
    <button id="refreshBtn">刷新</button>
    <table id="tasks"><thead><tr>
      <th>任务</th><th>账户</th><th>状态</th><th>进度</th><th>失败</th>
    </tr></thead><tbody></tbody></table>
  </div>

  <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: 写 style.css**

`zimbra_import/static/style.css`:
```css
body { font-family: sans-serif; max-width: 720px; margin: 40px auto;
       color: #222; }
.card { border: 1px solid #ddd; border-radius: 8px; padding: 24px;
        margin-bottom: 20px; }
.hidden { display: none; }
.err { color: #c00; }
input, button { font-size: 14px; padding: 6px 8px; margin: 4px 0; }
input[type=text], input[type=password], #username, #password,
#folder, #targetAccount { width: 280px; }
label { display: block; margin: 10px 0; }
table { width: 100%; border-collapse: collapse; margin-top: 10px; }
th, td { border: 1px solid #ddd; padding: 6px; font-size: 13px;
         text-align: left; }
.bar { background: #eee; border-radius: 4px; overflow: hidden; }
.bar > div { background: #3a7; height: 14px; }
```

- [ ] **Step 3: 写 app.js**

`zimbra_import/static/app.js`:
```javascript
const CHUNK = 10 * 1024 * 1024; // 10MB
let pollTimer = null;

function $(id) { return document.getElementById(id); }

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (r.status === 401) { showLogin(); throw new Error("未登录"); }
  return r;
}

function showLogin() {
  $("login").classList.remove("hidden");
  $("main").classList.add("hidden");
}

function showMain(account, isAdmin) {
  $("login").classList.add("hidden");
  $("main").classList.remove("hidden");
  $("who").textContent = account;
  $("adminBox").classList.toggle("hidden", !isAdmin);
  refreshTasks();
}

$("loginBtn").onclick = async () => {
  $("loginErr").textContent = "";
  const r = await fetch("/api/login", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({username: $("username").value,
                          password: $("password").value})
  });
  const data = await r.json();
  if (!r.ok) { $("loginErr").textContent = data.error || "登录失败"; return; }
  showMain(data.account, data.is_admin);
};

$("logoutBtn").onclick = async () => {
  await fetch("/api/logout", {method: "POST"});
  showLogin();
};

$("refreshBtn").onclick = refreshTasks;

async function uploadFile(uploadId, fileIndex, file) {
  const total = Math.ceil(file.size / CHUNK);
  for (let i = 0; i < total; i++) {
    const blob = file.slice(i * CHUNK, (i + 1) * CHUNK);
    const fd = new FormData();
    fd.append("upload_id", uploadId);
    fd.append("file_index", fileIndex);
    fd.append("chunk_index", i);
    fd.append("blob", blob);
    await api("/api/upload/chunk", {method: "POST", body: fd});
    $("uploadProgress").textContent =
      `上传 ${file.name}: ${i + 1}/${total} 片`;
  }
  return total;
}

$("startBtn").onclick = async () => {
  const files = $("files").files;
  if (!files.length) { alert("请先选择文件"); return; }
  const init = await (await api("/api/upload/init",
    {method: "POST", headers: {"Content-Type": "application/json"},
     body: "{}"})).json();
  const uploadId = init.upload_id;
  const meta = [];
  for (let idx = 0; idx < files.length; idx++) {
    const chunks = await uploadFile(uploadId, idx, files[idx]);
    meta.push({index: idx, name: files[idx].name, chunks: chunks});
  }
  const body = {upload_id: uploadId, files: meta, folder: $("folder").value};
  const ta = $("targetAccount").value.trim();
  if (ta) body.account = ta;
  const r = await api("/api/import", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body)});
  const data = await r.json();
  if (!r.ok) { alert(data.error || "导入失败"); return; }
  $("uploadProgress").textContent = "上传完成,任务已进入队列: " + data.task_id;
  refreshTasks();
};

async function refreshTasks() {
  const tasks = await (await api("/api/tasks")).json();
  const tbody = $("tasks").querySelector("tbody");
  tbody.innerHTML = "";
  let anyActive = false;
  for (const t of tasks) {
    if (t.status === "queued" || t.status === "running") anyActive = true;
    const pct = t.total ? Math.round(100 * t.done / t.total) : 0;
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td>${t.id.slice(0, 8)}</td><td>${t.account}</td>` +
      `<td>${statusText(t.status)}</td>` +
      `<td><div class="bar"><div style="width:${pct}%"></div></div>` +
      `${t.done}/${t.total}</td><td>${t.failed}</td>`;
    tbody.appendChild(tr);
  }
  if (anyActive && !pollTimer) {
    pollTimer = setInterval(refreshTasks, 3000);
  } else if (!anyActive && pollTimer) {
    clearInterval(pollTimer); pollTimer = null;
  }
}

function statusText(s) {
  return {queued: "排队中", running: "进行中", done: "完成",
          failed: "失败", interrupted: "中断"}[s] || s;
}

// 启动时探测是否已登录
api("/api/tasks").then(r => {
  if (r.ok) return r.json().then(() => {
    // 已登录但缺身份信息,简单重新登录;此处直接显示主界面占位
    $("login").classList.add("hidden");
    $("main").classList.remove("hidden");
    refreshTasks();
  });
}).catch(() => showLogin());
```

- [ ] **Step 4: 手动浏览器验证**

启动 web 进程:`cd zimbra-import && cp config.example.ini config.ini`(填入测试值;无 Zimbra 时可临时 monkeypatch,或直接在有 Zimbra 的服务器上做),运行 `FLASK_APP=... python -c "from zimbra_import.config import Config; from zimbra_import.web import create_app; create_app(Config('config.ini')).run(port=8088)"`。

浏览器打开 `http://127.0.0.1:8088`,确认:登录表单显示;登录后出现导入表单;选文件后能看到分片上传进度;任务出现在「我的任务」表格并随轮询刷新进度条。

Expected: 页面各环节交互正常(此步无自动断言,以实际可用为准)。

- [ ] **Step 5: 提交**

```bash
git add -A && git commit -m "feat: single-page frontend with chunked upload and progress"
```

---

## Task 16: 部署单元与说明

**Files:**
- Create: `zimbra-import/deploy/zimbra-import-web.service`
- Create: `zimbra-import/deploy/zimbra-import-worker.service`
- Create: `zimbra-import/deploy/run_web.py`
- Create: `zimbra-import/deploy/README.md`

- [ ] **Step 1: 写 web 启动脚本**

`deploy/run_web.py`:
```python
import sys
from zimbra_import.config import Config
from zimbra_import.web import create_app

cfg = Config(sys.argv[1] if len(sys.argv) > 1 else "/etc/zimbra-import/config.ini")
app = create_app(cfg)

if __name__ == "__main__":
    app.run(host=cfg.listen_host, port=cfg.listen_port)
```

- [ ] **Step 2: 写 systemd 单元**

`deploy/zimbra-import-web.service`:
```ini
[Unit]
Description=Zimbra Import Web
After=network.target

[Service]
User=zimbra-import
WorkingDirectory=/opt/zimbra-import
ExecStart=/opt/zimbra-import/venv/bin/python deploy/run_web.py /etc/zimbra-import/config.ini
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

`deploy/zimbra-import-worker.service`:
```ini
[Unit]
Description=Zimbra Import Worker
After=network.target

[Service]
User=zimbra-import
WorkingDirectory=/opt/zimbra-import
ExecStart=/opt/zimbra-import/venv/bin/python -m zimbra_import.worker /etc/zimbra-import/config.ini
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 3: 写部署 README**

`deploy/README.md`:
```markdown
# 部署说明

## 1. 系统用户与目录
    useradd -r -s /sbin/nologin zimbra-import
    mkdir -p /opt/zimbra-import /etc/zimbra-import /var/lib/zimbra-import
    chown -R zimbra-import: /var/lib/zimbra-import

## 2. 代码与依赖
    cp -r zimbra-import/* /opt/zimbra-import/
    cd /opt/zimbra-import
    python3 -m venv venv
    venv/bin/pip install -r requirements.txt
    chown -R zimbra-import: /opt/zimbra-import

## 3. 配置
    cp config.example.ini /etc/zimbra-import/config.ini
    chmod 600 /etc/zimbra-import/config.ini
    chown zimbra-import: /etc/zimbra-import/config.ini
编辑 config.ini:填入 secret_key(随机串)、service_account 的账号密码。

## 4. 服务账号
在 Zimbra 上创建一个专用管理员账号作为服务账号:
    su - zimbra -c "zmprov ca importsvc@msauto.com.cn '<强密码>'"
    su - zimbra -c "zmprov ma importsvc@msauto.com.cn zimbraIsAdminAccount TRUE"
把账号密码写入 config.ini 的 [service_account]。

## 5. 启动
    cp deploy/*.service /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable --now zimbra-import-web zimbra-import-worker

## 6. 反向代理(经 Zimbra nginx 暴露 HTTPS)
web 进程只监听 127.0.0.1。在 Zimbra nginx 上加一个 location 反代到
127.0.0.1:8088,复用已有的 Let's Encrypt 证书,对外只走 HTTPS。

## 7. 服务账号凭据轮换
config.ini 含服务账号密码,文件权限须为 600;定期轮换该账号密码并同步更新。
```

- [ ] **Step 4: 验证单元文件语法**

Run: `python -c "import configparser; c=configparser.ConfigParser(); c.read('deploy/zimbra-import-web.service'); print(c.get('Service','ExecStart'))"`
Expected: 打印出 ExecStart 行,无异常

- [ ] **Step 5: 提交**

```bash
git add -A && git commit -m "chore: systemd units and deployment guide"
```

---

## Task 17: 集成测试与端到端验证

**Files:**
- Create: `zimbra-import/tests/test_integration.py`

> 集成测试需要真实 Zimbra 与一个测试账户,默认跳过;在服务器上带环境变量运行。

- [ ] **Step 1: 在 Zimbra 上建测试账户**

在 Zimbra 服务器执行:
```bash
su - zimbra -c "zmprov ca importtest@msauto.com.cn 'Test-Passw0rd!'"
```

- [ ] **Step 2: 写集成测试**

`tests/test_integration.py`:
```python
import os
import io
import tarfile
import pytest

from zimbra_import.config import Config
from zimbra_import import archive, zimbra_auth, zimbra_inject

RUN = os.environ.get("ZIMBRA_IT") == "1"
pytestmark = pytest.mark.skipif(not RUN, reason="set ZIMBRA_IT=1 to run")

CONFIG = os.environ.get("ZIMBRA_IT_CONFIG", "/etc/zimbra-import/config.ini")
TARGET = "importtest@msauto.com.cn"


def test_delegate_and_inject_single_eml(tmp_path):
    cfg = Config(CONFIG)
    token = zimbra_auth.delegate_token(cfg, TARGET)
    eml = tmp_path / "it.eml"
    eml.write_bytes(b"From: it@test\r\nSubject: IT probe\r\n\r\nbody\r\n")
    zimbra_inject.inject_eml(cfg, TARGET, "Inbox", token, str(eml))
    # 人工确认:登录 importtest 的 webmail,Inbox 应出现 "IT probe"


def test_normalize_and_inject_pax_bundle(tmp_path):
    cfg = Config(CONFIG)
    inp = tmp_path / "input"
    inp.mkdir() if False else os.makedirs(str(inp))
    longname = "Re_ " + "入出库通知采购" * 6 + ".eml"
    with tarfile.open(str(inp / "b.tgz"), "w:gz",
                      format=tarfile.PAX_FORMAT) as tar:
        content = b"From: it@test\r\nSubject: IT pax probe\r\n\r\nx\r\n"
        info = tarfile.TarInfo(name=longname)
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
    work = tmp_path / "work"
    os.makedirs(str(work))
    norm = archive.normalize(str(inp), str(work))
    assert norm.kind == "eml-bundle" and len(norm.eml_paths) == 1
    token = zimbra_auth.delegate_token(cfg, TARGET)
    zimbra_inject.inject_eml(cfg, TARGET, "Inbox", token, norm.eml_paths[0])
    # 人工确认:webmail Inbox 出现 "IT pax probe"
```

- [ ] **Step 3: 运行单元测试全集确认无回归**

Run: `cd zimbra-import && python -m pytest tests/ -v`
Expected: 所有单元测试 PASS,`test_integration.py` 显示 skipped

- [ ] **Step 4: 在服务器上运行集成测试**

在 Zimbra 服务器、已部署配置后运行:
Run: `ZIMBRA_IT=1 ZIMBRA_IT_CONFIG=/etc/zimbra-import/config.ini python -m pytest tests/test_integration.py -v`
Expected: 2 passed;随后登录 `importtest@msauto.com.cn` 的 webmail,确认 Inbox 中出现 "IT probe" 与 "IT pax probe" 两封邮件

- [ ] **Step 5: 端到端手动验证(完整 tgz 路径)**

用一个真实的 Zimbra 完整账户导出 tgz,通过页面导入到 `importtest@msauto.com.cn`:确认 `archive.detect_kind` 判为 `zimbra-export`、文件夹结构/联系人/日历在 webmail 中正确还原。若真实导出不含 `.meta` 旁挂文件导致判别错误,据实修正 Task 3 的 `detect_kind` 并补一个单元测试。

- [ ] **Step 6: 提交**

```bash
git add -A && git commit -m "test: integration tests against real Zimbra"
```

---

## 自检结论

- **Spec 覆盖**:背景目标(全计划)、多 eml + 大 tgz 上传(Task 7/13/15)、PaxHeader 规避(Task 2/4)、管理员+用户认证(Task 8/12/14)、服务账号注入认证(Task 9/11)、两种 tgz 归一化(Task 3/4)、SQLite 任务队列(Task 5/6)、串行调度与队列护栏(Task 6/14)、后台任务+进度持久化(Task 6/11/15)、错误处理逐封不中断(Task 11)、安全 HTTPS/越权防护(Task 14/16)、测试策略(Task 2-17)——逐项有任务对应。
- **占位符**:无 TBD/TODO;`detect_kind` 的 `.meta` 判别与 `_repack_clean` 的 GNU 格式均为明确实现,并在 Task 17 Step 5 设了真实导出验证与修正点。
- **类型一致性**:`NormalizedInput`/`Identity` 字段、任务状态字符串、`TaskStore` 方法名、`archive.normalize` 签名在各任务间一致。
- **范围**:单一内聚工具,一个实现计划可完成。
