import json
import sqlite3
from datetime import datetime

from dashboard import create_app
from src.services.dashboard_action_record_service import DashboardActionRecordService
from src.services.dashboard_action_service import DashboardActionService
from src.services.dashboard_service import DashboardDataService


class DummyDashboardService:
    def build_snapshot(self):
        return {"meta": {"app_name": "test-app"}, "overview": {"metrics": []}}


class DummyDashboardActionService:
    def execute(self, action, payload=None, confirmed=False):
        return {
            "success": True,
            "action": action,
            "message": f"{action} done",
            "payload": {"stage_target": "preMarketSection", "echo_payload": payload or {}, "confirmed": confirmed},
        }

    @property
    def task_runner(self):
        class _Runner:
            @staticmethod
            def list_tasks(limit=20):
                return [{"task_id": "demo", "action_label": "示例任务", "status": "success", "message": "ok"}][:limit]

        return _Runner()


class DummyOfflineDashboardActionService:
    def execute(self, action, payload=None, confirmed=False):
        return {
            "success": True,
            "action": action,
            "message": "已进入盘中盯盘状态，但当前未检测到实时监控在线。请确保 `main.py` 或 `run_service.py` 正在运行。",
            "payload": {
                "runtime_state": {
                    "runtime_online": False,
                    "status_label": "未检测到实时监控",
                }
            },
        }


class DummyDegradedDashboardActionService:
    def execute(self, action, payload=None, confirmed=False):
        return {
            "success": True,
            "action": action,
            "message": "盘中状态已刷新，但当前监控可用性不足：数据源已降级。",
            "payload": {
                "runtime_state": {
                    "runtime_online": True,
                    "runtime_usable": False,
                    "status_label": "数据源已降级",
                }
            },
        }


def test_dashboard_routes_render():
    app = create_app(
        service=DummyDashboardService(),
        action_service=DummyDashboardActionService(),
    )
    client = app.test_client()

    response = client.get("/")
    assert response.status_code == 200
    assert "量化交易辅助看板" in response.get_data(as_text=True)

    api_response = client.get("/api/dashboard/snapshot")
    assert api_response.status_code == 200
    assert api_response.get_json()["meta"]["app_name"] == "test-app"

    action_response = client.post("/api/dashboard/action", json={"action": "generate_plan"})
    assert action_response.status_code == 200
    payload = action_response.get_json()
    assert payload["success"] is True
    assert payload["message"] == "generate_plan done"
    assert payload["snapshot"]["meta"]["app_name"] == "test-app"

    tasks_response = client.get("/api/dashboard/tasks")
    assert tasks_response.status_code == 200
    assert tasks_response.get_json()["tasks"][0]["task_id"] == "demo"


def test_dashboard_action_requires_action_name():
    app = create_app(
        service=DummyDashboardService(),
        action_service=DummyDashboardActionService(),
    )
    client = app.test_client()

    response = client.post("/api/dashboard/action", json={})
    assert response.status_code == 400
    assert response.get_json()["success"] is False


