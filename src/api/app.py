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

# 可选服务（可能不存在）
try:
    from src.services.execution_journal_service import ExecutionJournalService
    _execution_journal_available = True
except ImportError:
    _execution_journal_available = False
    ExecutionJournalService = None

try:
    from src.services.notification_center_service import NotificationCenterService
    _notification_center_available = True
except ImportError:
    _notification_center_available = False
    NotificationCenterService = None

try:
    from src.services.startup_self_check_service import StartupSelfCheckService
    _startup_self_check_available = True
except ImportError:
    _startup_self_check_available = False
    StartupSelfCheckService = None

# AI管家服务（可选依赖）
try:
    from src.services.ai_butler_service import AIButlerService
    from src.services.ai_service import AIService
    _ai_available = True
except ImportError:
    _ai_available = False

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
execution_journal_path = project_root / "data" / "cache" / "execution_journal.json"
notification_center_ack_path = project_root / "data" / "cache" / "notification_center_ack.json"
execution_journal_service = (
    ExecutionJournalService(
        journal_path=execution_journal_path,
        max_entries=int(config.get("mobile_api.execution_journal_max_entries", 2000) or 2000),
    )
    if _execution_journal_available
    else None
)
notification_center_service = (
    NotificationCenterService(
        db=action_service.db,
        config=config,
        ack_state_path=notification_center_ack_path,
        max_scan_items=int(config.get("mobile_api.notification_center_max_scan_items", 5000) or 5000),
    )
    if _notification_center_available
    else None
)
startup_self_check_service = (
    StartupSelfCheckService(
        project_root=project_root,
        config=config,
        stale_days_threshold=int(config.get("mobile_api.startup_self_check_data_stale_days", 5) or 5),
    )
    if _startup_self_check_available
    else None
)
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


class VirtualTradeCloseRequest(BaseModel):
    sell_price: float
    quantity: int = 0
    sell_time: Optional[str] = None
    reason: Optional[str] = None
    note: Optional[str] = None


class StrategyRunRequest(BaseModel):
    params: Optional[Dict[str, Any]] = None


class WatchlistUpdateRequest(BaseModel):
    symbols: List[str]


class NotificationAckAllRequest(BaseModel):
    status: Optional[str] = None


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


def _normalize_trade_close_payload(raw: VirtualTradeCloseRequest) -> Dict[str, Any]:
    if raw.sell_price <= 0:
        raise ValueError("sell_price must be greater than 0")
    quantity = int(raw.quantity or 0)
    if quantity < 0:
        raise ValueError("quantity must be greater than or equal to 0")
    reason = str(raw.reason or "").strip() or "manual_close"
    note = str(raw.note or "").strip() or None
    return {
        "sell_price": float(raw.sell_price),
        "quantity": quantity,
        "sell_time": str(raw.sell_time or "").strip() or datetime.now().isoformat(),
        "reason": reason,
        "note": note,
    }


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _recompute_virtual_trade_stats(payload: Dict[str, Any]) -> Dict[str, Any]:
    open_trades = list(payload.get("open_trades") or [])
    closed_trades = list(payload.get("closed_trades") or [])
    pnl_values = [
        _safe_float(item.get("pnl_pct"), 0.0)
        for item in closed_trades
        if item.get("pnl_pct") is not None
    ]
    win_count = sum(1 for value in pnl_values if value > 0)
    loss_count = sum(1 for value in pnl_values if value < 0)
    stats = dict(payload.get("statistics") or {})
    stats.update(
        {
            "open_trades": len(open_trades),
            "total_closed": len(closed_trades),
            "total_signals": len(open_trades) + len(closed_trades),
            "win_count": win_count,
            "loss_count": loss_count,
            "win_rate": (win_count / len(pnl_values)) if pnl_values else 0.0,
            "avg_pnl_pct": (sum(pnl_values) / len(pnl_values)) if pnl_values else 0.0,
        }
    )
    payload["statistics"] = stats
    return payload


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


