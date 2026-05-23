# ZImport-tools 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从 ZImport 当前 main HEAD 派生出一个独立的 Zimbra-内置编辑(ZImport-tools),只走 cookie 认证、不带表单登录,作为 Zimbra Web 应用栏里的 Zimlet 入口。

**Architecture:** 同 ZImport 的双进程 Python 应用(web + worker + SQLite 队列)。核心管线(`archive`、`store`、`uploads`、`worker`、`zimbra_inject`、`zimbra_folders`、`zimbra_search`)从 ZImport 复制;新增 `zimbra_session`(cookie 校验 + 缓存);重写 `web.py`(无 `/api/login`、cookie 认证 + CSRF);重写前端(无登录表单);新增 Zimlet 包注册顶层应用页签。

**Tech Stack:** Python 3.8+、Flask 3.x、Werkzeug 3.x、requests、`tarfile`/`sqlite3`、pytest;前端原生 JS 单页;经典 Zimbra 8.8.15 Zimlet。

设计依据见 [`../specs/2026-05-23-zimport-tools-design.md`](../specs/2026-05-23-zimport-tools-design.md)。

---

## 总体说明

**源仓库:** `/tmp/11223344/zimport/`(ZImport,main HEAD 为基线 `df5ca13` 之后已加了 spec 提交;以最新的 `main` 上代码为基线)
**目标仓库:** `/tmp/11223344/zimport-tools/`(本计划要建的新项目)
**最终 GitHub:** `https://github.com/jiulin-hou/ZImport-tools`(user 手工建空仓后推送)

**所有路径相对于** `/tmp/11223344/zimport-tools/`(本计划的项目根)。

**关键命名映射** —— 重命名时按这个表对照,避免误改:

| 源(ZImport) | 目标(ZImport-tools) | 说明 |
|---|---|---|
| `zimport` (Python 包) | `zimport_tools` | 下划线,Python 标识符 |
| `from zimport import` | `from zimport_tools import` | 同上 |
| `from zimport.X import` | `from zimport_tools.X import` | 同上 |
| `/opt/zimport` | `/opt/zimport-tools` | 横线,系统路径 |
| `/etc/zimport` | `/etc/zimport-tools` | 同上 |
| `/var/lib/zimport` | `/var/lib/zimport-tools` | 同上 |
| 系统用户 `zimport` | `zimport-tools` | 同上 |
| `zimport-web.service` | `zimport-tools-web.service` | systemd 单元 |
| `zimport-worker.service` | `zimport-tools-worker.service` | systemd 单元 |
| `python -m zimport.worker` | `python -m zimport_tools.worker` | 模块路径 |

> **不要全局 sed `zimport → zimport_tools`** —— 像 `X-Zimport-CSRF` 这种字符串、`ZImport` 这种品牌名要保持原样或单独处理。每个任务里说明具体替换范围。

## 文件结构(目标完成态)

```
zimport-tools/
├── README.md
├── CHANGELOG.md
├── requirements.txt
├── config.example.ini
├── .gitignore
├── zimport_tools/
│   ├── __init__.py                __version__ = "1.0.0"
│   ├── config.py                  从 ZImport 复制(无改动)
│   ├── archive.py                 从 ZImport 复制(无改动)
│   ├── store.py                   从 ZImport 复制(无改动)
│   ├── uploads.py                 从 ZImport 复制(无改动)
│   ├── worker.py                  从 ZImport 复制 + 改 import 路径
│   ├── zimbra_auth.py             从 ZImport 复制 + 删 login() 函数
│   ├── zimbra_inject.py           从 ZImport 复制(无改动)
│   ├── zimbra_folders.py          从 ZImport 复制(无改动)
│   ├── zimbra_search.py           从 ZImport 复制(无改动)
│   ├── zimbra_session.py          ★ 新增:cookie 校验 + 缓存
│   ├── web.py                     ★ 重写:无 /api/login,cookie 认证 + CSRF
│   └── static/
│       ├── index.html             ★ 重写:无登录表单
│       ├── app.js                 ★ 重写:启动直接 /api/me;所有 fetch 带 CSRF 头
│       └── style.css              从 ZImport 复制 + 删除登录框相关样式
├── zimlet/
│   ├── com_msauto_zimport_tools.xml
│   ├── com_msauto_zimport_tools.js
│   ├── com_msauto_zimport_tools.css
│   └── build.sh                   打包成 com_msauto_zimport_tools.zip
├── tests/                         从 ZImport 复制 + 适配 + 新增 zimbra_session/CSRF 测试
└── deploy/                        从 ZImport 复制 + 改名(setup.sh / setup-proxy.sh / release.sh / *.service / run_web.py)
```

---

## Task 1: 项目脚手架与基础文件

**Files:**
- Create: `/tmp/11223344/zimport-tools/.gitignore`
- Create: `/tmp/11223344/zimport-tools/requirements.txt`
- Create: `/tmp/11223344/zimport-tools/config.example.ini`
- Create: `/tmp/11223344/zimport-tools/CHANGELOG.md`
- Create: `/tmp/11223344/zimport-tools/README.md`(占位,Task 11 完整化)
- Create: `/tmp/11223344/zimport-tools/zimport_tools/__init__.py`
- Create: `/tmp/11223344/zimport-tools/tests/__init__.py`

- [ ] **Step 1: 初始化目录与 git**

```bash
mkdir -p /tmp/11223344/zimport-tools/zimport_tools/static
mkdir -p /tmp/11223344/zimport-tools/tests
mkdir -p /tmp/11223344/zimport-tools/deploy
mkdir -p /tmp/11223344/zimport-tools/zimlet
cd /tmp/11223344/zimport-tools
git init -b main
touch zimport_tools/__init__.py tests/__init__.py
```

- [ ] **Step 2: 写 `.gitignore`**

```
__pycache__/
*.pyc
.pytest_cache/
venv/
*.db
tmp/
dist/
```

- [ ] **Step 3: 写 `requirements.txt`**

```
Flask>=3.0,<4.0
Werkzeug>=3.0,<4.0
requests>=2.20
pytest>=6.0
```

- [ ] **Step 4: 写 `config.example.ini`**(同 ZImport,但所有路径里的 `zimport` 改为 `zimport-tools`)

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
temp_root = /var/lib/zimport-tools/tmp
db_path = /var/lib/zimport-tools/tasks.db
max_task_bytes = 10737418240
retention_days = 7

[scheduler]
concurrency = 1
queue_limit = 50
dedupe = true

[upload]
chunk_size = 10485760
```

> 如果源 `config.example.ini` 在 v1.1.0 后又加了字段(如 `dedupe`),以源最新版为准。下面 Task 2 复制 `config.py` 时也以源最新 `config.py` 为准。

- [ ] **Step 5: 写 `CHANGELOG.md` 骨架**(v1.0.0 段落 Task 11 再填正式内容)

```markdown
# 更新日志

版本号遵循语义化版本(主.次.补丁)。发版流程:

1. 在本文件顶部加一条新版本记录(`## vX.Y.Z — 日期` 加改动条目)
2. 运行 `bash deploy/release.sh X.Y.Z` —— 自动跑测试、写版本号、提交、
   打 tag、推送 main 与 tag、生成 `dist/zimport-tools-X.Y.Z.tar.gz`
```

- [ ] **Step 6: 写占位 `README.md`**

```markdown
# ZImport-tools

ZImport 的 Zimbra 内置工具版 —— 作为 Zimbra Web 应用栏里的「数据导入」页签。