def test_dashboard_action_accepts_payload_and_confirm_flag():
    app = create_app(
        service=DummyDashboardService(),
        action_service=DummyDashboardActionService(),
    )
    client = app.test_client()

    response = client.post(
        "/api/dashboard/action",
        json={"action": "clear_candidate_pool", "payload": {"scope": "candidate"}, "confirmed": True},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["payload"]["echo_payload"]["scope"] == "candidate"
    assert payload["payload"]["confirmed"] is True


def test_dashboard_action_accepts_push_strategy_payload():
    app = create_app(
        service=DummyDashboardService(),
        action_service=DummyDashboardActionService(),
    )
    client = app.test_client()

    response = client.post(
        "/api/dashboard/action",
        json={"action": "push_selection_wecom", "payload": {"strategy": "secondary_launch"}},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["payload"]["echo_payload"]["strategy"] == "secondary_launch"


def test_dashboard_action_can_return_runtime_offline_hint():
    app = create_app(
        service=DummyDashboardService(),
        action_service=DummyOfflineDashboardActionService(),
    )
    client = app.test_client()

    response = client.post("/api/dashboard/action", json={"action": "start_intraday_watch"})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert "未检测到实时监控在线" in payload["message"]


def test_dashboard_action_can_return_runtime_degraded_hint():
    app = create_app(
        service=DummyDashboardService(),
        action_service=DummyDegradedDashboardActionService(),
    )
    client = app.test_client()

    response = client.post("/api/dashboard/action", json={"action": "refresh_intraday_status"})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert "监控可用性不足" in payload["message"]


def test_dashboard_service_builds_snapshot(tmp_path):
    quant_db = tmp_path / "quant.db"
    history_db = tmp_path / "history.db"
    candidate_cache = tmp_path / "candidate_pool.json"
    virtual_cache = tmp_path / "virtual_trades.json"
    terminals_dir = tmp_path / "terminals"
    terminals_dir.mkdir()

    conn = sqlite3.connect(quant_db)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE hold_stock (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_code TEXT,
            name TEXT,
            hold_price REAL,
            hold_num INTEGER,
            hold_date TEXT,
            status INTEGER,
            update_time TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE stock_daily (
            ts_code TEXT,
            trade_date TEXT,
            close REAL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE signal_history (
            ts_code TEXT,
            name TEXT,
            signal_type TEXT,
            signal_time TEXT,
            trigger_reason TEXT,
            suggestion TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE signal_feedback_run (
            run_id TEXT,
            start_date TEXT,
            end_date TEXT,
            recommendation_count INTEGER,
            signal_count INTEGER,
            detail_count INTEGER,
            summary_count INTEGER,
            meta_json TEXT,
            created_time TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE signal_feedback_summary (
            source_type TEXT,
            direction TEXT,
            horizon INTEGER,
            sample_count INTEGER,
            win_rate REAL,
            mean_gross_return REAL,
            mean_net_return REAL,
            median_net_return REAL,
            p25_net_return REAL,
            p75_net_return REAL,
            mean_mfe REAL,
            mean_mae REAL,
            run_id TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE health_snapshot (
            snapshot_time TEXT,
            source TEXT,
            uptime_seconds REAL,
            success_total INTEGER,
            incident_total INTEGER,
            severity_json TEXT,
            component_status_json TEXT,
            latency_summary_json TEXT,
            snapshot_json TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE runtime_incident (
            incident_time TEXT,
            title TEXT,
            message TEXT,
            severity TEXT,
            category TEXT,
            component TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE dashboard_action_record (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_key TEXT,
            status TEXT,
            message TEXT,
            payload_json TEXT,
            created_time TEXT
        )
        """
    )

    cur.execute(
        "INSERT INTO hold_stock (ts_code, name, hold_price, hold_num, hold_date, status, update_time) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("600519.SH", "贵州茅台", 1500.0, 100, "2026-03-20", 1, "2026-03-28 15:00:00"),
    )
    cur.execute(
        "INSERT INTO stock_daily (ts_code, trade_date, close) VALUES (?, ?, ?)",
        ("600519.SH", "20260328", 1525.0),
    )
    cur.execute(
        "INSERT INTO signal_history (ts_code, name, signal_type, signal_time, trigger_reason, suggestion) VALUES (?, ?, ?, ?, ?, ?)",
        ("600519.SH", "贵州茅台", "买点触发", "2026-03-28 10:10:00", "放量突破", "关注买入"),
    )
    cur.execute(
        "INSERT INTO signal_feedback_run VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "run_1",
            "20260301",
            "20260328",
            120,
            30,
            300,
            3,
            json.dumps(
                {
                    "recommendation_count": 120,
                    "signal_meta": {
                        "signal_type_stats": [
                            {
                                "signal_type": "secondary_launch_breakout",
                                "direction": "buy",
                                "horizon": 1,
                                "sample_count": 12,
                                "win_rate": 0.75,
                                "mean_net_return": 0.023,
                            }
                        ],
                        "window_stats": [
                            {
                                "signal_type": "secondary_launch_breakout",
                                "direction": "buy",
                                "window_minutes": 5,
                                "sample_count": 10,
                                "win_rate": 0.7,
                                "mean_net_return": 0.008,
                            }
                        ],
                        "insights": {
                            "conclusions": [
                                "当前盘中最优子类型为 `secondary_launch_breakout`，样本 `12` 条，胜率 `75.00%`，平均净收益 `2.30%`。"
                            ],
                            "action_items": [
                                "优先保留并加权 `secondary_launch_breakout`，可作为二次启动主推送形态。"
                            ],
                            "best_window": {
                                "signal_type": "secondary_launch_breakout",
                                "window_minutes": 5,
                            },
                        },
                    },
                },
                ensure_ascii=False,
            ),
            "2026-03-28 18:00:00",
        ),
    )
    cur.execute(
        "INSERT INTO signal_feedback_summary VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("recommendation", "buy", 2, 50, 0.6, 0.02, 0.015, 0.01, -0.02, 0.04, 0.06, -0.03, "run_1"),
    )
    cur.execute(
        "INSERT INTO health_snapshot VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "2026-03-28 14:59:00",
            "service",
            3600.0,
            12,
            1,
            "{}",
            json.dumps({"service.lifecycle": {"health": "healthy", "last_seen": "2026-03-28 14:59:00", "lag_seconds": 0}}, ensure_ascii=False),
            "{}",
            json.dumps({"component_status": {"service.lifecycle": {"health": "healthy", "last_seen": "2026-03-28 14:59:00", "lag_seconds": 0}}}, ensure_ascii=False),
        ),
    )
    cur.execute(
        "INSERT INTO runtime_incident VALUES (?, ?, ?, ?, ?, ?)",
        (
            "2026-03-28 14:58:30",
            "分钟数据降级",
            "行业实时主源获取失败，降级到候选分钟聚合",
            "warning",
            "monitor",
            "monitor.loop",
        ),
    )
    cur.execute(
        "INSERT INTO dashboard_action_record (action_key, status, message, payload_json, created_time) VALUES (?, ?, ?, ?, ?)",
        (
            "generate_plan",
            "success",
            "今日计划已生成",
            json.dumps({"recommended_count": 1}, ensure_ascii=False),
            "2026-03-28 08:56:00",
        ),
    )
    cur.execute(
        "INSERT INTO dashboard_action_record (action_key, status, message, payload_json, created_time) VALUES (?, ?, ?, ?, ?)",
        (
            "refresh_intraday_status",
            "failed",
            "未检测到实时监控在线",
            json.dumps({}, ensure_ascii=False),
            "2026-03-28 09:10:00",
        ),
    )
    conn.commit()
    conn.close()

    conn = sqlite3.connect(history_db)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            name TEXT,
            recommendation_date TEXT,
            recommendation_reason TEXT,
            recommendation_score REAL,
            strategy_type TEXT
        )
        """
    )
    cur.execute(
        "INSERT INTO recommendations (symbol, name, recommendation_date, recommendation_reason, recommendation_score, strategy_type) VALUES (?, ?, ?, ?, ?, ?)",
        ("600519.SH", "贵州茅台", "2026-03-28", "推荐", 88.6, "白酒"),
    )
    conn.commit()
    conn.close()

    candidate_cache.write_text(
        json.dumps(
            {
                "date": "20260328",
                "created_time": "2026-03-28 08:55:00",
                "candidates": [
                    {"symbol": "600519", "name": "贵州茅台", "score": 88.6, "level": "强烈推荐", "industry": "酿酒", "pool_type": "core"}
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    virtual_cache.write_text(
        json.dumps(
            {
                "open_trades": [
                    {
                        "symbol": "600519",
                        "name": "贵州茅台",
                        "buy_time": "2026-03-28T10:00:00",
                        "buy_price": 1508.0,
                        "buy_signal": "突破",
                        "buy_score": 87.0,
                        "details": {
                            "buy_route": "legacy_gap_mid_open",
                            "signal_subtype": "secondary_launch_breakout",
                        },
                    }
                ],
                "closed_trades": [],
                "statistics": {"total_signals": 1, "total_closed": 0, "open_trades": 1, "win_rate": 0, "avg_pnl_pct": 0},
                "save_time": "2026-03-28T10:05:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monitor_session_cache = tmp_path / "monitor_session.json"
    monitor_session_cache.write_text(
        json.dumps(
            {
                "is_active": True,
                "status_label": "正在盯盘",
                "started_at": "2026-03-28 09:32:00",
                "last_refresh_at": "2026-03-28 14:58:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (terminals_dir / "2.txt").write_text(
        "\n".join(
            [
                "---",
                "pid: 16348",
                "cwd: D:\\HuaweiAI\\quantSystem2",
                "active_command: python main.py",
                "---",
                "[14:59:30] 实时监控中...",
                "行业实时主源获取失败，降级到候选分钟聚合",
            ]
        ),
        encoding="utf-8",
    )
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "secondary_launch_recent_tracking_20260328_150000.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-03-28 15:00:00",
                "intraday_review_summary": {
                    "reviewed_signal_count": 3,
                    "buy_signal_count": 1,
                    "buy_signal_ratio": 0.3333,
                    "not_pushed_count": 2,
                    "top_not_pushed_reasons": [
                        {"reason": "前高抛压过近且量能不足，突破信号否决", "count": 1},
                        {"reason": "午后首次突破阈值更高，当前量能不足", "count": 1},
                    ],
                    "top_blocker_tags": [
                        {"tag": "near_high_supply", "label": "前高抛压", "count": 1},
                        {"tag": "afternoon_threshold", "label": "午后阈值", "count": 1},
                    ],
                },
                "details": [
                    {
                        "signal_date": "20260328",
                        "ts_code": "600519.SH",
                        "name": "贵州茅台",
                        "has_buy_signal": False,
                        "not_pushed_reason": "前高抛压过近且量能不足，突破信号否决",
                        "blocker_tag": "near_high_supply",
                        "blocker_label": "前高抛压",
                        "blocker_detail": "距离近30分钟前高过近，但量能未明显放大",
                        "confidence": 0.66,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    service = DashboardDataService(
        project_root=tmp_path,
        quant_db_path=quant_db,
        history_db_path=history_db,
        candidate_cache_path=candidate_cache,
        virtual_trades_path=virtual_cache,
        terminals_directory=terminals_dir,
        now_provider=lambda: datetime(2026, 3, 28, 15, 0, 0),
    )
    service.monitor_session_service.session_path = monitor_session_cache
    snapshot = service.build_snapshot()

    assert snapshot["meta"]["dashboard_mode"] == "web_v2"
    assert snapshot["today_board"]["status"] in {"准备中", "可交易", "谨慎", "休息", "仅复盘"}
    assert len(snapshot["today_board"]["cards"]) == 4
    assert snapshot["monitor_session"]["is_active"] is True
    assert snapshot["monitor_session"]["status_label"] == "会话已开，但数据源已降级"
    assert snapshot["monitor_session"]["runtime_online"] is True
    assert snapshot["monitor_session"]["runtime_usable"] is False
    assert snapshot["monitor_session"]["degraded_reasons"]
    assert snapshot["terminal_runtime"]["terminal_online"] is True
    assert snapshot["terminal_runtime"]["last_monitor_at"] == "14:59:30"
    assert snapshot["health"]["startup_market_sync"]["status"] == "unknown"
    assert "启动同步：" in " ".join(snapshot["today_board"]["highlights"])
    assert any(row.get("action_label") == "生成今日计划" for row in snapshot["action_center"]["timeline"])
    assert any("生成今日计划" in (row.get("action_label") or "") for row in snapshot["action_center"]["timeline"])
    assert snapshot["action_center"]["latest_success"] is not None
    assert len(snapshot["action_center"]["timeline"]) >= 2
    assert any(row["status_label"] in {"失败", "success", "成功"} for row in snapshot["action_center"]["timeline"])
    assert snapshot["journey"]["pre_market"]["items"][0]["name"] == "贵州茅台"
    assert "signals" in snapshot["journey"]["intraday"]
    assert snapshot["journey"]["intraday"]["monitor_session"]["is_active"] is True
    assert "summary" in snapshot["journey"]["post_market"]
    assert snapshot["secondary_launch_tracking"]["summary"]["reviewed_signal_count"] == 3
    assert snapshot["journey"]["post_market"]["summary"]["main_blocker"] == "前高抛压过近且量能不足，突破信号否决"


def test_dashboard_service_includes_startup_market_sync_status(tmp_path):
    tasks_path = tmp_path / "data" / "cache" / "web_background_tasks.json"
    tasks_path.parent.mkdir(parents=True, exist_ok=True)
    tasks_path.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "task_id": "startup-1",
                        "task_type": "thread",
                        "action_key": "startup_market_data_sync",
                        "status": "success",
                        "message": "启动校验完成",
                        "started_at": "2026-04-07 09:30:00",
                        "updated_at": "2026-04-07 09:31:05",
                        "ended_at": "2026-04-07 09:31:05",
                        "payload": {
                            "target_trade_date": "20260407",
                            "latest_trade_date_before": "20260403",
                            "latest_trade_date_after": "20260407",
                            "missing_trade_dates": ["20260407"],
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    service = DashboardDataService(
        project_root=tmp_path,
        quant_db_path=tmp_path / "quant.db",
        history_db_path=tmp_path / "history.db",
        candidate_cache_path=tmp_path / "candidate_pool.json",
        virtual_trades_path=tmp_path / "virtual_trades.json",
        terminals_directory=tmp_path / "terminals",
        now_provider=lambda: datetime(2026, 4, 7, 9, 35, 0),
    )

    snapshot = service.build_snapshot()
    startup_sync = snapshot["health"]["startup_market_sync"]
    assert snapshot["startup_market_sync"]["status"] == "success"
    assert startup_sync["target_trade_date"] == "20260407"
    assert startup_sync["missing_trade_dates_count"] == 1
    assert "目标交易日 20260407" in startup_sync["summary"]
    assert any("启动同步：成功" in text for text in snapshot["today_board"]["highlights"])


def test_dashboard_action_service_records_success(tmp_path):
    quant_db = tmp_path / "quant.db"
    config = None

    import src.services.dashboard_action_service as action_module

    class _StubDailyReport:
        def __init__(self, *_args, **_kwargs):
            pass

        def generate_report(self, skip_data_update=True):
            return {
                "secondary_launch_selection": [{"symbol": "600519"}],
                "market_analysis": {"target_position": 0.3},
            }

    class _StubTaskRunner:
        def __init__(self, *_args, **_kwargs):
            pass

    class _StubProcessManager:
        def __init__(self, *_args, **_kwargs):
            pass

    original_daily = action_module.DailyReportGenerator
    original_runner = action_module.DashboardTaskRunner
    original_process = action_module.DashboardProcessManager
    action_module.DailyReportGenerator = _StubDailyReport
    action_module.DashboardTaskRunner = _StubTaskRunner
    action_module.DashboardProcessManager = _StubProcessManager
    try:
        db = __import__("src.core.database", fromlist=["DatabaseManager"]).DatabaseManager()
        db.db_path = str(quant_db)
        db._connection_pool.db_path = str(quant_db)
        db._init_database()
        service = DashboardActionService(config=config, db=db)
        service.execute("generate_plan")
        record_service = DashboardActionRecordService(db=db)
        latest = record_service.get_latest_by_action("generate_plan")
        assert latest is not None
        assert latest["status"] == "success"
        assert "今日计划已生成" in latest["message"]
    finally:
        action_module.DailyReportGenerator = original_daily
        action_module.DashboardTaskRunner = original_runner
        action_module.DashboardProcessManager = original_process


def test_dashboard_action_service_requires_confirm_for_clear(tmp_path):
    quant_db = tmp_path / "quant.db"
    db = __import__("src.core.database", fromlist=["DatabaseManager"]).DatabaseManager()
    db.db_path = str(quant_db)
    db._connection_pool.db_path = str(quant_db)
    db._init_database()

    class _StubTaskRunner:
        def __init__(self, *_args, **_kwargs):
            pass

    class _StubProcessManager:
        def __init__(self, *_args, **_kwargs):
            pass

    service = DashboardActionService(
        db=db,
        task_runner=_StubTaskRunner(),
        process_manager=_StubProcessManager(),
    )
    try:
        service.execute("clear_candidate_pool", confirmed=False)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "确认" in str(exc)
