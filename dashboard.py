from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from src.services.dashboard_action_service import DashboardActionService
from src.services.dashboard_service import DashboardDataService


BASE_DIR = Path(__file__).resolve().parent


def _resolve_terminals_directory() -> str | None:
    env_value = os.environ.get("DASHBOARD_TERMINALS_DIR")
    if env_value:
        return env_value

    project_name = str(BASE_DIR).replace(":", "").replace("\\", "-").replace("/", "-")
    default_path = Path.home() / ".cursor" / "projects" / project_name / "terminals"
    if default_path.exists():
        return str(default_path)
    return None


def create_app(
    service: DashboardDataService | None = None,
    action_service: DashboardActionService | None = None,
) -> Flask:
    terminals_directory = _resolve_terminals_directory()
    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "web" / "templates"),
        static_folder=str(BASE_DIR / "web" / "static"),
        static_url_path="/static",
    )
    data_service = service or DashboardDataService(
        project_root=BASE_DIR,
        terminals_directory=terminals_directory,
    )
    dashboard_action_service = action_service or DashboardActionService(
        terminals_directory=terminals_directory,
    )

    @app.after_request
    def add_no_cache_headers(response):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return response

    @app.get("/")
    def index():
        return render_template("dashboard.html")

    @app.get("/api/dashboard/snapshot")
    def snapshot():
        return jsonify(data_service.build_snapshot())

    @app.post("/api/dashboard/action")
    def dashboard_action():
        payload = request.get_json(silent=True) or {}
        action = str(payload.get("action", "") or "").strip()
        action_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        confirmed = bool(payload.get("confirmed", False))
        if not action:
            return jsonify({"success": False, "message": "缺少动作标识"}), 400
        try:
            result = dashboard_action_service.execute(action, payload=action_payload, confirmed=confirmed)
            result["snapshot"] = data_service.build_snapshot()
            return jsonify(result)
        except ValueError as exc:
            return jsonify({"success": False, "message": str(exc)}), 400
        except Exception as exc:
            return jsonify({"success": False, "message": f"动作执行失败: {exc}"}), 500

    @app.get("/api/dashboard/tasks")
    def dashboard_tasks():
        tasks = []
        if hasattr(dashboard_action_service, "task_runner"):
            tasks = dashboard_action_service.task_runner.list_tasks(limit=20)
        return jsonify({"tasks": tasks})

    return app


if __name__ == "__main__":
    host = os.environ.get("DASHBOARD_HOST", "127.0.0.1")
    port = int(os.environ.get("DASHBOARD_PORT", "8501"))
    create_app().run(host=host, port=port, debug=False)