def _record_execution_journal(
    action: str,
    status: str,
    message: Optional[str] = None,
    symbol: Optional[str] = None,
    trade_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    if execution_journal_service is None:
        return
    try:
        execution_journal_service.append_event(
            action=action,
            status=status,
            message=message,
            symbol=symbol,
            trade_id=trade_id,
            source="mobile_api",
            channel="android_app",
            details=details or {},
        )
    except Exception:
        logger.exception("Failed to record execution journal event: %s", action)


def _to_user_facing_action_error(action: str, exc: Exception) -> str:
    raw = str(exc or "").strip()
    lowered = raw.lower()
    if (
        "submit_background_task" in lowered
        or "stubtaskrunner" in lowered
        or ("has no attribute" in lowered and "taskrunner" in lowered)
    ):
        return "后台任务通道暂不可用，已自动切换为同步执行，请重试。"
    if "clear_candidate_pool" in lowered:
        return "清空候选池失败，请稍后重试。"
    if raw:
        return raw
    return f"动作 {action} 执行失败，请稍后重试。"


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
            "id": "breakout",
            "name": "突破策略",
            "description": "面向强势突破形态，聚焦趋势延续票。",
            "scene": "强势行情、趋势加速阶段",
            "default_params": {"top_k": 15, "min_score": 60},
        },
        {
            "id": "wide_breakout",
            "name": "宽进突破策略",
            "description": "放宽选股覆盖面，买点采用最严档（与回测预设 wide_pool_strict_entry_v2 一致）。",
            "scene": "提高观察池覆盖、以突破确认过滤入场",
            "default_params": {"preset": "wide_pool_strict_entry_v2"},
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


@app.get("/api/system/startup_self_check")
async def get_startup_self_check():
    if startup_self_check_service is None:
        raise HTTPException(status_code=503, detail="启动自检服务未启用")
    try:
        payload = startup_self_check_service.run_check()
        return {"success": True, "data": payload}
    except Exception as exc:
        logger.exception("Failed to run startup self-check")
        raise HTTPException(status_code=500, detail=str(exc))


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
        raise HTTPException(
            status_code=500,
            detail=_to_user_facing_action_error(request.action, exc),
        )


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


@app.get("/api/execution_journal")
async def get_execution_journal(
    limit: int = 50,
    action: Optional[str] = None,
    status: Optional[str] = None,
    symbol: Optional[str] = None,
):
    if execution_journal_service is None:
        raise HTTPException(status_code=503, detail="执行流水服务未启用")
    try:
        safe_limit = max(1, min(int(limit), 500))
        payload = execution_journal_service.get_journal(
            limit=safe_limit,
            action=action,
            status=status,
            symbol=symbol,
        )
        return {"success": True, "data": payload}
    except Exception as exc:
        logger.exception("Failed to load execution journal")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/execution_journal/summary")
async def get_execution_journal_summary(limit: int = 20):
    if execution_journal_service is None:
        raise HTTPException(status_code=503, detail="执行流水服务未启用")
    try:
        safe_limit = max(1, min(int(limit), 200))
        payload = execution_journal_service.build_snapshot(recent_limit=safe_limit)
        return {"success": True, "data": payload}
    except Exception as exc:
        logger.exception("Failed to load execution journal summary")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/notifications")
async def get_notifications(
    limit: int = 50,
    status: Optional[str] = None,
    unread_only: bool = False,
):
    if notification_center_service is None:
        raise HTTPException(status_code=503, detail="通知中心服务未启用")
    try:
        safe_limit = max(1, min(int(limit), 200))
        payload = notification_center_service.list_notifications(
            limit=safe_limit,
            status=status,
            unread_only=bool(unread_only),
        )
        return {"success": True, "data": payload}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to load notifications")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/notifications/summary")
async def get_notification_summary(limit: int = 20):
    if notification_center_service is None:
        raise HTTPException(status_code=503, detail="通知中心服务未启用")
    try:
        safe_limit = max(1, min(int(limit), 100))
        payload = notification_center_service.build_summary(recent_limit=safe_limit)
        return {"success": True, "data": payload}
    except Exception as exc:
        logger.exception("Failed to load notification summary")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/notifications/{notification_id}/ack")
async def ack_notification(notification_id: str):
    if notification_center_service is None:
        raise HTTPException(status_code=503, detail="通知中心服务未启用")
    try:
        payload = notification_center_service.ack_notification(notification_id=notification_id)
        return {"success": True, "data": payload}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to ack notification: %s", notification_id)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/notifications/ack_all")
