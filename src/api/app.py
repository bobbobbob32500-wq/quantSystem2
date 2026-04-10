# -*- coding: utf-8 -*-
"""Mobile API service for the quant system."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from src.core.config import ConfigManager
from src.core.logger import get_logger
from src.services.dashboard_action_record_service import DashboardActionRecordService
from src.services.dashboard_action_service import DashboardActionService
from src.services.dashboard_service import DashboardDataService

logger = get_logger("mobile_api")

app = FastAPI(
    title="Quant Trading Mobile API",
    description="Expose data and actions for the Android mobile app.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

config = ConfigManager()
data_service = DashboardDataService()
action_service = DashboardActionService()
action_record_service = DashboardActionRecordService()
release_dir = project_root / "data" / "releases"
release_meta_path = release_dir / "android-latest.json"
release_apk_path = release_dir / "android-latest.apk"
virtual_trades_path = project_root / "data" / "cache" / "virtual_trades.json"
virtual_trades_lock = Lock()
watchlist_path = project_root / "data" / "cache" / "mobile_watchlist.json"
watchlist_lock = Lock()
startup_market_sync_lock = Lock()
startup_market_sync_scheduled = False


class ActionRequest(BaseModel):
    action: str
    payload: Optional[Dict[str, Any]] = None
    confirmed: bool = False


class VirtualTradeUpsertRequest(BaseModel):
    symbol: str
    name: str
    buy_price: float
    quantity: int = 0
    buy_time: Optional[str] = None


class StrategyRunRequest(BaseModel):
    params: Optional[Dict[str, Any]] = None


class WatchlistUpdateRequest(BaseModel):
    symbols: List[str]


def _load_virtual_trades_payload() -> Dict[str, Any]:
    if not virtual_trades_path.exists():
        return {"open_trades": [], "closed_trades": [], "statistics": {}}
    try:
        payload = json.loads(virtual_trades_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except Exception:
        logger.exception("Failed to parse virtual trades payload")
    return {"open_trades": [], "closed_trades": [], "statistics": {}}


def _persist_virtual_trades_payload(payload: Dict[str, Any]) -> None:
    payload["save_time"] = datetime.now().isoformat()
    virtual_trades_path.parent.mkdir(parents=True, exist_ok=True)
    virtual_trades_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _normalize_trade_payload(raw: VirtualTradeUpsertRequest) -> Dict[str, Any]:
    symbol = str(raw.symbol or "").strip()
    name = str(raw.name or "").strip()
    if not symbol or not name:
        raise ValueError("股票代码和名称不能为空")
    if raw.buy_price <= 0:
        raise ValueError("买入价格必须大于0")
    return {
        "symbol": symbol,
        "name": name,
        "buy_price": float(raw.buy_price),
        "quantity": int(raw.quantity or 0),
        "buy_time": str(raw.buy_time or "").strip() or datetime.now().isoformat(),
    }


def _load_watchlist_payload() -> Dict[str, Any]:
    if not watchlist_path.exists():
        return {"symbols": [], "updated_at": None}
    try:
        payload = json.loads(watchlist_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except Exception:
        logger.exception("Failed to parse watchlist payload")
    return {"symbols": [], "updated_at": None}


def _persist_watchlist_payload(payload: Dict[str, Any]) -> None:
    payload["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    watchlist_path.parent.mkdir(parents=True, exist_ok=True)
    watchlist_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _normalize_symbols(raw_symbols: List[str]) -> List[str]:
    normalized: List[str] = []
    for symbol in raw_symbols:
        text = str(symbol or "").strip().upper()
        if not text:
            continue
        if "." in text:
            text = text.split(".", 1)[0]
        normalized.append(text)
    # Preserve order while deduplicating.
    return list(dict.fromkeys(normalized))


def _schedule_startup_market_data_sync() -> Optional[Dict[str, Any]]:
    global startup_market_sync_scheduled

    if os.environ.get("PYTEST_CURRENT_TEST"):
        logger.debug("Skip startup market data sync under pytest")
        return None
    if not bool(config.get("data_source.startup_auto_update_enabled", True)):
        logger.info("Startup market data sync disabled by config")
        return None

    with startup_market_sync_lock:
        if startup_market_sync_scheduled:
            return None
        startup_market_sync_scheduled = True

    try:
        task = action_service.task_runner.run_startup_market_data_sync()
        logger.info("Startup market data sync scheduled: %s", task.get("task_id"))
        return task
    except Exception:
        with startup_market_sync_lock:
            startup_market_sync_scheduled = False
        logger.exception("Failed to schedule startup market data sync")
        return None


def _strategy_catalog() -> List[Dict[str, Any]]:
    return [
        {
            "id": "secondary_launch",
            "name": "二次启动策略",
            "description": "优先捕捉二次启动形态，适合盘前候选筛选。",
            "scene": "盘前选股、盘中信号跟踪",
            "default_params": {"top_k": 15, "min_score": 60},
        },
        {
            "id": "legacy",
            "name": "原策略",
            "description": "保持历史兼容的选股逻辑，用于稳定对照。",
            "scene": "稳健模式、历史对比",
            "default_params": {"top_k": 15, "min_score": 55},
        },
        {
            "id": "breakout",
            "name": "突破策略",
            "description": "面向强势突破形态，聚焦趋势延续票。",
            "scene": "强势行情、趋势加速阶段",
            "default_params": {"top_k": 15, "min_score": 60},
        },
        {
            "id": "strong_start",
            "name": "强势股刚启动",
            "description": "结合筹码集中、平台收敛、放量突破与缩量回踩的启动临界点筛选。",
            "scene": "低位吸筹末端、突破启动、回踩确认",
            "default_params": {"top_k": 12, "min_score": 62},
        },
        {
            "id": "both",
            "name": "融合策略",
            "description": "合并二次启动与原策略结果，扩大候选覆盖。",
            "scene": "盘前全量扫描",
            "default_params": {"top_k": 20, "min_score": 55},
        },
    ]


@app.get("/")
async def root():
    return {
        "message": "Quant Trading Mobile API",
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.on_event("startup")
async def startup_event() -> None:
    _schedule_startup_market_data_sync()


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "service": "mobile_api"}


@app.get("/api/dashboard")
async def get_dashboard():
    try:
        snapshot = data_service.build_snapshot()
        return {"success": True, "data": snapshot}
    except Exception as exc:
        logger.exception("Failed to load dashboard snapshot")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/dashboard/overview")
async def get_overview():
    try:
        snapshot = data_service.build_terminal_home_snapshot()
        return {"success": True, "data": snapshot}
    except Exception as exc:
        logger.exception("Failed to load dashboard overview")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/action")
async def execute_action(request: ActionRequest):
    try:
        result = action_service.execute(
            action=request.action,
            payload=request.payload,
            confirmed=request.confirmed,
        )
        return {"success": True, "data": result}
    except Exception as exc:
        logger.exception("Failed to execute action: %s", request.action)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/candidate_pool")
async def get_candidate_pool():
    try:
        snapshot = data_service.build_snapshot()
        return {"success": True, "data": snapshot.get("candidate_pool", {})}
    except Exception as exc:
        logger.exception("Failed to load candidate pool")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/signals")
async def get_signals():
    try:
        snapshot = data_service.build_snapshot()
        return {"success": True, "data": snapshot.get("signals", {})}
    except Exception as exc:
        logger.exception("Failed to load signals")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/virtual_trades")
async def get_virtual_trades():
    try:
        snapshot = data_service.build_snapshot()
        return {"success": True, "data": snapshot.get("virtual_trades", {})}
    except Exception as exc:
        logger.exception("Failed to load virtual trades")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/virtual_trades")
async def create_virtual_trade(request: VirtualTradeUpsertRequest):
    try:
        normalized = _normalize_trade_payload(request)
        with virtual_trades_lock:
            payload = _load_virtual_trades_payload()
            open_trades = list(payload.get("open_trades") or [])
            trade_id = f"{normalized['symbol']}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
            open_trades.insert(
                0,
                {
                    "trade_id": trade_id,
                    "symbol": normalized["symbol"],
                    "name": normalized["name"],
                    "buy_time": normalized["buy_time"],
                    "buy_price": normalized["buy_price"],
                    "buy_signal": "mobile_manual",
                    "buy_score": 0.0,
                    "status": "holding",
                    "details": {"quantity": normalized["quantity"], "source": "android_app"},
                },
            )
            payload["open_trades"] = open_trades
            payload.setdefault("closed_trades", [])
            stats = dict(payload.get("statistics") or {})
            stats["open_trades"] = len(open_trades)
            stats["total_signals"] = len(open_trades) + len(payload.get("closed_trades") or [])
            payload["statistics"] = stats
            _persist_virtual_trades_payload(payload)
        return {"success": True, "data": {"trade_id": trade_id}}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to create virtual trade")
        raise HTTPException(status_code=500, detail=str(exc))


@app.put("/api/virtual_trades/{trade_id}")
async def update_virtual_trade(trade_id: str, request: VirtualTradeUpsertRequest):
    try:
        normalized = _normalize_trade_payload(request)
        with virtual_trades_lock:
            payload = _load_virtual_trades_payload()
            open_trades = list(payload.get("open_trades") or [])
            matched = False
            for item in open_trades:
                if str(item.get("trade_id") or "") != trade_id:
                    continue
                item["symbol"] = normalized["symbol"]
                item["name"] = normalized["name"]
                item["buy_price"] = normalized["buy_price"]
                item["buy_time"] = normalized["buy_time"]
                details = item.get("details") if isinstance(item.get("details"), dict) else {}
                details["quantity"] = normalized["quantity"]
                details["updated_from"] = "android_app"
                item["details"] = details
                matched = True
                break
            if not matched:
                raise HTTPException(status_code=404, detail="未找到对应的虚拟持仓")
            payload["open_trades"] = open_trades
            _persist_virtual_trades_payload(payload)
        return {"success": True, "data": {"trade_id": trade_id}}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to update virtual trade: %s", trade_id)
        raise HTTPException(status_code=500, detail=str(exc))


@app.delete("/api/virtual_trades/{trade_id}")
async def delete_virtual_trade(trade_id: str):
    try:
        with virtual_trades_lock:
            payload = _load_virtual_trades_payload()
            open_trades = list(payload.get("open_trades") or [])
            filtered = [item for item in open_trades if str(item.get("trade_id") or "") != trade_id]
            if len(filtered) == len(open_trades) and trade_id.startswith("symbol:"):
                symbol = trade_id.split(":", 1)[1].strip().upper().split(".", 1)[0]
                if symbol:
                    removed = False
                    fallback_filtered = []
                    for item in open_trades:
                        item_symbol = str(item.get("symbol") or "").strip().upper().split(".", 1)[0]
                        if not removed and item_symbol == symbol:
                            removed = True
                            continue
                        fallback_filtered.append(item)
                    filtered = fallback_filtered
            if len(filtered) == len(open_trades):
                raise HTTPException(status_code=404, detail="未找到对应的虚拟持仓")
            payload["open_trades"] = filtered
            stats = dict(payload.get("statistics") or {})
            stats["open_trades"] = len(filtered)
            payload["statistics"] = stats
            _persist_virtual_trades_payload(payload)
        return {"success": True, "data": {"trade_id": trade_id}}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to delete virtual trade: %s", trade_id)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/history")
async def get_history():
    try:
        snapshot = data_service.build_snapshot()
        return {
            "success": True,
            "data": {
                "recommendations": snapshot.get("recommendations", {}),
                "secondary_launch_tracking": snapshot.get("secondary_launch_tracking", {}),
            },
        }
    except Exception as exc:
        logger.exception("Failed to load history")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/action_records")
async def get_action_records(limit: int = 30):
    try:
        safe_limit = max(1, min(int(limit), 200))
        return {"success": True, "data": action_record_service.get_recent(limit=safe_limit)}
    except Exception as exc:
        logger.exception("Failed to load action records")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/background_tasks")
async def get_background_tasks(limit: int = 30):
    try:
        safe_limit = max(1, min(int(limit), 100))
        raw_tasks = action_service.task_runner.list_tasks(limit=safe_limit)
        tasks: List[Dict[str, Any]] = []
        for task in raw_tasks:
            status = str(task.get("status") or "")
            retryable = status.lower() == "failed"
            progress_pct = 0
            if status.lower() == "queued":
                progress_pct = 10
            elif status.lower() == "running":
                progress_pct = 60
            elif status.lower() == "success":
                progress_pct = 100
            error_code = "TASK_FAILED" if retryable else None
            next_task = dict(task)
            next_task["retryable"] = retryable
            next_task["progress_pct"] = progress_pct
            next_task["error_code"] = error_code
            tasks.append(next_task)
        return {"success": True, "data": tasks}
    except Exception as exc:
        logger.exception("Failed to load background tasks")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/background_tasks/{task_id}/retry")
async def retry_background_task(task_id: str):
    try:
        result = action_service.retry_background_task(task_id)
        return {"success": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to retry background task: %s", task_id)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/stocks/{symbol}/detail")
async def get_stock_detail(symbol: str):
    try:
        snapshot = data_service.build_snapshot()
        normalized_symbol = str(symbol or "").strip().upper().split(".", 1)[0]
        if not normalized_symbol:
            raise HTTPException(status_code=400, detail="symbol不能为空")
        candidates = list((snapshot.get("candidate_pool") or {}).get("top_candidates") or [])
        signals = list((snapshot.get("signals") or {}).get("latest_items") or [])
        trades = list((snapshot.get("virtual_trades") or {}).get("open_trades") or [])
        candidate_hit = next(
            (item for item in candidates if str(item.get("symbol", "")).upper().split(".", 1)[0] == normalized_symbol),
            None,
        )
        stock_signals = [
            item for item in signals
            if str(item.get("ts_code", "")).upper().split(".", 1)[0] == normalized_symbol
        ]
        open_trade = next(
            (item for item in trades if str(item.get("symbol", "")).upper().split(".", 1)[0] == normalized_symbol),
            None,
        )
        latest_signal = stock_signals[0] if stock_signals else None
        risk_tags: List[str] = []
        if candidate_hit and float(candidate_hit.get("score", 0) or 0) < 70:
            risk_tags.append("评分偏低")
        if not stock_signals:
            risk_tags.append("近期无信号")
        if open_trade and float(open_trade.get("last_pnl_pct", open_trade.get("profit_pct", 0)) or 0) < -3:
            risk_tags.append("浮亏扩大")
        if not risk_tags:
            risk_tags.append("风险可控")

        detail = {
            "symbol": normalized_symbol,
            "name": (
                (candidate_hit or {}).get("name")
                or (latest_signal or {}).get("name")
                or (open_trade or {}).get("name")
                or normalized_symbol
            ),
            "strategy_tags": [str((candidate_hit or {}).get("strategy_profile") or "").strip() or "unknown"],
            "selection_reason": (
                str((candidate_hit or {}).get("trigger_reason") or "").strip()
                or str((latest_signal or {}).get("trigger_reason") or "").strip()
                or "暂无明确入选原因"
            ),
            "market_phase": ((snapshot.get("meta") or {}).get("market_session") or {}).get("phase"),
            "key_risks": risk_tags,
            "todo_actions": [
                "关注下一次触发信号",
                "结合仓位规则确认是否执行",
                "若波动放大，优先控制回撤",
            ],
            "candidate": candidate_hit,
            "latest_signal": latest_signal,
            "signal_timeline": stock_signals[:10],
            "open_trade": open_trade,
            "risk_tags": risk_tags,
            "action_suggestion": (
                "优先观察并等待下一次信号确认"
                if not stock_signals
                else "已有信号，可结合仓位规则评估执行"
            ),
        }
        return {"success": True, "data": detail}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to get stock detail: %s", symbol)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/strategies")
async def get_strategies():
    return {"success": True, "data": _strategy_catalog()}


@app.get("/api/strategies/{strategy_id}")
async def get_strategy_detail(strategy_id: str):
    strategies = _strategy_catalog()
    for item in strategies:
        if item["id"] == strategy_id:
            return {"success": True, "data": item}
    raise HTTPException(status_code=404, detail="未找到策略")


@app.post("/api/strategies/{strategy_id}/run")
async def run_strategy(strategy_id: str, request: StrategyRunRequest):
    try:
        payload = {"strategy": strategy_id}
        if isinstance(request.params, dict):
            payload["params"] = request.params
        result = action_service.execute(
            action="run_stock_selection",
            payload=payload,
            confirmed=False,
        )
        return {"success": True, "data": result}
    except Exception as exc:
        logger.exception("Failed to run strategy: %s", strategy_id)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/analytics/summary")
async def get_analytics_summary():
    try:
        snapshot = data_service.build_snapshot()
        feedback = snapshot.get("feedback") or {}
        best_summary = feedback.get("best_summary") or {}
        intraday = feedback.get("best_intraday_subtype") or {}
        recommendations = snapshot.get("recommendations") or {}
        virtual_trades = snapshot.get("virtual_trades") or {}
        payload = {
            "week_hit_rate": float(intraday.get("win_rate_pct", 0) or 0),
            "month_hit_rate": float(best_summary.get("win_rate_pct", 0) or 0),
            "strategy_success_rate": float(best_summary.get("win_rate_pct", 0) or 0),
            "return_summary": {
                "mean_net_return_pct": float(best_summary.get("mean_net_return_pct", 0) or 0),
                "mean_mfe_pct": float(best_summary.get("mean_mfe_pct", 0) or 0),
                "mean_mae_pct": float(best_summary.get("mean_mae_pct", 0) or 0),
            },
            "drawdown_summary": {
                "avg_drawdown_pct": float(best_summary.get("mean_mae_pct", 0) or 0),
                "open_positions": int(virtual_trades.get("open_count", 0) or 0),
            },
            "latest_recommendation_date": recommendations.get("latest_date"),
        }
        return {"success": True, "data": payload}
    except Exception as exc:
        logger.exception("Failed to get analytics summary")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/watchlist")
async def get_watchlist():
    try:
        with watchlist_lock:
            payload = _load_watchlist_payload()
        return {"success": True, "data": payload}
    except Exception as exc:
        logger.exception("Failed to get watchlist")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/watchlist")
async def update_watchlist(request: WatchlistUpdateRequest):
    try:
        symbols = _normalize_symbols(request.symbols)
        with watchlist_lock:
            payload = {"symbols": symbols}
            _persist_watchlist_payload(payload)
        return {"success": True, "data": payload}
    except Exception as exc:
        logger.exception("Failed to update watchlist")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/app_update/android/latest")
async def get_android_latest_update(request: Request):
    try:
        if not release_apk_path.exists():
            return {
                "success": True,
                "data": {
                    "available": False,
                    "message": "No published APK found on server.",
                },
            }

        meta: Dict[str, Any] = {}
        if release_meta_path.exists():
            try:
                meta = json.loads(release_meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta = {}

        apk_url = str(meta.get("apk_url", "") or "").strip()
        if not apk_url:
            base = str(request.base_url).rstrip("/")
            apk_url = f"{base}/api/app_update/android/download"

        latest_version_code = int(meta.get("latest_version_code", meta.get("version_code", 1)) or 1)
        latest_version_name = str(meta.get("latest_version_name", meta.get("version_name", "1.0.0")) or "1.0.0")
        changelog = str(meta.get("changelog", "") or "").strip() or None
        force_update = bool(meta.get("force_update", False))
        published_at = str(meta.get("published_at", "") or "").strip() or None

        return {
            "success": True,
            "data": {
                "available": True,
                "latest_version_code": latest_version_code,
                "latest_version_name": latest_version_name,
                "apk_url": apk_url,
                "changelog": changelog,
                "force_update": force_update,
                "published_at": published_at,
            },
        }
    except Exception as exc:
        logger.exception("Failed to load Android update info")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/app_update/android/download")
async def download_android_latest_apk():
    if not release_apk_path.exists():
        raise HTTPException(status_code=404, detail="APK not found")
    return FileResponse(
        path=str(release_apk_path),
        media_type="application/vnd.android.package-archive",
        filename=release_apk_path.name,
    )


if __name__ == "__main__":
    import asyncio
    import uvicorn

    logger.info("Starting mobile API service...")
    if sys.platform.startswith("win"):
        # More stable socket behavior on Windows for long-lived mobile/ngrok connections.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
        loop="asyncio",
        http="h11",
        timeout_keep_alive=15,
        proxy_headers=True,
    )
