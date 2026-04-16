from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, jsonify, render_template, request

# CORS支持（可选依赖）
try:
    from flask_cors import CORS
    _cors_available = True
except ImportError:
    _cors_available = False

from src.services.dashboard_action_service import DashboardActionService
from src.services.dashboard_service import DashboardDataService

# AI服务（可选依赖）
_ai_import_error: str | None = None
try:
    from src.services.ai_service import AIService
    _ai_available = True
except Exception as exc:
    _ai_available = False
    _ai_import_error = str(exc)

# AI管家服务（可选依赖）
try:
    from src.services.ai_butler_service import AIButlerService
    _butler_available = True
except ImportError:
    _butler_available = False


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

    # 启用CORS（云服务器跨域访问需要）
    if _cors_available:
        CORS(app, resources={r"/api/*": {"origins": "*"}})

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

    # === AI助手接口 ===
    if _ai_available:
        ai_service = AIService()

        @app.get("/api/ai/status")
        def ai_status():
            return jsonify(ai_service.get_status())

        @app.post("/api/ai/chat")
        def ai_chat():
            payload = request.get_json(silent=True) or {}
            user_input = str(payload.get("message", "") or "").strip()
            context = payload.get("context")
            session_id = str(payload.get("session_id", "") or "").strip() or None
            if not user_input:
                return jsonify({"success": False, "message": "消息不能为空"}), 400
            try:
                response = ai_service.chat(user_input, context=context, session_id=session_id)
                return jsonify({"success": True, "response": response})
            except Exception as exc:
                return jsonify({"success": False, "message": f"AI对话失败: {exc}"}), 500

        @app.post("/api/ai/quick-ask")
        def ai_quick_ask():
            payload = request.get_json(silent=True) or {}
            prompt_key = str(payload.get("key", "") or "").strip()
            session_id = str(payload.get("session_id", "") or "").strip() or None
            if not prompt_key:
                return jsonify({"success": False, "message": "缺少预设问题key"}), 400
            try:
                response = ai_service.quick_ask(prompt_key, session_id=session_id)
                return jsonify({"success": True, "response": response})
            except Exception as exc:
                return jsonify({"success": False, "message": f"AI问答失败: {exc}"}), 500

        @app.post("/api/ai/explain-selection")
        def ai_explain_selection():
            payload = request.get_json(silent=True) or {}
            stock_list = payload.get("stocks", [])
            factors = payload.get("factors")
            market_context = payload.get("market_context")
            try:
                response = ai_service.explain_selection(stock_list, factors, market_context)
                return jsonify({"success": True, "response": response})
            except Exception as exc:
                return jsonify({"success": False, "message": f"选股解释失败: {exc}"}), 500

        @app.post("/api/ai/analyze-signal")
        def ai_analyze_signal():
            payload = request.get_json(silent=True) or {}
            stock_code = payload.get("code", "")
            stock_name = payload.get("name", "")
            signal_data = payload.get("signal", {})
            try:
                response = ai_service.analyze_signal(stock_code, stock_name, signal_data)
                return jsonify({"success": True, "response": response})
            except Exception as exc:
                return jsonify({"success": False, "message": f"信号分析失败: {exc}"}), 500

        @app.post("/api/ai/analyze-news")
        def ai_analyze_news():
            payload = request.get_json(silent=True) or {}
            news_list = payload.get("news", [])
            holdings = payload.get("holdings")
            try:
                response = ai_service.analyze_news(news_list, holdings)
                return jsonify({"success": True, "response": response})
            except Exception as exc:
                return jsonify({"success": False, "message": f"新闻分析失败: {exc}"}), 500

        @app.post("/api/ai/generate-code")
        def ai_generate_code():
            payload = request.get_json(silent=True) or {}
            description = str(payload.get("description", "") or "").strip()
            framework = payload.get("framework", "pandas")
            if not description:
                return jsonify({"success": False, "message": "策略描述不能为空"}), 400
            try:
                response = ai_service.generate_code(description, framework)
                return jsonify({"success": True, "response": response})
            except Exception as exc:
                return jsonify({"success": False, "message": f"代码生成失败: {exc}"}), 500

        @app.post("/api/ai/clear-history")
        def ai_clear_history():
            payload = request.get_json(silent=True) or {}
            session_id = str(payload.get("session_id", "") or "").strip() or None
            ai_service.clear_chat_history(session_id=session_id)
            return jsonify({"success": True})

        @app.get("/api/ai/history")
        def ai_history():
            session_id = str(request.args.get("session_id", "") or "").strip() or None
            limit = request.args.get("limit", 50)
            try:
                limit_int = int(limit)
            except Exception:
                limit_int = 50
            return jsonify({"history": ai_service.get_chat_history(session_id=session_id, limit=limit_int)})
    else:
        app.logger.warning("AI routes disabled because AIService import failed: %s", _ai_import_error)

        @app.get("/api/ai/status")
        def ai_status_unavailable():
            return jsonify(
                {
                    "enabled": False,
                    "available": False,
                    "message": "AI service unavailable in current dashboard runtime.",
                    "import_error": _ai_import_error,
                }
            )

        @app.post("/api/ai/chat")
        def ai_chat_unavailable():
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "AI service unavailable, please check dashboard runtime dependencies.",
                        "import_error": _ai_import_error,
                    }
                ),
                503,
            )

        @app.post("/api/ai/quick-ask")
        def ai_quick_ask_unavailable():
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "AI service unavailable, please check dashboard runtime dependencies.",
                        "import_error": _ai_import_error,
                    }
                ),
                503,
            )

    # === AI管家接口 ===
    if _butler_available:
        butler_service = AIButlerService()

        if not os.environ.get("PYTEST_CURRENT_TEST"):
            auto_start = True
            try:
                import yaml

                cfg_path = BASE_DIR / "config" / "ai_config.yaml"
                if cfg_path.exists():
                    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
                    auto_start = bool((cfg.get("ai", {}) or {}).get("butler", {}).get("auto_start", True))
            except Exception:
                app.logger.exception("Failed to read ai_config.yaml for butler auto-start")

            if auto_start:
                try:
                    butler_service.start()
                    app.logger.info("AI butler auto-started on dashboard boot")
                except Exception:
                    app.logger.exception("Failed to auto-start AI butler from dashboard")

        @app.get("/api/butler/status")
        def butler_status():
            return jsonify(butler_service.get_status())

        @app.post("/api/butler/start")
        def butler_start():
            try:
                butler_service.start()
                return jsonify({"success": True, "message": "AI管家服务已启动"})
            except Exception as exc:
                return jsonify({"success": False, "message": f"启动失败: {exc}"}), 500

        @app.post("/api/butler/stop")
        def butler_stop():
            butler_service.stop()
            return jsonify({"success": True, "message": "AI管家服务已停止"})

        @app.post("/api/butler/briefing")
        def butler_briefing():
            """生成盘前简报"""
            payload = request.get_json(silent=True) or {}
            try:
                result = butler_service.generate_briefing_now(
                    yesterday_review=payload.get("yesterday_review"),
                    today_selection=payload.get("today_selection"),
                    overnight_news=payload.get("overnight_news"),
                    data_status=payload.get("data_status"),
                )
                return jsonify({"success": True, "result": result})
            except Exception as exc:
                return jsonify({"success": False, "message": f"简报生成失败: {exc}"}), 500

        @app.post("/api/butler/monitor")
        def butler_monitor():
            """执行盘中监控"""
            payload = request.get_json(silent=True) or {}
            try:
                result = butler_service.do_intraday_monitor_now(
                    holdings=payload.get("holdings"),
                    signals=payload.get("signals"),
                    market_status=payload.get("market_status"),
                )
                return jsonify({"success": True, "result": result})
            except Exception as exc:
                return jsonify({"success": False, "message": f"监控执行失败: {exc}"}), 500

        @app.post("/api/butler/review")
        def butler_review():
            """生成盘后复盘"""
            payload = request.get_json(silent=True) or {}
            try:
                result = butler_service.generate_review_now(
                    today_trades=payload.get("today_trades"),
                    today_signals=payload.get("today_signals"),
                    holdings=payload.get("holdings"),
                    market_summary=payload.get("market_summary"),
                )
                return jsonify({"success": True, "result": result})
            except Exception as exc:
                return jsonify({"success": False, "message": f"复盘生成失败: {exc}"}), 500

        @app.post("/api/butler/risk-check")
        def butler_risk_check():
            """执行风险检查"""
            payload = request.get_json(silent=True) or {}
            try:
                result = butler_service.do_risk_check_now(
                    holdings=payload.get("holdings", []),
                    market_data=payload.get("market_data", {}),
                )
                return jsonify({"success": True, "result": result})
            except Exception as exc:
                return jsonify({"success": False, "message": f"风险检查失败: {exc}"}), 500

        @app.post("/api/butler/signal-analysis")
        def butler_signal_analysis():
            """信号实时分析"""
            payload = request.get_json(silent=True) or {}
            signal = payload.get("signal", {})
            stock_info = payload.get("stock_info", {})
            position = payload.get("position")
            try:
                result = butler_service.on_signal_triggered(signal, stock_info, position)
                return jsonify({"success": True, "result": result})
            except Exception as exc:
                return jsonify({"success": False, "message": f"信号分析失败: {exc}"}), 500

        @app.get("/api/butler/last-briefing")
        def butler_last_briefing():
            return jsonify({"briefing": butler_service.get_last_briefing()})

        @app.get("/api/butler/last-review")
        def butler_last_review():
            return jsonify({"review": butler_service.get_last_review()})

    return app


if __name__ == "__main__":
    host = os.environ.get("DASHBOARD_HOST", "0.0.0.0")
    port = int(os.environ.get("DASHBOARD_PORT", "8501"))
    create_app().run(host=host, port=port, debug=False)