async def ack_all_notifications(request: NotificationAckAllRequest):
    if notification_center_service is None:
        raise HTTPException(status_code=503, detail="通知中心服务未启用")
    try:
        payload = notification_center_service.ack_all(status=request.status)
        return {"success": True, "data": payload}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to ack all notifications")
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
            _recompute_virtual_trade_stats(payload)
            _persist_virtual_trades_payload(payload)
        _record_execution_journal(
            action="virtual_trade_create",
            status="success",
            message="Virtual trade created from mobile app",
            symbol=normalized["symbol"],
            trade_id=trade_id,
            details={
                "quantity": normalized["quantity"],
                "buy_price": normalized["buy_price"],
            },
        )
        return {"success": True, "data": {"trade_id": trade_id}}
    except ValueError as exc:
        _record_execution_journal(
            action="virtual_trade_create",
            status="failed",
            message=str(exc),
            symbol=request.symbol,
            details={"stage": "validate"},
        )
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to create virtual trade")
        _record_execution_journal(
            action="virtual_trade_create",
            status="failed",
            message=str(exc),
            symbol=request.symbol,
            details={"stage": "persist"},
        )
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
            _recompute_virtual_trade_stats(payload)
            _persist_virtual_trades_payload(payload)
        _record_execution_journal(
            action="virtual_trade_update",
            status="success",
            message="Virtual trade updated from mobile app",
            symbol=normalized["symbol"],
            trade_id=trade_id,
            details={
                "quantity": normalized["quantity"],
                "buy_price": normalized["buy_price"],
            },
        )
        return {"success": True, "data": {"trade_id": trade_id}}
    except HTTPException as exc:
        _record_execution_journal(
            action="virtual_trade_update",
            status="failed",
            message=str(exc.detail),
            symbol=request.symbol,
            trade_id=trade_id,
            details={"status_code": exc.status_code},
        )
        raise
    except ValueError as exc:
        _record_execution_journal(
            action="virtual_trade_update",
            status="failed",
            message=str(exc),
            symbol=request.symbol,
            trade_id=trade_id,
            details={"stage": "validate"},
        )
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to update virtual trade: %s", trade_id)
        _record_execution_journal(
            action="virtual_trade_update",
            status="failed",
            message=str(exc),
            symbol=request.symbol,
            trade_id=trade_id,
            details={"stage": "persist"},
        )
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/virtual_trades/{trade_id}/close")
async def close_virtual_trade(trade_id: str, request: VirtualTradeCloseRequest):
    try:
        normalized = _normalize_trade_close_payload(request)
        with virtual_trades_lock:
            payload = _load_virtual_trades_payload()
            open_trades = list(payload.get("open_trades") or [])
            closed_trades = list(payload.get("closed_trades") or [])

            target_index = -1
            target_trade: Optional[Dict[str, Any]] = None
            for idx, item in enumerate(open_trades):
                if str(item.get("trade_id") or "") == trade_id:
                    target_index = idx
                    target_trade = item
                    break

            if target_trade is None:
                raise HTTPException(status_code=404, detail="virtual trade not found")

            buy_price = _safe_float(target_trade.get("buy_price"), 0.0)
            if buy_price <= 0:
                raise ValueError("invalid buy_price in target trade")

            sell_price = normalized["sell_price"]
            pnl_abs = sell_price - buy_price
            pnl_pct = pnl_abs / buy_price
            sell_time = normalized["sell_time"]

            details = (
                target_trade.get("details")
                if isinstance(target_trade.get("details"), dict)
                else {}
            )
            close_quantity = normalized["quantity"] or int(details.get("quantity") or 0)
            details.update(
                {
                    "quantity": close_quantity,
                    "close_source": "android_app",
                    "close_reason": normalized["reason"],
                    "close_note": normalized["note"],
                }
            )

            closed_trade = dict(target_trade)
            closed_trade.update(
                {
                    "status": "closed",
                    "sell_price": sell_price,
                    "sell_time": sell_time,
                    "sell_reason": normalized["reason"],
                    "pnl": round(pnl_abs, 6),
                    "pnl_pct": round(pnl_pct, 8),
                    "details": details,
                }
            )

            try:
                buy_time_raw = str(target_trade.get("buy_time") or "").strip()
                buy_time = datetime.fromisoformat(buy_time_raw) if buy_time_raw else None
                close_time = datetime.fromisoformat(sell_time)
                if buy_time is not None:
                    closed_trade["hold_duration"] = int((close_time - buy_time).total_seconds() // 60)
            except Exception:
                pass

            open_trades.pop(target_index)
            closed_trades.insert(0, closed_trade)
            payload["open_trades"] = open_trades
            payload["closed_trades"] = closed_trades
            _recompute_virtual_trade_stats(payload)
            _persist_virtual_trades_payload(payload)

        _record_execution_journal(
            action="virtual_trade_close",
            status="success",
            message="Virtual trade closed from mobile app",
            symbol=str(target_trade.get("symbol") or "").strip() or None,
            trade_id=trade_id,
            details={
                "sell_price": sell_price,
                "pnl_pct": round(pnl_pct * 100, 4),
                "reason": normalized["reason"],
            },
        )
        return {
            "success": True,
            "data": {
                "trade_id": trade_id,
                "sell_reason": normalized["reason"],
                "sell_time": sell_time,
            },
        }
    except HTTPException as exc:
        _record_execution_journal(
            action="virtual_trade_close",
            status="failed",
            message=str(exc.detail),
            trade_id=trade_id,
            details={"status_code": exc.status_code},
        )
        raise
    except ValueError as exc:
        _record_execution_journal(
            action="virtual_trade_close",
            status="failed",
            message=str(exc),
            trade_id=trade_id,
            details={"stage": "validate"},
        )
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to close virtual trade: %s", trade_id)
        _record_execution_journal(
            action="virtual_trade_close",
            status="failed",
            message=str(exc),
            trade_id=trade_id,
            details={"stage": "persist"},
        )
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
            _recompute_virtual_trade_stats(payload)
            _persist_virtual_trades_payload(payload)
        _record_execution_journal(
            action="virtual_trade_delete",
            status="success",
            message="Virtual trade deleted from mobile app",
            trade_id=trade_id,
            details={"open_count_after": len(filtered)},
        )
        return {"success": True, "data": {"trade_id": trade_id}}
    except HTTPException as exc:
        _record_execution_journal(
            action="virtual_trade_delete",
            status="failed",
            message=str(exc.detail),
            trade_id=trade_id,
            details={"status_code": exc.status_code},
        )
        raise
    except Exception as exc:
        logger.exception("Failed to delete virtual trade: %s", trade_id)
        _record_execution_journal(
            action="virtual_trade_delete",
            status="failed",
            message=str(exc),
            trade_id=trade_id,
            details={"stage": "persist"},
        )
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
        host=os.environ.get("MOBILE_API_HOST", "0.0.0.0"),
        port=int(os.environ.get("MOBILE_API_PORT", "8000")),
        log_level="info",
        loop="asyncio",
        http="h11",
        timeout_keep_alive=15,
        proxy_headers=True,
    )