详细 README 见 Task 11 提交。
```

- [ ] **Step 7: 写 `zimport_tools/__init__.py`**

```python
__version__ = "0.1.0-dev"
```

> v1.0.0 在 Task 11 发版时由 `release.sh` 写入。

- [ ] **Step 8: 建 venv 并装依赖**

```bash
cd /tmp/11223344/zimport-tools
python3 -m venv venv
venv/bin/pip install -q -r requirements.txt
venv/bin/python -c "import flask, requests, pytest; print('deps OK')"
```

Expected: `deps OK`

- [ ] **Step 9: 提交**

```bash
git add -A
git commit -m "chore: scaffold ZImport-tools project"
```

---

## Task 2: 复制核心管线模块 + 测试

复制 ZImport 中**完全不需要改动**的纯核心模块及其测试:`archive.py`、`store.py`、`uploads.py`、`zimbra_inject.py`、`zimbra_folders.py`、`zimbra_search.py`、`config.py`。

**Files:**
- Copy: 6 个模块 + `config.py` 到 `zimport_tools/`
- Copy: 6 个对应测试到 `tests/`

- [ ] **Step 1: 复制模块**

```bash
SRC=/tmp/11223344/zimport/zimport
DST=/tmp/11223344/zimport-tools/zimport_tools
cp "$SRC/config.py"          "$DST/config.py"
cp "$SRC/archive.py"         "$DST/archive.py"
cp "$SRC/store.py"           "$DST/store.py"
cp "$SRC/uploads.py"         "$DST/uploads.py"
cp "$SRC/zimbra_inject.py"   "$DST/zimbra_inject.py"
cp "$SRC/zimbra_folders.py"  "$DST/zimbra_folders.py"
cp "$SRC/zimbra_search.py"   "$DST/zimbra_search.py"
```

- [ ] **Step 2: 复制对应测试**

```bash
SRC=/tmp/11223344/zimport/tests
DST=/tmp/11223344/zimport-tools/tests
cp "$SRC/test_config.py"          "$DST/test_config.py"
cp "$SRC/test_archive.py"         "$DST/test_archive.py"
cp "$SRC/test_store.py"           "$DST/test_store.py"
cp "$SRC/test_uploads.py"         "$DST/test_uploads.py"
cp "$SRC/test_zimbra_inject.py"   "$DST/test_zimbra_inject.py"
cp "$SRC/test_zimbra_folders.py"  "$DST/test_zimbra_folders.py"
cp "$SRC/test_zimbra_search.py"   "$DST/test_zimbra_search.py"
```

- [ ] **Step 3: 改这些文件里的 import 路径**

精确替换:`from zimport.` → `from zimport_tools.`、`from zimport import` → `from zimport_tools import`、`import zimport.` → `import zimport_tools.`、`import zimport ` → `import zimport_tools `

```bash
cd /tmp/11223344/zimport-tools
for f in zimport_tools/{config,archive,store,uploads,zimbra_inject,zimbra_folders,zimbra_search}.py \
         tests/test_{config,archive,store,uploads,zimbra_inject,zimbra_folders,zimbra_search}.py; do
  sed -i \
    -e 's/\bfrom zimport\./from zimport_tools./g' \
    -e 's/\bfrom zimport import\b/from zimport_tools import/g' \
    -e 's/\bimport zimport\./import zimport_tools./g' \
    -e 's/\bimport zimport$/import zimport_tools/g' \
    "$f"
done
```

> 注意 `\b` 单词边界,避免误改 `zimport_tools` 自己。

- [ ] **Step 4: 跑测试,确认全过**

```bash
cd /tmp/11223344/zimport-tools
venv/bin/python -m pytest tests/ -q
```

Expected: 全部 PASS(具体条数取决于源仓库当前 main 的状态,大致 30+ 测试)。

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "feat: copy core pipeline modules from ZImport"
```

---

## Task 3: 复制 zimbra_auth.py 并删除 login()

ZImport 的 `zimbra_auth.py` 有 `login()`(账号密码登录)和 `delegate_token()`/`_admin_token()`(服务账号委托)两组功能。ZImport-tools 只需要后者(worker 注入时用)。前者**删掉**。

**Files:**
- Copy + modify: `zimport_tools/zimbra_auth.py`
- Copy + modify: `tests/test_zimbra_auth.py`

- [ ] **Step 1: 复制并修改 `zimbra_auth.py`**

```bash
cp /tmp/11223344/zimport/zimport/zimbra_auth.py /tmp/11223344/zimport-tools/zimport_tools/zimbra_auth.py
```

打开 `/tmp/11223344/zimport-tools/zimport_tools/zimbra_auth.py`,**整段删除** `login()` 函数(从 `def login(cfg, username, password):` 到该函数的最后一行 `return Identity(is_admin=False, account=username)`)。

保留:`Identity` namedtuple、`AuthError` 类、`_soap()` 函数、`_admin_token()` 函数、`delegate_token()` 函数,以及 `import collections`、`import requests` 等顶部 import。

修改 import 路径(若有 `from zimport.` 引用,同 Task 2 Step 3 的 sed 处理)。

- [ ] **Step 2: 复制并修改 `test_zimbra_auth.py`**

```bash
cp /tmp/11223344/zimport/tests/test_zimbra_auth.py /tmp/11223344/zimport-tools/tests/test_zimbra_auth.py
```

打开 `/tmp/11223344/zimport-tools/tests/test_zimbra_auth.py`,**删除** 所有名字以 `test_login_` 开头的测试函数(`test_login_admin`、`test_login_normal_user`、`test_login_bad_credentials`)。

保留:辅助类 `_Resp`、`_Cfg`,辅助函数 `_fault()`、`_admin_ok()`、`_account_ok()`,以及 `test_delegate_token`。

> `_account_ok()` 可能因为不再被引用而显得无用,但保留它符合"最小变更"原则;LSP 不会报错。

同 Task 2 Step 3 sed 改 import 路径。

- [ ] **Step 3: 跑测试**

```bash
cd /tmp/11223344/zimport-tools
venv/bin/python -m pytest tests/test_zimbra_auth.py -v
```

Expected: 1 PASS(`test_delegate_token`),0 FAIL。如果还有 `test_login_*` 出现 → 删除不彻底,回去再删。

- [ ] **Step 4: 全量测试无回归**

```bash
venv/bin/python -m pytest tests/ -q
```

Expected: 仍全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "feat: copy zimbra_auth without login(), keep delegate_token"
```

---

## Task 4: 复制 worker.py + 改 import 路径

`worker.py` 内部从 `zimport` 包导入若干模块,需要改路径。

**Files:**
- Copy + modify: `zimport_tools/worker.py`
- Copy + modify: `tests/test_worker.py`

- [ ] **Step 1: 复制并 sed 改路径**

```bash
cp /tmp/11223344/zimport/zimport/worker.py /tmp/11223344/zimport-tools/zimport_tools/worker.py
cp /tmp/11223344/zimport/tests/test_worker.py /tmp/11223344/zimport-tools/tests/test_worker.py
cd /tmp/11223344/zimport-tools
sed -i \
  -e 's/\bfrom zimport\./from zimport_tools./g' \
  -e 's/\bfrom zimport import\b/from zimport_tools import/g' \
  -e 's/\bzimport\.worker\b/zimport_tools.worker/g' \
  zimport_tools/worker.py tests/test_worker.py
```

- [ ] **Step 2: 跑 worker 测试**

```bash
venv/bin/python -m pytest tests/test_worker.py -v
```

Expected: 全 PASS(3 个或更多,取决于源仓库当前 main 的状态)。

- [ ] **Step 3: 全量测试无回归**

```bash
venv/bin/python -m pytest tests/ -q
```

Expected: 仍全部 PASS。

- [ ] **Step 4: 提交**

```bash
git add -A
git commit -m "feat: copy worker.py with adapted import paths"
```

---

## Task 5: zimbra_session.py(新模块,TDD)

**Files:**
- Create: `zimport_tools/zimbra_session.py`
- Test: `tests/test_zimbra_session.py`

- [ ] **Step 1: 写失败测试**

`tests/test_zimbra_session.py`:
```python
import pytest
from zimport_tools import zimbra_session
from zimport_tools.zimbra_auth import Identity


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _Cfg:
    soap_url = "https://h:8443/service/soap"
    verify_tls = False


def _info_ok(account="u@d", is_admin="FALSE"):
    return {"Body": {"GetInfoResponse": {
        "name": account,
        "attrs": {"_attrs": {"zimbraIsAdminAccount": is_admin}},
    }}}


def _fault():
    return {"Body": {"Fault": {"Reason": {"Text": "auth failed"}}}}


def test_validate_valid_token_returns_identity(monkeypatch):
    cache = zimbra_session._Cache()
    monkeypatch.setattr(zimbra_session.requests, "post",
                        lambda url, **kw: _Resp(_info_ok("u@d", "FALSE")))
    ident = zimbra_session.validate(_Cfg, "TOK", _cache=cache)
    assert isinstance(ident, Identity)
    assert ident.account == "u@d"
    assert ident.is_admin is False


