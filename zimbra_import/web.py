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