# ==================== AI管家接口（移动端专用） ====================

if _ai_available:
    ai_service = AIService()
    butler_service = AIButlerService()

    class AIChatRequest(BaseModel):
        message: str
        context: Optional[Dict[str, Any]] = None

    class AIQuickAskRequest(BaseModel):
        key: str
        context: Optional[Dict[str, Any]] = None

    class AIBriefingRequest(BaseModel):
        yesterday_review: Optional[Dict[str, Any]] = None
        today_selection: Optional[List[Dict[str, Any]]] = None
        overnight_news: Optional[List[Dict[str, Any]]] = None
        data_status: Optional[Dict[str, Any]] = None

    class AIMonitorRequest(BaseModel):
        holdings: Optional[List[Dict[str, Any]]] = None
        signals: Optional[List[Dict[str, Any]]] = None
        market_status: Optional[Dict[str, Any]] = None

    class AIReviewRequest(BaseModel):
        today_trades: Optional[List[Dict[str, Any]]] = None
        today_signals: Optional[List[Dict[str, Any]]] = None
        holdings: Optional[List[Dict[str, Any]]] = None
        market_summary: Optional[Dict[str, Any]] = None

    class AIRiskCheckRequest(BaseModel):
        holdings: List[Dict[str, Any]] = []
        market_data: Dict[str, Any] = {}

    class AISignalAnalysisRequest(BaseModel):
        signal: Dict[str, Any]
        stock_info: Dict[str, Any]
        position: Optional[Dict[str, Any]] = None

    @app.get("/api/ai/status")
    async def get_ai_status():
        """获取AI服务状态"""
        return ai_service.get_status()

    @app.post("/api/ai/chat")
    async def ai_chat(request: AIChatRequest):
        """AI对话"""
        try:
            response = ai_service.chat(request.message, context=request.context)
            return {"success": True, "response": response}
        except Exception as exc:
            logger.exception("AI chat failed")
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/api/ai/quick_ask")
    async def ai_quick_ask(request: AIQuickAskRequest):
        """快速预设问答"""
        try:
            response = ai_service.quick_ask(request.key, context=request.context)
            return {"success": True, "response": response}
        except Exception as exc:
            logger.exception("AI quick ask failed")
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/api/butler/status")
    async def get_butler_status():
        """获取管家状态"""
        return butler_service.get_status()

    @app.post("/api/butler/start")
    async def start_butler():
        """启动管家服务"""
        try:
            butler_service.start()
            return {"success": True, "message": "AI管家服务已启动"}
        except Exception as exc:
            logger.exception("Failed to start butler")
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/api/butler/stop")
    async def stop_butler():
        """停止管家服务"""
        butler_service.stop()
        return {"success": True, "message": "AI管家服务已停止"}

    @app.post("/api/butler/briefing")
    async def generate_briefing(request: AIBriefingRequest):
        """生成盘前简报"""
        try:
            result = butler_service.generate_briefing_now(
                yesterday_review=request.yesterday_review,
                today_selection=request.today_selection,
                overnight_news=request.overnight_news,
                data_status=request.data_status,
            )
            return {"success": True, "result": result}
        except Exception as exc:
            logger.exception("Failed to generate briefing")
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/api/butler/monitor")
    async def do_monitor(request: AIMonitorRequest):
        """执行盘中监控"""
        try:
            result = butler_service.do_intraday_monitor_now(
                holdings=request.holdings,
                signals=request.signals,
                market_status=request.market_status,
            )
            return {"success": True, "result": result}
        except Exception as exc:
            logger.exception("Failed to do monitor")
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/api/butler/review")
    async def generate_review(request: AIReviewRequest):
        """生成盘后复盘"""
        try:
            result = butler_service.generate_review_now(
                today_trades=request.today_trades,
                today_signals=request.today_signals,
                holdings=request.holdings,
                market_summary=request.market_summary,
            )
            return {"success": True, "result": result}
        except Exception as exc:
            logger.exception("Failed to generate review")
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/api/butler/risk_check")
    async def do_risk_check(request: AIRiskCheckRequest):
        """执行风险检查"""
        try:
            result = butler_service.do_risk_check_now(
                holdings=request.holdings,
                market_data=request.market_data,
            )
            return {"success": True, "result": result}
        except Exception as exc:
            logger.exception("Failed to do risk check")
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/api/butler/signal_analysis")
    async def analyze_signal(request: AISignalAnalysisRequest):
        """信号实时分析"""
        try:
            result = butler_service.on_signal_triggered(
                request.signal,
                request.stock_info,
                request.position,
            )
            return {"success": True, "result": result}
        except Exception as exc:
            logger.exception("Failed to analyze signal")
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/api/butler/last_briefing")
    async def get_last_briefing():
        """获取最近盘前简报"""
        return {"briefing": butler_service.get_last_briefing()}

    @app.get("/api/butler/last_review")
    async def get_last_review():
        """获取最近盘后复盘"""
        return {"review": butler_service.get_last_review()}

    # ==================== 扩展功能接口 ====================

    # --- 多维度预警 ---
    try:
        from src.modules.ai_integration.alert_system import MultiDimensionalAlertSystem
        _alert_system = MultiDimensionalAlertSystem(llm_client=butler_service.butler.llm if hasattr(butler_service, 'butler') else None)
    except Exception:
        _alert_system = None

    class AlertCheckRequest(BaseModel):
        symbol: str
        price_data: Dict[str, Any] = {}
        indicators: Optional[Dict[str, Any]] = None
        capital_data: Optional[Dict[str, Any]] = None

    @app.post("/api/alerts/technical")
    async def check_technical_alerts(request: AlertCheckRequest):
        """技术面预警检查"""
        if not _alert_system:
            raise HTTPException(status_code=503, detail="预警系统不可用")
        try:
            alerts = _alert_system.check_technical_alerts(request.symbol, request.price_data, request.indicators)
            return {"success": True, "data": alerts}
        except Exception as exc:
            logger.exception("Technical alert check failed")
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/api/alerts/capital_flow")
    async def check_capital_flow_alerts(request: AlertCheckRequest):
        """资金面预警检查"""
        if not _alert_system:
            raise HTTPException(status_code=503, detail="预警系统不可用")
        try:
            alerts = _alert_system.check_capital_flow_alerts(request.symbol, request.capital_data or {})
            return {"success": True, "data": alerts}
        except Exception as exc:
            logger.exception("Capital flow alert check failed")
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/api/alerts/active")
    async def get_active_alerts():
        """获取活跃预警"""
        if not _alert_system:
            return {"success": True, "data": []}
        return {"success": True, "data": _alert_system.get_active_alerts()}

    @app.get("/api/alerts/summary")
    async def get_alert_summary():
        """获取预警摘要"""
        if not _alert_system:
            return {"success": True, "data": {"total_active": 0}}
        return {"success": True, "data": _alert_system.get_alert_summary()}

    @app.post("/api/alerts/{alert_id}/ack")
    async def ack_alert(alert_id: str):
        """确认预警"""
        if not _alert_system:
            raise HTTPException(status_code=503, detail="预警系统不可用")
        if _alert_system.ack_alert(alert_id):
            return {"success": True}
        raise HTTPException(status_code=404, detail="预警不存在")

    # --- 实时盯盘 ---
    try:
        from src.modules.ai_integration.realtime_watcher import RealTimeWatcher, WatchType
        _watcher = RealTimeWatcher(llm_client=butler_service.butler.llm if hasattr(butler_service, 'butler') else None)
    except Exception:
        _watcher = None

    class PriceAlertRequest(BaseModel):
        symbol: str
        watch_type: str  # price_above, price_below, support_break, resistance_break
        target_value: float
        label: Optional[str] = None

    @app.post("/api/watcher/alerts")
    async def set_price_alert(request: PriceAlertRequest):
        """设置价位提醒"""
        if not _watcher:
            raise HTTPException(status_code=503, detail="盯盘系统不可用")
        try:
            wt = WatchType(request.watch_type)
            alert = _watcher.set_price_alert(request.symbol, wt, request.target_value, request.label or "")
            return {"success": True, "data": alert.to_dict()}
        except ValueError:
            raise HTTPException(status_code=400, detail=f"无效的watch_type: {request.watch_type}")
        except Exception as exc:
            logger.exception("Set price alert failed")
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/api/watcher/alerts")
    async def get_watcher_alerts():
        """获取盯盘提醒列表"""
        if not _watcher:
            return {"success": True, "data": []}
        return {"success": True, "data": _watcher.get_all_alerts()}

    @app.delete("/api/watcher/alerts/{alert_id}")
    async def remove_price_alert(alert_id: str):
        """移除价位提醒"""
        if not _watcher:
            raise HTTPException(status_code=503, detail="盯盘系统不可用")
        if _watcher.remove_price_alert(alert_id):
            return {"success": True}
        raise HTTPException(status_code=404, detail="提醒不存在")

    @app.get("/api/watcher/summary")
    async def get_watcher_summary():
        """获取盯盘摘要"""
        if not _watcher:
            return {"success": True, "data": {}}
        return {"success": True, "data": _watcher.get_summary()}

    # --- 策略优化 ---
    try:
        from src.modules.ai_integration.strategy_optimizer import StrategyOptimizer
        _strategy_optimizer = StrategyOptimizer(llm_client=butler_service.butler.llm if hasattr(butler_service, 'butler') else None)
    except Exception:
        _strategy_optimizer = None

    class StrategyOptimizeRequest(BaseModel):
        strategy_id: str
        strategy_name: str
        current_params: Dict[str, Any] = {}
        performance: Dict[str, Any] = {}

    @app.post("/api/strategy/optimize")
    async def optimize_strategy(request: StrategyOptimizeRequest):
        """策略参数优化建议"""
        if not _strategy_optimizer:
            raise HTTPException(status_code=503, detail="策略优化不可用")
        try:
            result = _strategy_optimizer.analyze_strategy_performance(
                request.strategy_id, request.strategy_name, request.current_params, request.performance
            )
            return {"success": True, "data": result}
        except Exception as exc:
            logger.exception("Strategy optimize failed")
            raise HTTPException(status_code=500, detail=str(exc))

    class MarketAdaptiveRequest(BaseModel):
        market_regime: str
        current_params: Dict[str, Any] = {}

    @app.post("/api/strategy/market_adaptive")
    async def market_adaptive_params(request: MarketAdaptiveRequest):
        """市场自适应参数建议"""
        if not _strategy_optimizer:
            raise HTTPException(status_code=503, detail="策略优化不可用")
        try:
            result = _strategy_optimizer.suggest_market_adaptive_params(request.market_regime, request.current_params)
            return {"success": True, "data": result}
        except Exception as exc:
            logger.exception("Market adaptive failed")
            raise HTTPException(status_code=500, detail=str(exc))

    # --- 智能执行 ---
    try:
        from src.modules.ai_integration.execution_assistant import ExecutionAssistant
        _execution_assistant = ExecutionAssistant(llm_client=butler_service.butler.llm if hasattr(butler_service, 'butler') else None)
    except Exception:
        _execution_assistant = None

    class ExecutionPlanRequest(BaseModel):
        signal: Dict[str, Any]
        stock_info: Dict[str, Any]
        current_position: Optional[Dict[str, Any]] = None
        risk_config: Optional[Dict[str, Any]] = None

    @app.post("/api/execution/plan")
    async def generate_execution_plan(request: ExecutionPlanRequest):
        """生成交易执行计划"""
        if not _execution_assistant:
            raise HTTPException(status_code=503, detail="执行助手不可用")
        try:
            plan = _execution_assistant.generate_trade_plan(
                request.signal, request.stock_info, request.current_position, request.risk_config
            )
            return {"success": True, "data": plan.to_dict()}
        except Exception as exc:
            logger.exception("Generate execution plan failed")
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/api/execution/plans")
    async def get_execution_plans():
        """获取交易计划列表"""
        if not _execution_assistant:
            return {"success": True, "data": []}
        return {"success": True, "data": _execution_assistant.get_plans()}

    # --- 深度复盘 ---
    try:
        from src.modules.ai_integration.deep_review import DeepReviewAnalyzer
        _deep_review = DeepReviewAnalyzer(llm_client=butler_service.butler.llm if hasattr(butler_service, 'butler') else None)
    except Exception:
        _deep_review = None

    class DeepReviewRequest(BaseModel):
        trades: List[Dict[str, Any]] = []

    @app.post("/api/review/deep")
    async def deep_review(request: DeepReviewRequest):
        """深度复盘分析"""
        if not _deep_review:
            raise HTTPException(status_code=503, detail="深度复盘不可用")
        try:
            mistakes = _deep_review.analyze_mistakes(request.trades)
            profitable = [t for t in request.trades if t.get("pnl_pct", 0) > 0]
            patterns = _deep_review.extract_success_patterns(profitable)
            overall = {
                "win_rate": len(profitable) / len(request.trades) if request.trades else 0,
                "avg_return_pct": sum(t.get("pnl_pct", 0) for t in request.trades) / len(request.trades) if request.trades else 0,
            }
            improvement = _deep_review.generate_improvement_plan(mistakes, patterns, overall)
            return {"success": True, "data": {
                "mistakes": mistakes,
                "success_patterns": patterns,
                "improvement_plan": improvement,
            }}
        except Exception as exc:
            logger.exception("Deep review failed")
            raise HTTPException(status_code=500, detail=str(exc))

    # --- 周报/月报 ---
    try:
        from src.modules.ai_integration.periodic_reporter import PeriodicReporter
        _periodic_reporter = PeriodicReporter(llm_client=butler_service.butler.llm if hasattr(butler_service, 'butler') else None)
    except Exception:
        _periodic_reporter = None

    class PeriodicReportRequest(BaseModel):
        trades: List[Dict[str, Any]] = []
        signals: List[Dict[str, Any]] = []
        holdings: List[Dict[str, Any]] = []
        report_type: str = "weekly"

    @app.post("/api/reports/generate")
    async def generate_report(request: PeriodicReportRequest):
        """生成周期报告"""
        if not _periodic_reporter:
            raise HTTPException(status_code=503, detail="报告生成不可用")
        try:
            if request.report_type == "monthly":
                result = _periodic_reporter.generate_monthly_report(request.trades, request.signals, request.holdings)
            else:
                result = _periodic_reporter.generate_weekly_report(request.trades, request.signals, request.holdings)
            return {"success": True, "data": result}
        except Exception as exc:
            logger.exception("Report generation failed")
            raise HTTPException(status_code=500, detail=str(exc))

    # --- 交易风格 ---
    try:
        from src.modules.ai_integration.style_learner import TradingStyleLearner
        _style_learner = TradingStyleLearner(llm_client=butler_service.butler.llm if hasattr(butler_service, 'butler') else None)
    except Exception:
        _style_learner = None

    class StyleAnalyzeRequest(BaseModel):
        trade_history: List[Dict[str, Any]] = []

    @app.post("/api/style/analyze")
    async def analyze_trading_style(request: StyleAnalyzeRequest):
        """分析交易风格"""
        if not _style_learner:
            raise HTTPException(status_code=503, detail="风格学习不可用")
        try:
            style = _style_learner.analyze_user_pattern(request.trade_history)
            return {"success": True, "data": style.to_dict()}
        except Exception as exc:
            logger.exception("Style analysis failed")
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/api/style")
    async def get_trading_style():
        """获取当前交易风格"""
        if not _style_learner:
            return {"success": True, "data": {}}
        return {"success": True, "data": _style_learner.get_style()}

    # --- 上下文问答 ---
    try:
        from src.modules.ai_integration.context_qa import ContextAwareQA
        _context_qa = ContextAwareQA(llm_client=butler_service.butler.llm if hasattr(butler_service, 'butler') else None)
    except Exception:
        _context_qa = None

    class ContextQARequest(BaseModel):
        question: str
        current_page: str = ""
        current_data: Optional[Dict[str, Any]] = None

    @app.post("/api/ai/context_qa")
    async def context_qa(request: ContextQARequest):
        """上下文感知问答"""
        if not _context_qa:
            raise HTTPException(status_code=503, detail="上下文问答不可用")
        try:
            result = _context_qa.answer_with_context(request.question, request.current_page, request.current_data)
            return {"success": True, "data": result}
        except Exception as exc:
            logger.exception("Context QA failed")
            raise HTTPException(status_code=500, detail=str(exc))

    # --- 知识库 ---
    try:
        from src.modules.ai_integration.knowledge_base import QuantKnowledgeBase
        _knowledge_base = QuantKnowledgeBase(llm_client=butler_service.butler.llm if hasattr(butler_service, 'butler') else None)
    except Exception:
        _knowledge_base = None

    @app.get("/api/knowledge/topics")
    async def list_knowledge_topics(category: Optional[str] = None):
        """列出知识主题"""
        if not _knowledge_base:
            return {"success": True, "data": []}
        return {"success": True, "data": _knowledge_base.list_topics(category)}

    @app.get("/api/knowledge/query")
    async def query_knowledge(topic: str):
        """查询知识"""
        if not _knowledge_base:
            raise HTTPException(status_code=503, detail="知识库不可用")
        result = _knowledge_base.query(topic)
        if result:
            return {"success": True, "data": result}
        raise HTTPException(status_code=404, detail="未找到相关知识")

    @app.get("/api/knowledge/categories")
    async def get_knowledge_categories():
        """获取知识分类"""
        if not _knowledge_base:
            return {"success": True, "data": []}
        return {"success": True, "data": _knowledge_base.get_categories()}

    # --- 数据质量 ---
    try:
        from src.modules.ai_integration.data_quality import DataQualityMonitor
        _data_quality = DataQualityMonitor()
    except Exception:
        _data_quality = None

    class DataQualityRequest(BaseModel):
        data_status: Dict[str, Any] = {}
        expected_symbols: Optional[List[str]] = None

    @app.post("/api/data_quality/check")
    async def check_data_quality(request: DataQualityRequest):
        """检查数据质量"""
        if not _data_quality:
            raise HTTPException(status_code=503, detail="数据质量监控不可用")
        try:
            result = _data_quality.check_data_quality(request.data_status, request.expected_symbols)
            return {"success": True, "data": result}
        except Exception as exc:
            logger.exception("Data quality check failed")
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/api/data_quality/summary")
    async def get_data_quality_summary():
        """获取数据质量摘要"""
        if not _data_quality:
            return {"success": True, "data": {}}
        return {"success": True, "data": _data_quality.get_summary()}