def test_validate_admin_token(monkeypatch):
    cache = zimbra_session._Cache()
    monkeypatch.setattr(zimbra_session.requests, "post",
                        lambda url, **kw: _Resp(_info_ok("admin@d", "TRUE")))
    ident = zimbra_session.validate(_Cfg, "ADMTOK", _cache=cache)
    assert ident.is_admin is True


def test_validate_invalid_token_raises(monkeypatch):
    from zimport_tools.zimbra_auth import AuthError
    cache = zimbra_session._Cache()
    monkeypatch.setattr(zimbra_session.requests, "post",
                        lambda url, **kw: _Resp(_fault()))
    with pytest.raises(AuthError):
        zimbra_session.validate(_Cfg, "BADTOK", _cache=cache)


def test_validate_zimbra_unreachable(monkeypatch):
    import requests
    cache = zimbra_session._Cache()
    def boom(url, **kw):
        raise requests.ConnectionError("nope")
    monkeypatch.setattr(zimbra_session.requests, "post", boom)
    with pytest.raises(zimbra_session.ZimbraUnreachable):
        zimbra_session.validate(_Cfg, "TOK", _cache=cache)


def test_validate_caches_positive(monkeypatch):
    cache = zimbra_session._Cache()
    calls = []
    monkeypatch.setattr(zimbra_session.requests, "post",
                        lambda url, **kw: (calls.append(1), _Resp(_info_ok()))[1])
    zimbra_session.validate(_Cfg, "TOK", _cache=cache)
    zimbra_session.validate(_Cfg, "TOK", _cache=cache)
    zimbra_session.validate(_Cfg, "TOK", _cache=cache)
    assert len(calls) == 1, "positive cache should prevent re-validation"


def test_validate_caches_negative(monkeypatch):
    from zimport_tools.zimbra_auth import AuthError
    cache = zimbra_session._Cache()
    calls = []
    monkeypatch.setattr(zimbra_session.requests, "post",
                        lambda url, **kw: (calls.append(1), _Resp(_fault()))[1])
    for _ in range(3):
        with pytest.raises(AuthError):
            zimbra_session.validate(_Cfg, "BAD", _cache=cache)
    assert len(calls) == 1, "negative cache should prevent re-validation"


def test_cache_ttl_expiry(monkeypatch):
    cache = zimbra_session._Cache()
    calls = []
    monkeypatch.setattr(zimbra_session.requests, "post",
                        lambda url, **kw: (calls.append(1), _Resp(_info_ok()))[1])
    # Force the time used by the cache to a fixed value, then advance past TTL
    now = [1000.0]
    monkeypatch.setattr(zimbra_session, "_now", lambda: now[0])
    zimbra_session.validate(_Cfg, "TOK", _cache=cache)
    now[0] += zimbra_session.POSITIVE_TTL + 1
    zimbra_session.validate(_Cfg, "TOK", _cache=cache)
    assert len(calls) == 2, "expired positive cache entry should re-validate"


def test_cache_lru_eviction():
    cache = zimbra_session._Cache(capacity=2)
    cache.put_positive("A", Identity(False, "a@d"))
    cache.put_positive("B", Identity(False, "b@d"))
    cache.put_positive("C", Identity(False, "c@d"))  # Should evict A
    assert cache.get("A") is None
    assert cache.get("B") is not None
    assert cache.get("C") is not None
```

- [ ] **Step 2: 跑测试确认失败**

```bash
venv/bin/python -m pytest tests/test_zimbra_session.py -v
```

Expected: 8 FAIL,因 `ModuleNotFoundError: No module named 'zimport_tools.zimbra_session'`

- [ ] **Step 3: 实现 `zimbra_session.py`**

`zimport_tools/zimbra_session.py`:
```python
import time
import threading
from collections import OrderedDict

import requests

from zimport_tools.zimbra_auth import Identity, AuthError, _soap

POSITIVE_TTL = 300   # 5 minutes
NEGATIVE_TTL = 30    # 30 seconds
DEFAULT_CAPACITY = 1024


class ZimbraUnreachable(Exception):
    """Raised when the Zimbra SOAP endpoint is unreachable (network errors)."""


def _now():
    return time.time()


class _Cache:
    """LRU cache storing token -> (identity_or_None, expires_at).

    identity_or_None=None means a negative entry (auth failed).
    Thread-safe via a single internal lock.
    """

    def __init__(self, capacity=DEFAULT_CAPACITY):
        self.capacity = capacity
        self._items = OrderedDict()
        self._lock = threading.Lock()

    def get(self, token):
        """Return identity (or None for negative) if still valid;
        otherwise return False meaning 'not in cache'."""
        with self._lock:
            entry = self._items.get(token)
            if entry is None:
                return False
            identity, expires_at = entry
            if _now() >= expires_at:
                del self._items[token]
                return False
            self._items.move_to_end(token)
            return identity  # may be None for negative cache

    def put_positive(self, token, identity):
        self._put(token, identity, POSITIVE_TTL)

    def put_negative(self, token):
        self._put(token, None, NEGATIVE_TTL)

    def _put(self, token, value, ttl):
        with self._lock:
            self._items[token] = (value, _now() + ttl)
            self._items.move_to_end(token)
            while len(self._items) > self.capacity:
                self._items.popitem(last=False)  # evict oldest


_default_cache = _Cache()


def validate(cfg, token, _cache=None):
    """Validate a Zimbra ZM_AUTH_TOKEN cookie value.

    Returns Identity on success.
    Raises AuthError if the token is invalid/expired/rejected.
    Raises ZimbraUnreachable if Zimbra is unreachable (network error).
    """
    cache = _cache if _cache is not None else _default_cache
    cached = cache.get(token)
    if cached is not None:
        if cached is False:
            pass  # not in cache, fall through to network
        elif isinstance(cached, Identity):
            return cached
        else:
            # negative cache entry (cached is None) — re-raise AuthError
            raise AuthError("invalid token (cached)")

    body = {
        "GetInfoRequest": {
            "_jsns": "urn:zimbraAccount",
            "sections": "mbox,prefs,attrs,props",
        }
    }
    header = {"context": {"_jsns": "urn:zimbra",
                          "authToken": {"_content": token}}}
    try:
        inner = _soap(cfg.soap_url, body, cfg.verify_tls, header=header)
    except requests.RequestException as exc:
        raise ZimbraUnreachable(str(exc))
    except AuthError:
        cache.put_negative(token)
        raise

    info = inner.get("GetInfoResponse", {})
    account = info.get("name") or _account_from_attrs(info)
    is_admin = _admin_from_attrs(info)
    identity = Identity(is_admin=is_admin, account=account)
    cache.put_positive(token, identity)
    return identity


def _account_from_attrs(info):
    # Fallback if response doesn't expose 'name' at top level
    attrs = info.get("attrs", {}).get("_attrs", {})
    return attrs.get("zimbraMailDeliveryAddress") or attrs.get("uid") or ""


def _admin_from_attrs(info):
    attrs = info.get("attrs", {}).get("_attrs", {})
    val = attrs.get("zimbraIsAdminAccount")
    return str(val).upper() == "TRUE"


def token_hash(token):
    """Compute a stable hash of a token for storing in session
    (so the raw token value never lives in the session cookie)."""
    import hashlib
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]
```

- [ ] **Step 4: 跑测试确认通过**

```bash
venv/bin/python -m pytest tests/test_zimbra_session.py -v
```

Expected: 8 passed

- [ ] **Step 5: 全量测试无回归**

```bash
venv/bin/python -m pytest tests/ -q
```

Expected: 全部 PASS。

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "feat: zimbra_session module with cookie validation + LRU cache"
```

---

## Task 6: web.py — cookie 认证 + CSRF + /api/me

ZImport-tools 的 `web.py` 与 ZImport 的不同之处:无 `/api/login`、无 `/api/logout`、`login_required` 走 cookie 验证、新增 CSRF 防护、新增 `/api/me`、新增账户切换检测。

**这一个 Task 只做这部分**,业务端点(上传/导入/任务/文件夹/账户搜索)在 Task 7 单独加。

**Files:**
- Create: `zimport_tools/web.py`(初版,仅 app factory + /api/me + 装饰器 + CSRF)
- Create: `tests/test_web.py`(仅测前述功能)

- [ ] **Step 1: 写失败测试**

