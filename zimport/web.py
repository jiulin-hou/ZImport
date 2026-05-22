import os
import re
import shutil
import functools

from flask import Flask, request, session, jsonify, send_from_directory

from zimport import (zimbra_auth, zimbra_folders, zimbra_search,
                     uploads, archive)
from zimport.store import TaskStore

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

    @app.route("/api/me")
    @login_required
    def me():
        return jsonify({"account": session["account"],
                        "is_admin": session.get("is_admin", False)})

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

    @app.route("/api/folders")
    @login_required
    def folders():
        account = request.args.get("account") or session["account"]
        if account != session["account"] and not session.get("is_admin"):
            return jsonify({"error": "无权查询此账户"}), 403
        try:
            tok = zimbra_auth.delegate_token(cfg, account)
            paths = zimbra_folders.list_folders(cfg, tok)
            return jsonify({"folders": paths})
        except (zimbra_auth.AuthError,
                zimbra_folders.FolderError) as exc:
            return jsonify({"error": str(exc)}), 502

    @app.route("/api/admin/accounts/search")
    @login_required
    def admin_account_search():
        if not session.get("is_admin"):
            return jsonify({"error": "仅管理员可用"}), 403
        q = request.args.get("q", "")
        try:
            results = zimbra_search.search_accounts(cfg, q)
            return jsonify({"accounts": results})
        except zimbra_search.SearchError as exc:
            return jsonify({"error": str(exc)}), 502

    # 上传与导入端点在 Task 13 / 14 注册
    _register_uploads(app, cfg, store, login_required)
    _register_import(app, cfg, store, login_required)
    return app


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
        if not _valid_upload_id(upload_id):
            return jsonify({"error": "无效的 upload_id"}), 400
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
        if not _valid_upload_id(upload_id):
            return jsonify({"error": "无效的 upload_id"}), 400
        file_index = int(request.args["file_index"])
        total = int(request.args["total_chunks"])
        missing = uploads.missing_chunks(cfg.temp_root, upload_id,
                                         file_index, total)
        return jsonify({"missing": missing})


_UPLOAD_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _valid_upload_id(upload_id):
    return bool(upload_id) and bool(_UPLOAD_ID_RE.match(upload_id))


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
        if not _valid_upload_id(upload_id):
            return jsonify({"error": "无效的 upload_id"}), 400
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