`tests/test_web.py`:
```python
import pytest
from zimport_tools import web, zimbra_session
from zimport_tools.zimbra_auth import Identity, AuthError


class _Cfg:
    secret_key = "test-secret"
    temp_root = None
    db_path = None
    queue_limit = 50
    max_task_bytes = 10 ** 12
    chunk_size = 1024
    rest_base = "https://h:8443"
    verify_tls = False


@pytest.fixture
def app(tmp_path):
    cfg = _Cfg()
    cfg.temp_root = str(tmp_path / "tmp")
    cfg.db_path = str(tmp_path / "t.db")
    application = web.create_app(cfg)
    application.config["TESTING"] = True
    return application


@pytest.fixture
def patch_validate(monkeypatch):
    """Helper: make zimbra_session.validate return a specific Identity for
    a given token, or raise for others."""
    def _setup(token_to_identity):
        def fake_validate(cfg, token, _cache=None):
            if token in token_to_identity:
                return token_to_identity[token]
            raise AuthError("bad")
        monkeypatch.setattr(web.zimbra_session, "validate", fake_validate)
    return _setup


def test_me_with_valid_cookie(app, patch_validate):
    patch_validate({"TOK": Identity(False, "u@d")})
    client = app.test_client()
    client.set_cookie("ZM_AUTH_TOKEN", "TOK")
    resp = client.get("/api/me")
    assert resp.status_code == 200
    assert resp.get_json()["account"] == "u@d"
    assert resp.get_json()["is_admin"] is False


def test_me_with_admin_cookie(app, patch_validate):
    patch_validate({"ADMTOK": Identity(True, "admin@d")})
    client = app.test_client()
    client.set_cookie("ZM_AUTH_TOKEN", "ADMTOK")
    resp = client.get("/api/me")
    assert resp.get_json()["is_admin"] is True


def test_me_without_cookie(app):
    client = app.test_client()
    resp = client.get("/api/me")
    assert resp.status_code == 401


def test_me_with_invalid_cookie(app, patch_validate):
    patch_validate({})  # no token matches
    client = app.test_client()
    client.set_cookie("ZM_AUTH_TOKEN", "BAD")
    resp = client.get("/api/me")
    assert resp.status_code == 401


def test_zimbra_unreachable_returns_503(app, monkeypatch):
    def boom(cfg, token, _cache=None):
        raise zimbra_session.ZimbraUnreachable("nope")
    monkeypatch.setattr(web.zimbra_session, "validate", boom)
    client = app.test_client()
    client.set_cookie("ZM_AUTH_TOKEN", "TOK")
    resp = client.get("/api/me")
    assert resp.status_code == 503


def test_login_endpoint_does_not_exist(app):
    client = app.test_client()
    assert client.post("/api/login", json={}).status_code == 404


def test_account_switch_rebuilds_session(app, patch_validate):
    patch_validate({"A": Identity(False, "a@d"),
                    "B": Identity(False, "b@d")})
    client = app.test_client()
    client.set_cookie("ZM_AUTH_TOKEN", "A")
    assert client.get("/api/me").get_json()["account"] == "a@d"
    # Switch to a different cookie token
    client.set_cookie("ZM_AUTH_TOKEN", "B")
    assert client.get("/api/me").get_json()["account"] == "b@d"


# ---- CSRF tests use a state-changing endpoint we'll add a stub for ----

def test_csrf_missing_header_rejected(app, patch_validate):
    patch_validate({"TOK": Identity(False, "u@d")})
    client = app.test_client()
    client.set_cookie("ZM_AUTH_TOKEN", "TOK")
    # _test_csrf is a no-op POST endpoint registered only when TESTING=True
    resp = client.post("/api/_test_csrf",
                       headers={"Origin": "https://h:8443"})
    assert resp.status_code == 403


def test_csrf_bad_origin_rejected(app, patch_validate):
    patch_validate({"TOK": Identity(False, "u@d")})
    client = app.test_client()
    client.set_cookie("ZM_AUTH_TOKEN", "TOK")
    resp = client.post("/api/_test_csrf",
                       headers={"X-Zimport-CSRF": "1",
                                "Origin": "https://evil.example.com"})
    assert resp.status_code == 403


def test_csrf_valid_request_passes(app, patch_validate):
    patch_validate({"TOK": Identity(False, "u@d")})
    client = app.test_client()
    client.set_cookie("ZM_AUTH_TOKEN", "TOK")
    resp = client.post("/api/_test_csrf",
                       headers={"X-Zimport-CSRF": "1",
                                "Origin": "https://h:8443"})
    assert resp.status_code == 200
```

- [ ] **Step 2: 跑测试确认失败**

```bash
venv/bin/python -m pytest tests/test_web.py -v
```

Expected: 全 FAIL,`ModuleNotFoundError: No module named 'zimport_tools.web'`

- [ ] **Step 3: 实现 `web.py` 初版**

`zimport_tools/web.py`:
```python
import os
import functools
from urllib.parse import urlparse

from flask import Flask, request, session, jsonify, send_from_directory, abort

from zimport_tools import zimbra_session
from zimport_tools.zimbra_auth import AuthError
from zimport_tools.store import TaskStore

_STATIC = os.path.join(os.path.dirname(__file__), "static")
_CSRF_HEADER = "X-Zimport-CSRF"
_STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}


def create_app(cfg):
    app = Flask(__name__, static_folder=None)
    app.secret_key = cfg.secret_key
    app.config["MAX_CONTENT_LENGTH"] = None
    app.config.update(
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=True,
    )
    store = TaskStore(cfg.db_path)
    os.makedirs(cfg.temp_root, exist_ok=True)

    expected_origin = _origin_from_url(cfg.rest_base)

    def _csrf_check():
        if request.method not in _STATE_CHANGING:
            return None
        if request.headers.get(_CSRF_HEADER) != "1":
            return jsonify({"error": "非法请求来源"}), 403
        origin = request.headers.get("Origin")
        if origin and expected_origin and origin != expected_origin:
            return jsonify({"error": "非法请求来源"}), 403
        return None

    def _auth_via_cookie():
        token = request.cookies.get("ZM_AUTH_TOKEN")
        if not token:
            return None
        try:
            ident = zimbra_session.validate(cfg, token)
        except zimbra_session.ZimbraUnreachable:
            return ("zimbra_unreachable", None)
        except AuthError:
            return None
        return ident, token

    def login_required(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            current_hash = None
            cookie_token = request.cookies.get("ZM_AUTH_TOKEN")
            if cookie_token:
                current_hash = zimbra_session.token_hash(cookie_token)
            # If session is for a different cookie token, drop it
            if "account" in session and session.get("token_hash") != current_hash:
                session.clear()
            if "account" not in session:
                result = _auth_via_cookie()
                if result is None:
                    return jsonify({"error": "未登录"}), 401
                if result == ("zimbra_unreachable", None):
                    return jsonify({"error": "Zimbra 暂不可达"}), 503
                ident, token = result
                session["account"] = ident.account
                session["is_admin"] = ident.is_admin
                session["token_hash"] = zimbra_session.token_hash(token)
            csrf = _csrf_check()
            if csrf is not None:
                return csrf
            return fn(*a, **kw)
        return wrapper

    @app.route("/")
    def index():
        return send_from_directory(_STATIC, "index.html")

    @app.route("/static/<path:name>")
    def static_files(name):
        return send_from_directory(_STATIC, name)

    @app.route("/api/me")
    @login_required
    def me():
        return jsonify({"account": session["account"],
                        "is_admin": session.get("is_admin", False)})

    # Test-only no-op endpoint for CSRF tests
    if app.config.get("TESTING"):
        @app.route("/api/_test_csrf", methods=["POST"])
        @login_required
        def _test_csrf():
            return jsonify({"ok": True})

    # Task 7 will register additional business endpoints here
    return app


def _origin_from_url(url):
    """Extract the scheme://host[:port] portion of a URL for Origin checking."""
    if not url:
        return None
    p = urlparse(url)
    if not p.scheme or not p.netloc:
        return None
    return "%s://%s" % (p.scheme, p.netloc)
```

- [ ] **Step 4: 跑测试确认通过**

```bash
venv/bin/python -m pytest tests/test_web.py -v
```

Expected: 10 passed

- [ ] **Step 5: 全量测试无回归**

```bash
venv/bin/python -m pytest tests/ -q
```

Expected: 全部 PASS。

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "feat: web.py with cookie auth, CSRF, /api/me, account-switch protection"
```

---

## Task 7: web.py — 业务端点(从 ZImport 移植)

把 ZImport `web.py` 中的业务端点(上传 / 导入 / 任务 / 文件夹 / 账户搜索)移植过来,套上 ZImport-tools 的 `login_required`(自动获得 CSRF 校验)。

**Files:**
- Modify: `zimport_tools/web.py`
- Modify: `tests/test_web.py`(增加业务端点测试)

- [ ] **Step 1: 把 ZImport `web.py` 的业务端点搬过来**

打开 ZImport 源 `/tmp/11223344/zimport/zimport/web.py`,定位以下端点的实现:
- `POST /api/tasks/<task_id>/retry`
- `GET /api/tasks` 与 `GET /api/tasks/<task_id>`
- `_register_uploads` 函数 + 其内 3 个端点
- `_register_import` 函数 + 其内 `start_import` + `_queue_limit_for` 模块级函数
- `GET /api/folders`(若 v1.1.0 已有)
- `GET /api/admin/accounts/search`(若 v1.1.0 已有)

把这些**复制**到 ZImport-tools 的 `web.py` 中,注意:
1. 装饰器 `@login_required` 保持(本编辑器自动套了 CSRF)
2. `from zimport import X` → `from zimport_tools import X`
3. **不要复制** `/api/login`、`/api/logout`、`@app.route("/api/me")`(`me` 在 Task 6 已实现)
4. **不要复制** `index` / `static_files` 路由(Task 6 已实现)
5. 移除 ZImport 原 `_register_uploads`/`_register_import` 在 `create_app` 末尾的调用桩 —— ZImport-tools 不需要那种延迟注册结构,直接在 `create_app` 内 inline 写

具体修改是把 `web.py` 末尾(从 `# Task 7 will register additional business endpoints here` 那行开始)替换为复制过来的端点定义,以及任何模块级辅助函数(`_queue_limit_for`)。

> 这一步**手工细致**,不能简单 sed,需要看明白源码再粘。完成后用 `git diff` 自检看是否只复制了想要的部分。

- [ ] **Step 2: 给 tests/test_web.py 加业务端点测试**

把 ZImport `tests/test_web.py` 中**业务端点**相关测试复制过来。注意:
- ZImport 原测试用 `_login(app, monkeypatch)` 通过 `client.post("/api/login")` 建会话。ZImport-tools **没有** `/api/login`,改为通过设置 `ZM_AUTH_TOKEN` cookie + monkeypatching `zimbra_session.validate` 来登录。
- 把所有 `_login` 调用替换为下面定义的 helper:

在 `tests/test_web.py` 顶部追加:
```python
def _logged_in_client(app, patch_validate, account="u@d", is_admin=False, token="TOK"):
    patch_validate({token: Identity(is_admin, account)})
    client = app.test_client()
    client.set_cookie("ZM_AUTH_TOKEN", token)
    return client


def _csrf_headers():
    """Headers needed for state-changing requests under TESTING=True."""
    return {"X-Zimport-CSRF": "1"}
```

> 在 TESTING 模式下我们不强制 Origin(因为 Flask test_client 默认不发 Origin),所以只设 `X-Zimport-CSRF` 头。这要求 web.py 的 `_csrf_check` 对**空 Origin** 放行(已实现,见 `if origin and expected_origin and origin != expected_origin`)。

把 ZImport 测试中所有 `client.post(...)` 状态变更请求改成 `client.post(..., headers=_csrf_headers())`,改成把 `_login(app, monkeypatch)` 替换成 `_logged_in_client(app, patch_validate)`。

把 ZImport 测试里 `/api/login` 401 / `/api/login` 成功的测试**整体删掉**(我们已经在 Task 6 加了 `test_login_endpoint_does_not_exist`)。

把测 `越权` 的用例(普通用户给 `account` 参数被强制改回自己)、`队列已满拒绝`、`upload_id 校验`、`/api/tasks/<id>/retry`、`/api/folders`、`/api/admin/accounts/search` 等保留。

- [ ] **Step 3: 跑测试**

```bash
venv/bin/python -m pytest tests/test_web.py -v
```

Expected: 全 PASS。失败时,99% 是漏改 `_login` 或漏加 `_csrf_headers()`,逐个修。

- [ ] **Step 4: 全量测试无回归**

```bash
venv/bin/python -m pytest tests/ -q
```

Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "feat: port business endpoints (upload/import/tasks/folders/admin) from ZImport"
```

---

## Task 8: 前端重写(无登录表单)

ZImport-tools 的前端去掉了登录框 —— 启动直接调 `/api/me`,200 进入主界面,401 显示"请回 Zimbra Web 登录"提示,503 显示"Zimbra 暂不可达"。所有 fetch 自动带 `X-Zimport-CSRF: 1` 头。

**Files:**
- Create: `zimport_tools/static/index.html`
- Create: `zimport_tools/static/app.js`
- Create: `zimport_tools/static/style.css`

- [ ] **Step 1: 写 `index.html`**

`zimport_tools/static/index.html`:
```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ZImport-tools — 数据导入</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <div id="loading" class="card">正在识别身份…</div>

  <div id="error" class="card hidden">
    <h2>无法使用</h2>
    <p id="errorMsg" class="err"></p>
    <button id="retryBtn">重试</button>
  </div>

  <div id="main" class="card hidden">
    <p>当前登录:<b id="who"></b></p>
    <div id="adminBox" class="hidden">
      <label>目标账户(管理员):<input id="targetAccount"
        placeholder="留空=导入到自己"></label>
    </div>
    <label>目标文件夹:<select id="folder"></select></label>
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

- [ ] **Step 2: 写 `style.css`**(基于 ZImport 的 style.css 复制并精简登录框相关样式)

```bash
cp /tmp/11223344/zimport/zimport/static/style.css /tmp/11223344/zimport-tools/zimport_tools/static/style.css
```

打开该文件,删除任何针对 `#login`、`#loginBtn`、`#loginErr` 等仅登录框使用的规则(若有);保留 `.card`、`.hidden`、`.err`、`input`、`button`、`table`、`.bar` 等通用样式。

> 如果时间紧,可直接保留 ZImport 的 style.css 不动 —— 多余的规则不引用就不生效,无副作用。仅当样式有冲突时再清。

- [ ] **Step 3: 写 `app.js`**

`zimport_tools/static/app.js`:
```javascript
const CHUNK = 10 * 1024 * 1024; // 10MB
let pollTimer = null;
let session = null; // {account, is_admin}

function $(id) { return document.getElementById(id); }

function showOnly(id) {
  for (const k of ["loading", "error", "main"]) {
    $(k).classList.toggle("hidden", k !== id);
  }
}

function showError(msg) {
  $("errorMsg").textContent = msg;
  showOnly("error");
}

// All fetches go through this helper so CSRF header is consistent.
async function apiFetch(path, opts = {}) {
  const headers = new Headers(opts.headers || {});
  headers.set("X-Zimport-CSRF", "1");
  const r = await fetch(path, { ...opts, headers });
  return r;
}

async function probeSession() {
  showOnly("loading");
  let r;
  try {
    r = await apiFetch("/api/me");
  } catch (e) {
    showError("网络异常,无法连接 ZImport-tools。");
    return;
  }
  if (r.status === 401) {
    showError("请先在 Zimbra Web 登录,然后回到此页签。");
    return;
  }
  if (r.status === 503) {
    showError("Zimbra 暂不可达,请稍后再试。");
    return;
  }
  if (!r.ok) {
    showError("无法识别身份(状态码 " + r.status + ")。");
    return;
  }
  session = await r.json();
  $("who").textContent = session.account;
  $("adminBox").classList.toggle("hidden", !session.is_admin);
  await loadFolders();
  showOnly("main");
  refreshTasks();
}

async function loadFolders() {
  const ta = $("targetAccount").value.trim();
  const url = "/api/folders" + (ta ? "?account=" + encodeURIComponent(ta) : "");
  const r = await apiFetch(url);
  const sel = $("folder");
  sel.innerHTML = "";
  if (!r.ok) {
    const opt = document.createElement("option");
    opt.value = "Inbox";
    opt.textContent = "Inbox";
    sel.appendChild(opt);
    return;
  }
  const folders = await r.json();
  for (const f of folders) {
    const opt = document.createElement("option");
    opt.value = f.path || f;
    opt.textContent = f.path || f;
    sel.appendChild(opt);
  }
}

$("targetAccount").addEventListener("change", loadFolders);
$("retryBtn").onclick = probeSession;
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
    const r = await apiFetch("/api/upload/chunk", { method: "POST", body: fd });
    if (!r.ok) throw new Error("上传分片失败: " + r.status);
    $("uploadProgress").textContent =
      `上传 ${file.name}: ${i + 1}/${total} 片`;
  }
  return total;
}

$("startBtn").onclick = async () => {
  const files = $("files").files;
  if (!files.length) { alert("请先选择文件"); return; }
  try {
    const init = await (await apiFetch("/api/upload/init", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    })).json();
    const uploadId = init.upload_id;
    const meta = [];
    for (let idx = 0; idx < files.length; idx++) {
      const chunks = await uploadFile(uploadId, idx, files[idx]);
      meta.push({ index: idx, name: files[idx].name, chunks });
    }
    const body = {
      upload_id: uploadId,
      files: meta,
      folder: $("folder").value || "Inbox",
    };
    const ta = $("targetAccount").value.trim();
    if (ta) body.account = ta;
    const r = await apiFetch("/api/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await r.json();
    if (!r.ok) { alert(data.error || "导入失败"); return; }
    $("uploadProgress").textContent = "上传完成,任务已进入队列: " + data.task_id;
    refreshTasks();
  } catch (e) {
    alert(e.message || "上传失败");
  }
};

async function refreshTasks() {
  const r = await apiFetch("/api/tasks");
  if (!r.ok) return;
  const tasks = await r.json();
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
      `<td><div class="bar"><div style="width:${pct}%"></div></div>${t.done}/${t.total}</td>` +
      `<td>${t.failed}</td>`;
    tbody.appendChild(tr);
  }
  if (anyActive && !pollTimer) {
    pollTimer = setInterval(refreshTasks, 3000);
  } else if (!anyActive && pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

function statusText(s) {
  return { queued: "排队中", running: "进行中", done: "完成",
           failed: "失败", interrupted: "中断" }[s] || s;
}

probeSession();
```

- [ ] **Step 4: 烟雾测试 —— 前端文件通过 Flask 提供**

```bash
cd /tmp/11223344/zimport-tools
venv/bin/python - <<'EOF'
import os, tempfile
from zimport_tools.web import create_app
class C:
    secret_key='x'
    temp_root=tempfile.mkdtemp()
    db_path=os.path.join(tempfile.mkdtemp(),'t.db')
    queue_limit=50; max_task_bytes=10**12; chunk_size=1024
    rest_base='https://h:8443'; verify_tls=False
app = create_app(C())
c = app.test_client()
r = c.get('/')
assert r.status_code == 200, ('index', r.status_code)
assert b'ZImport-tools' in r.data, 'title not in index'
assert c.get('/static/app.js').status_code == 200, 'app.js missing'
assert c.get('/static/style.css').status_code == 200, 'style.css missing'
# index 里不应再有 #login id
assert b'id="login"' not in r.data, 'index still contains login form!'
print('smoke OK')
EOF
```

Expected: `smoke OK`

- [ ] **Step 5: JavaScript 语法检查(若 node 可用)**

```bash
which node && node --check zimport_tools/static/app.js && echo "js syntax OK" || echo "(node 不可用,跳过)"
```

Expected: `js syntax OK`(若 node 在),或显示跳过提示。

- [ ] **Step 6: 全量测试无回归**

```bash
venv/bin/python -m pytest tests/ -q
```

Expected: 全部 PASS。

- [ ] **Step 7: 提交**

```bash
git add -A
git commit -m "feat: frontend without login form (cookie-only via Zimbra session)"
```

---

## Task 9: Zimlet 包

构建经典 Zimbra 8.8.15 Zimlet,注册顶层应用页签,内容是指向 `/zimport-tools/` 的 iframe。

**Files:**
- Create: `zimlet/com_msauto_zimport_tools.xml`
- Create: `zimlet/com_msauto_zimport_tools.js`
- Create: `zimlet/com_msauto_zimport_tools.css`
- Create: `zimlet/build.sh`

- [ ] **Step 1: 写 `com_msauto_zimport_tools.xml`**

```xml
<zimlet name="com_msauto_zimport_tools" version="1.0.0" description="ZImport-tools — Zimbra 数据导入">
    <include>com_msauto_zimport_tools.js</include>
    <includeCSS>com_msauto_zimport_tools.css</includeCSS>
    <handlerObject>com_msauto_zimport_tools_HandlerObject</handlerObject>
    <zimletPanelItem label="数据导入" icon="ZimletAlertImg"/>
</zimlet>
```

- [ ] **Step 2: 写 `com_msauto_zimport_tools.js`**

```javascript
function com_msauto_zimport_tools_HandlerObject() {}
com_msauto_zimport_tools_HandlerObject.prototype = new ZmZimletBase();
com_msauto_zimport_tools_HandlerObject.prototype.constructor =
    com_msauto_zimport_tools_HandlerObject;

var Zit = com_msauto_zimport_tools_HandlerObject;

Zit.APP_NAME = "ZIMPORT_TOOLS";
Zit.IFRAME_SRC = "/zimport-tools/";

Zit.prototype.init = function() {
    // Register an application in the top app chooser.
    // The exact ZmApp registration API on Zimbra 8.8.15 may need adjustment
    // (see docs/plan待细化项). The shape below is the standard classic pattern.
    var app = appCtxt.getApp(Zit.APP_NAME);
    if (!app) {
        ZmApp.registerApp(Zit.APP_NAME, {
            nameKey:           "数据导入",
            icon:              "ZimletAlertImg",
            chooserTooltipKey: "数据导入",
            viewTooltipKey:    "数据导入",
            defaultSort:       Number.MAX_VALUE,
            chooserSort:       Number.MAX_VALUE,
        });
    }
};

Zit.prototype.appActive = function(appName, active) {
    if (appName !== Zit.APP_NAME || !active) return;
    var shell = appCtxt.getShell();
    var existing = document.getElementById("zit-iframe-host");
    if (existing) return;  // already created
    var iframe = document.createElement("iframe");
    iframe.id = "zit-iframe-host";
    iframe.src = Zit.IFRAME_SRC;
    iframe.className = "zit-iframe";
    // Attach to the app's content area. Exact attach point is framework-
    // specific; below assumes appCtxt.getAppViewMgr().getAppView is usable.
    var contentEl = shell.getHtmlElement();
    contentEl.appendChild(iframe);
};
```

> **注意:** `ZmApp.registerApp` 和 `appActive` 的具体 API 在 8.8.15 经典 Zimlet 框架下可能需要调整。这一步的"最终验证"在 Task 12 的部署阶段,通过实际 `zmzimletctl deploy` + 浏览器打开页签观察效果完成 —— 如有偏差,据实修正(spec §13 已列为"待细化")。

- [ ] **Step 3: 写 `com_msauto_zimport_tools.css`**

```css
.zit-iframe {
    width: 100%;
    height: calc(100vh - 80px);
    border: 0;
}
```

- [ ] **Step 4: 写 `build.sh`**

```bash
#!/usr/bin/env bash
# 打包 ZImport-tools Zimlet 成可用 zmzimletctl deploy 的 zip。
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$SCRIPT_DIR"
ZIP=com_msauto_zimport_tools.zip
rm -f "$ZIP"
zip -q "$ZIP" \
    com_msauto_zimport_tools.xml \
    com_msauto_zimport_tools.js \
    com_msauto_zimport_tools.css
echo "[zimlet] built $SCRIPT_DIR/$ZIP"
```

- [ ] **Step 5: 验证 XML well-formed、JS 语法**

```bash
cd /tmp/11223344/zimport-tools
venv/bin/python -c "import xml.etree.ElementTree as ET; ET.parse('zimlet/com_msauto_zimport_tools.xml'); print('xml OK')"
which node && node --check zimlet/com_msauto_zimport_tools.js && echo "js OK" || echo "(node 不可用,跳过 js 语法)"
chmod +x zimlet/build.sh
bash -n zimlet/build.sh && echo "build.sh syntax OK"
```

Expected: `xml OK` + `js OK`(或跳过)+ `build.sh syntax OK`

- [ ] **Step 6: 跑构建脚本生成 zip**

```bash
cd /tmp/11223344/zimport-tools
( command -v zip >/dev/null && bash zimlet/build.sh ) || echo "(zip 未安装,跳过实际打包)"
```

Expected: 显示 `[zimlet] built .../com_msauto_zimport_tools.zip`,或显示跳过提示。

- [ ] **Step 7: 提交**(zip 不入库,在 `.gitignore` 加 `zimlet/*.zip`)

```bash
cd /tmp/11223344/zimport-tools
echo "zimlet/*.zip" >> .gitignore
git add -A
git update-index --chmod=+x zimlet/build.sh
git commit -m "feat: classic Zimlet package that hosts ZImport-tools in Zimbra Web"
```

---

## Task 10: 部署脚本(setup / setup-proxy / release / systemd / run_web)

把 ZImport 的部署脚本复制并改名 `zimport` → `zimport-tools`(系统路径)+ `zimport` → `zimport_tools`(Python 模块)。

**Files:**
- Create: `deploy/run_web.py`
- Create: `deploy/zimport-tools-web.service`
- Create: `deploy/zimport-tools-worker.service`
- Create: `deploy/setup.sh`
- Create: `deploy/setup-proxy.sh`
- Create: `deploy/release.sh`
- Create: `deploy/README.md`

- [ ] **Step 1: 复制源文件**

```bash
SRC=/tmp/11223344/zimport/deploy
DST=/tmp/11223344/zimport-tools/deploy
cp "$SRC/run_web.py"             "$DST/run_web.py"
cp "$SRC/zimport-web.service"    "$DST/zimport-tools-web.service"
cp "$SRC/zimport-worker.service" "$DST/zimport-tools-worker.service"
cp "$SRC/setup.sh"               "$DST/setup.sh"
cp "$SRC/setup-proxy.sh"         "$DST/setup-proxy.sh"
cp "$SRC/release.sh"             "$DST/release.sh"
cp "$SRC/README.md"              "$DST/README.md"
chmod +x "$DST/setup.sh" "$DST/setup-proxy.sh" "$DST/release.sh"
```

- [ ] **Step 2: 改路径与名字**

```bash
cd /tmp/11223344/zimport-tools/deploy
# 系统路径 + 单元/用户名(横线)
sed -i \
  -e 's|/opt/zimport|/opt/zimport-tools|g' \
  -e 's|/etc/zimport|/etc/zimport-tools|g' \
  -e 's|/var/lib/zimport|/var/lib/zimport-tools|g' \
  -e 's|\buser=zimport\b|user=zimport-tools|g' \
  -e 's|\bzimport-web\b|zimport-tools-web|g' \
  -e 's|\bzimport-worker\b|zimport-tools-worker|g' \
  *.sh *.service README.md run_web.py
# Python 模块路径(下划线)
sed -i \
  -e 's|\bfrom zimport\.|from zimport_tools.|g' \
  -e 's|\bpython -m zimport\.worker\b|python -m zimport_tools.worker|g' \
  *.sh *.service run_web.py
# release.sh 里的包名 / tag 前缀(若有 `zimport-` 字面量)
sed -i 's|\bzimport-${VERSION}\b|zimport-tools-${VERSION}|g' release.sh
sed -i 's|\bzimport-X\.Y\.Z\b|zimport-tools-X.Y.Z|g' release.sh
# release.sh 改 __init__.py 路径(若有写死的 zimport/__init__.py)
sed -i 's|\bzimport/__init__\.py\b|zimport_tools/__init__.py|g' release.sh
```

> 改完后**用 `git diff` 检查**每个文件,确认没误改。如发现遗漏(如 README.md 里仍有 `/opt/zimport`),手工补 sed。

- [ ] **Step 3: 语法 / 解析检查**

```bash
cd /tmp/11223344/zimport-tools
for f in deploy/*.sh; do bash -n "$f" && echo "$f OK"; done
venv/bin/python -m py_compile deploy/run_web.py && echo "run_web.py OK"
venv/bin/python -c "import configparser; [configparser.ConfigParser().read(f) for f in ['deploy/zimport-tools-web.service','deploy/zimport-tools-worker.service']]; print('services OK')"
```

Expected: 各文件 OK。

- [ ] **Step 4: 全量测试无回归**

```bash
venv/bin/python -m pytest tests/ -q
```

Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add -A
git update-index --chmod=+x deploy/setup.sh deploy/setup-proxy.sh deploy/release.sh
git commit -m "feat: deploy scripts adapted from ZImport (zimport-tools paths)"
```

---

## Task 11: README + v1.0.0 准备

写正式 README、CHANGELOG 写入 v1.0.0 段落,准备 release.sh 发版。

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 写正式 `README.md`**

```markdown
# ZImport-tools

ZImport 的 Zimbra 内置工具版 —— 作为 Zimbra Web 应用栏里的「数据导入」页签存在,
直接信任 Zimbra 会话 cookie,**无独立登录步骤**。

姊妹项目:[ZImport](https://github.com/jiulin-hou/ZImport) 是独立 Web 工具形态。
两者并行维护、独立版本线。

## 它解决什么问题

用户已经登录在 Zimbra Web,不应该为了导入邮件再单独登录一次;独立 Web 工具会额外
新增公网暴露面。ZImport-tools 把导入做成 Zimbra Web 里的内置功能:共用 Zimbra 会话、
不新增公网攻击面、不再二次登录。

## 功能

- 多 `.eml` 文件 / 大体积 `.tgz`(>5GB,分片上传 + 断点续传)
- 自动 Message-ID 双层去重
- 后台串行 worker,任务队列持久化,关页签也不丢
- 失败任务可重试;管理员可指定目标账户
- 服务端解包归一化,从根本规避 Zimbra 导入器的 PaxHeader 故障

## 架构

- 单页前端 + Flask 后端 + 独立 worker 进程(同 ZImport)
- **前端登录**:从 Zimbra `ZM_AUTH_TOKEN` cookie 直接识别,**无登录表单**
- **管理员 SOAP 操作**(账户搜索 / 委托认证)统一走配置的服务账号
- Zimlet 在 Zimbra Web 应用栏注册「数据导入」页签,内容 = iframe `/zimport-tools/`

详细设计见 [`docs/superpowers/specs/2026-05-23-zimport-tools-design.md`](docs/superpowers/specs/2026-05-23-zimport-tools-design.md)(部署后从 ZImport 仓库复制过来)。

## 在新机器上下载与部署

### 1. 获取代码

    git clone https://github.com/jiulin-hou/ZImport-tools.git
    cd ZImport-tools

### 2. 一键环境准备

    sudo bash deploy/setup.sh

(并行装 Python 3.11、建 venv、放配置模板;不动系统 python3,对 Zimbra 无影响)

### 3. 反代到 Zimbra 同域名

    sudo bash deploy/setup-proxy.sh --path /zimport-tools

`ZM_AUTH_TOKEN` cookie 才会被自动带到 ZImport-tools 后端。

### 4. 部署 Zimlet

    cd zimlet && bash build.sh
    su - zimbra -c "zmzimletctl deploy $(pwd)/com_msauto_zimport_tools.zip"

Zimbra Web 应用栏自动出现「数据导入」页签。

### 5. 完成手工步骤

`setup.sh` 跑完会打印剩下步骤(填配置、建 Zimbra 服务账号、启动 systemd 服务)。
详见 [`deploy/README.md`](deploy/README.md)。

## 使用

1. 登录 Zimbra Web
2. 点顶部应用栏的「数据导入」页签
3. (管理员)填目标账户,或留空导入到自己;选目标文件夹
4. 选多个 `.eml` 或一个 `.tgz`,点「开始导入」
5. 任务在「我的任务」表里看进度;关页签稍后再看也行

## 发版

编辑 `CHANGELOG.md` 加新版本段落,然后:

    bash deploy/release.sh X.Y.Z

## 目录结构

    zimport_tools/  后端模块 + 前端 static/
    zimlet/         Zimbra Zimlet 包(经典 8.8.15 框架)
    tests/          单元 + 集成测试
    deploy/         setup.sh / setup-proxy.sh / release.sh / systemd 单元
```

- [ ] **Step 2: 写 `CHANGELOG.md` 的 v1.0.0 段落**(放在指南段落下面)

`CHANGELOG.md` 的内容(整体替换):
```markdown
# 更新日志

版本号遵循语义化版本(主.次.补丁)。发版流程:

1. 在本文件顶部加一条新版本记录(`## vX.Y.Z — 日期` 加改动条目)
2. 运行 `bash deploy/release.sh X.Y.Z` —— 自动跑测试、写版本号、提交、
   打 tag、推送 main 与 tag、生成 `dist/zimport-tools-X.Y.Z.tar.gz`

## v1.0.0 — 2026-05-23

首个版本。从 ZImport main HEAD 派生,作为独立姊妹项目维护。

**与 ZImport 的差异:**

- **无独立登录** —— 移除 `/api/login` 与登录表单;只通过 Zimbra `ZM_AUTH_TOKEN`
  cookie 识别身份(`zimbra_session.validate` → `GetInfoRequest`)
- **CSRF 防护** —— 状态变更端点要求 `X-Zimport-CSRF: 1` 头 + `Origin` 校验
- **账户切换串号防护** —— session 中保存 cookie token 的 hash,token 变化即重建 session
- **token 验证缓存** —— LRU 1024 条,正缓存 5 分钟、负缓存 30 秒,保护 Zimbra QPS
- **Zimlet 应用页签** —— 在 Zimbra Web 顶部应用栏注册「数据导入」页签,iframe 内嵌 ZImport-tools 页面
- **部署适配** —— 系统路径 `/opt/zimport-tools` 等;反代路径默认 `/zimport-tools/`;
  systemd 单元改名 `zimport-tools-web.service` / `zimport-tools-worker.service`

**继承自 ZImport main HEAD 的功能(初始基线复制,之后各自演进):**

- 多 eml + 大 tgz 分片上传与断点续传
- 服务端解包归一化,规避 PaxHeader 故障
- SQLite 任务队列、后台串行 worker、进度持久化、保留期自动清理
- Message-ID 双层去重、transient 失败自动重试、单封失败可重试
- 文件夹下拉(`/api/folders`)、管理员目标账户 autocomplete(`/api/admin/accounts/search`)
- systemd 部署 + 环境准备脚本 `deploy/setup.sh`
```

- [ ] **Step 3: 全量测试再跑一次**

```bash
cd /tmp/11223344/zimport-tools
venv/bin/python -m pytest tests/ -q
```

Expected: 全部 PASS。

- [ ] **Step 4: 提交**(注意:暂不要 `release.sh` —— 还没配 remote,无法 push)

```bash
git add -A
git commit -m "docs: README and CHANGELOG for v1.0.0"
```

---

## Task 12: 配置 GitHub 远程 + 推送 v1.0.0

最后一步:配 remote、推 `main` 与 `v1.0.0` 标签、生成版本化交付包。

**前置(由 user 完成,不是 executor):**
1. user 在 GitHub 上手工建一个**空仓库** `jiulin-hou/ZImport-tools`(不勾 README/license/.gitignore)
2. user 把 ZImport 的同一个 deploy key 加到新仓的 Deploy keys(Settings → Deploy keys → Add deploy key,粘贴 `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOZ+6s3OpQqxpF4+PF++HAlm0i5hLv9T+5BnP3u55SMV zimport-deploy`,勾 Allow write access)

> 这两步 executor 完成不了,需要 user 在 GitHub 网页上做。executor 在开始 Task 12 前必须先确认 user 已完成 —— 若未完成,Task 12 暂停。

**Files:** 无新文件,只有 git 操作

- [ ] **Step 1: 确认前置已完成**(询问 user 是否已建仓 + 加 deploy key)

如果 user 还没建,**停在这里**等待。建好后继续。

- [ ] **Step 2: 配 remote(用 ssh:// 完整形式,绕开 ZImport 仓库历史上那条 `url.https://github.com/.insteadof git@github.com:` 全局改写规则)**

```bash
cd /tmp/11223344/zimport-tools
git remote add origin ssh://git@github.com/jiulin-hou/ZImport-tools.git
git config core.sshCommand "ssh -i ~/.ssh/id_zimport_ed25519 -o IdentitiesOnly=yes"
git ls-remote --get-url origin
```

Expected 最后一行:`ssh://git@github.com/jiulin-hou/ZImport-tools.git`

- [ ] **Step 3: 用 release.sh 发 v1.0.0**

`release.sh` 已经会跑测试 + 写版本号 + 提交 + 打 tag + 推送 + 打包。但**先**测一下能不能 push(空仓首推):

```bash
git push -u origin main 2>&1 | tail -5
```

Expected: `* [new branch] main -> main`

然后跑 release(`release.sh` 会再产生一个 `chore: release v1.0.0` 提交,把 `__version__` 写成 `1.0.0`、打 tag、再推一次):

```bash
bash deploy/release.sh 1.0.0
```

Expected: 输出包含 `发版完成: v1.0.0` 与交付包路径 `dist/zimport-tools-1.0.0.tar.gz`。

- [ ] **Step 4: 验证远程**

```bash
git ls-remote origin 2>&1 | head
```

Expected: `refs/heads/main` 与 `refs/tags/v1.0.0` 都存在,且 hash 匹配本地。

- [ ] **Step 5: 验证交付包内容**

```bash
ls -lh dist/zimport-tools-1.0.0.tar.gz
tar tzf dist/zimport-tools-1.0.0.tar.gz | head -20
```

Expected: 包大小合理(~50KB 左右),内部以 `zimport-tools/` 为前缀,含 `zimport_tools/`、`zimlet/`、`deploy/`、`tests/`、`README.md`、`CHANGELOG.md` 等。

- [ ] **Step 6: 完成报告**

汇报给 user:
- GitHub 仓库 URL
- `main` 与 `v1.0.0` 的 commit hash
- 交付包绝对路径
- 部署到 Zimbra 服务器的下一步建议

---

## 自检结论

**Spec 覆盖(逐节核对 `2026-05-23-zimport-tools-design.md`):**

- §1 背景 / §2 非目标 → README + CHANGELOG 体现
- §3 总体架构 → Task 6 (web.py + cookie 认证) + Task 9 (Zimlet)
- §4 仓库结构 → Task 1–10 按结构逐项落地
- §5 数据流 → Task 6/7/8 实现完整流程
- §6 cookie-only 认证 + 三项关键决策(缓存、GetInfoRequest 推导身份、账户切换) → Task 5 (zimbra_session) + Task 6 (web.py 装饰器 + token-hash 比对)
- §7 CSRF 防护(自定义头 + Origin + Flask session cookie 加固) → Task 6 (`_csrf_check`)
- §8 "对任务/服务器/质量负责" → 继承自 ZImport(Task 2/3/4 复制),CSRF/缓存/账户切换在 Task 5/6 实现
- §9 错误处理表 → Task 6 实现 + Task 8 前端兜底
- §10 测试 → Task 5/6/7 单元测试;手工验收 = Task 12 部署后 user 验
- §11 部署与回滚 → Task 10 (脚本) + Task 12 (实际部署 = user)
- §12 版本与发布 → Task 11 (CHANGELOG) + Task 12 (release.sh)
- §13 待细化项 → Task 9 步骤注释里点名了 ZmApp.registerApp 等具体 API 在部署阶段验证

**占位符:** 无 TBD/TODO;"待细化"项明确写在 Task 9 Step 2 / Task 11 CHANGELOG 中,作为部署阶段的验证点,不是计划缺口。

**类型/命名一致性:**
- `Identity(is_admin, account)` 在 zimbra_auth / zimbra_session / web.py / tests 中字段名一致
- `X-Zimport-CSRF: 1` 在 web.py、app.js、tests、spec 中拼写一致
- `ZM_AUTH_TOKEN` cookie 名一致
- `zimport_tools` Python 包名贯穿
- `/opt/zimport-tools`、`/etc/zimport-tools`、`/var/lib/zimport-tools` 系统路径一致
- `zimport-tools-web.service` / `zimport-tools-worker.service` systemd 单元名一致
- `com_msauto_zimport_tools` Zimlet 名一致

**范围:** 单一姊妹项目,12 任务可一次性完成;无需进一步分解。
