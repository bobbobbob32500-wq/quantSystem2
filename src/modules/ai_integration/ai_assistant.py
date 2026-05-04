# -*- coding: utf-8 -*-
"""AI assistant for local quant system.

This module provides:
- natural-language chat with system context injection
- guarded action execution (whitelist + confirmation keyword)
- manager shortcuts:
  1) add/update holding by NL
  2) recent N-day win-rate report
  3) stock buy-condition check
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.logger import get_logger
from src.modules.ai_integration.llm_client import LLMClient

logger = get_logger("ai_assistant")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_CACHE_DIR = PROJECT_ROOT / "data" / "cache"

SYSTEM_PROMPT = """你是A股量化交易系统的AI管家助手。
要求：
1. 只能基于系统注入数据作答，不得编造系统事实。
2. 对涉及交易动作的请求，优先走系统动作接口，并明确风险提示。
3. 输出简洁、结构化、可执行。
"""

QUICK_PROMPTS = {
    "市场分析": "请分析当前A股市场环境，并给出简要操作建议。",
    "选股逻辑": "请解释当前系统的选股逻辑与关键指标。",
    "风控策略": "请总结当前策略的风控要点与仓位纪律。",
    "策略优化": "请给出当前策略可执行的优化建议。",
}


class AIAssistant:
    def __init__(
        self,
        llm_client: LLMClient,
        system_prompt: Optional[str] = None,
        quick_prompts: Optional[Dict[str, str]] = None,
        default_temperature: Optional[float] = None,
        default_max_tokens: Optional[int] = None,
        default_timeout: Optional[float] = None,
        enable_actions: bool = False,
        action_whitelist: Optional[List[str]] = None,
        require_action_confirmation: bool = True,
        action_confirmation_keywords: Optional[List[str]] = None,
    ):
        self.llm = llm_client
        self._system_prompt = system_prompt or SYSTEM_PROMPT
        self._quick_prompts = quick_prompts or QUICK_PROMPTS
        self._default_temperature = default_temperature
        self._default_max_tokens = default_max_tokens
        self._default_timeout = default_timeout
        self._enable_actions = bool(enable_actions)
        self._action_whitelist = set(action_whitelist or [])
        self._require_action_confirmation = bool(require_action_confirmation)
        self._action_confirmation_keywords = [
            str(x).lower() for x in (action_confirmation_keywords or ["确认", "执行", "立即执行", "confirm"]) if str(x).strip()
        ]
        self._conversation_history: List[Dict[str, str]] = []
        self._action_service = None

    @staticmethod
    def _normalize_ts_code(raw_code: str) -> str:
        code = str(raw_code or "").strip().upper()
        if not code:
            return ""
        if "." in code:
            return code
        if code.startswith(("6", "9")):
            return f"{code}.SH"
        return f"{code}.SZ"

    def _get_action_service(self):
        if self._action_service is None:
            try:
                from src.services.dashboard_action_service import DashboardActionService

                self._action_service = DashboardActionService()
            except Exception as exc:
                logger.warning("Action service unavailable: %s", exc)
        return self._action_service

    def _read_system_data(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {}

        try:
            pool_path = DATA_CACHE_DIR / "candidate_pool.json"
            if pool_path.exists():
                pool = json.loads(pool_path.read_text(encoding="utf-8"))
                candidates = list(pool.get("candidates") or [])
                data["候选池"] = {
                    "日期": pool.get("date"),
                    "数量": len(candidates),
                    "前10": [
                        {
                            "code": c.get("ts_code") or c.get("symbol"),
                            "name": c.get("name"),
                            "score": c.get("score", c.get("total_score")),
                        }
                        for c in candidates[:10]
                    ],
                }
        except Exception as exc:
            logger.debug("read candidate pool failed: %s", exc)

        try:
            vt_path = DATA_CACHE_DIR / "virtual_trades.json"
            if vt_path.exists():
                vt = json.loads(vt_path.read_text(encoding="utf-8"))
                data["虚拟交易"] = {
                    "open_trades": list(vt.get("open_trades") or []),
                    "closed_trades": list(vt.get("closed_trades") or []),
                    "statistics": dict(vt.get("statistics") or {}),
                }
        except Exception as exc:
            logger.debug("read virtual trades failed: %s", exc)

        return data

    def _format_system_data(self, data: Dict[str, Any]) -> str:
        if not data:
            return "（系统数据暂不可读）"
        return json.dumps(data, ensure_ascii=False, indent=2)[:6000]

    def _execute_system_action(self, action: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if self._action_whitelist and action not in self._action_whitelist:
            return {"success": False, "message": f"动作 `{action}` 不在白名单中，已拒绝执行。"}

        service = self._get_action_service()
        if service is None:
            return {"success": False, "message": "操作服务不可用"}

        try:
            return service.execute(action=action, payload=payload or {}, confirmed=True)
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def _read_dashboard_snapshot(self) -> Dict[str, Any]:
        try:
            from src.services.dashboard_service import DashboardDataService

            return DashboardDataService(project_root=PROJECT_ROOT).build_snapshot() or {}
        except Exception as exc:
            logger.debug("read dashboard snapshot failed: %s", exc)
            return {}

    def _try_update_holding_from_nl(self, user_input: str, input_lower: str) -> Optional[str]:
        keywords = ["新增持仓", "增加持仓", "添加持仓", "建仓", "加仓", "买入持仓"]
        if not any(k in user_input for k in keywords):
            return None

        symbol_match = re.search(r"\b(\d{6}(?:\.(?:SZ|SH))?)\b", user_input, re.IGNORECASE)
        if not symbol_match:
            return "已识别为新增持仓请求，但缺少股票代码。示例：新增持仓 000001.SZ 成本12.5 数量1000"
        ts_code = self._normalize_ts_code(symbol_match.group(1))

        price_match = re.search(r"(?:成本|买入价|买入价格|价格|cost)\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?)", user_input, re.IGNORECASE)
        qty_match = re.search(r"(?:数量|股数|仓位股数|num|qty)\s*[:：]?\s*(\d+)", user_input, re.IGNORECASE)
        name_match = re.search(r"(?:名称|股票|标的)\s*[:：]?\s*([A-Za-z0-9\u4e00-\u9fa5_]+)", user_input)

        if not price_match or not qty_match:
            return "已识别为新增持仓请求，但缺少成本或数量。示例：新增持仓 000001.SZ 名称平安银行 成本12.5 数量1000"

        if self._require_action_confirmation and not any(k in input_lower for k in self._action_confirmation_keywords):
            return "已识别可执行动作：新增持仓。请加入确认词后重试，例如：确认新增持仓 000001.SZ 成本12.5 数量1000"

        payload = {
            "ts_code": ts_code,
            "name": (name_match.group(1) if name_match else ts_code),
            "hold_price": float(price_match.group(1)),
            "hold_num": int(qty_match.group(1)),
            "hold_date": datetime.now().strftime("%Y-%m-%d"),
        }
        result = self._execute_system_action("update_holding", payload)
        if result.get("success"):
            return (
                "✅ 新增持仓执行成功\n"
                f"代码: {payload['ts_code']}\n名称: {payload['name']}\n成本: {payload['hold_price']}\n数量: {payload['hold_num']}"
            )
        return f"❌ 新增持仓执行失败: {result.get('message', '未知错误')}"

    def _try_remove_holding_from_nl(self, user_input: str, input_lower: str) -> Optional[str]:
        keywords = ["删除持仓", "移除持仓", "清仓", "卖出持仓", "移仓"]
        if not any(k in user_input for k in keywords):
            return None

        symbol_match = re.search(r"\b(\d{6}(?:\.(?:SZ|SH))?)\b", user_input, re.IGNORECASE)
        if not symbol_match:
            return "已识别为删除持仓请求，但缺少股票代码。示例：确认删除持仓 000001.SZ"
        ts_code = self._normalize_ts_code(symbol_match.group(1))

        if self._require_action_confirmation and not any(k in input_lower for k in self._action_confirmation_keywords):
            return f"已识别可执行动作：删除持仓 {ts_code}。请加入确认词后重试，例如：确认删除持仓 {ts_code}"

        result = self._execute_system_action("remove_holding", {"ts_code": ts_code})
        if result.get("success"):
            return f"✅ 删除持仓执行成功：{ts_code}"
        return f"❌ 删除持仓执行失败: {result.get('message', '未知错误')}"

    def _detect_and_execute_action(self, user_input: str) -> Optional[str]:
        input_lower = user_input.lower()

        holding_result = self._try_update_holding_from_nl(user_input, input_lower)
        if holding_result:
            return holding_result
        remove_result = self._try_remove_holding_from_nl(user_input, input_lower)
        if remove_result:
            return remove_result

        action_map = {
            r"选股": ("run_stock_selection", {}, "执行选股"),
            r"运行选股": ("run_stock_selection", {}, "执行选股"),
            r"启动监控": ("start_monitor_runtime", {}, "启动实时监控"),
            r"停止监控": ("stop_monitor_runtime", {}, "停止实时监控"),
            r"盘后复盘|复盘": ("generate_post_market_review", {}, "生成盘后复盘"),
            r"盘前计划|交易计划": ("generate_plan", {}, "生成交易计划"),
            r"清空候选池": ("clear_candidate_pool", {}, "清空候选池"),
            r"清空虚拟交易": ("clear_virtual_trades", {}, "清空虚拟交易"),
        }

        for pattern, (action, payload, description) in action_map.items():
            if not re.search(pattern, user_input):
                continue

            if self._require_action_confirmation and not any(k in input_lower for k in self._action_confirmation_keywords):
                return f"已识别可执行动作：{description}。为避免误触发，请加入确认词后重试。"

            result = self._execute_system_action(action, payload)
            if result.get("success"):
                return f"✅ {description}执行成功"
            return f"❌ {description}执行失败: {result.get('message', '未知错误')}"

        return None

    def _answer_system_health_query(self, user_input: str) -> Optional[str]:
        query = user_input or ""
        health_keys = ["系统运行情况", "系统健康", "系统状态", "健康检查", "系统体检", "运行状态", "巡检"]
        if not any(k in query for k in health_keys):
            return None

        snapshot = self._read_dashboard_snapshot()
        candidate_pool = (snapshot.get("candidate_pool") or {}) if isinstance(snapshot, dict) else {}
        signals = (snapshot.get("signals") or {}) if isinstance(snapshot, dict) else {}
        health = (snapshot.get("health") or {}) if isinstance(snapshot, dict) else {}
        monitor_session = (snapshot.get("monitor_session") or {}) if isinstance(snapshot, dict) else {}
        virtual_trades = (snapshot.get("virtual_trades") or {}) if isinstance(snapshot, dict) else {}
        meta = (snapshot.get("meta") or {}) if isinstance(snapshot, dict) else {}

        candidate_count = int(candidate_pool.get("count") or 0)
        signal_count = int(signals.get("recent_count") or 0)
        latest_signal_label = str(signals.get("latest_signal_label") or "暂无信号")
        open_count = int(virtual_trades.get("open_count") or 0)
        closed_count = int(virtual_trades.get("closed_count") or 0)
        monitor_label = str(monitor_session.get("status_label") or health.get("status_label") or "未知")
        generated_label = str(meta.get("generated_label") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        ai_link = "正常" if self.llm.is_available else "不可用"

        return (
            "AI管家系统体检：\n"
            f"- AI链路：{ai_link}\n"
            f"- 运行状态：{monitor_label}\n"
            f"- 候选池：{candidate_count} 只\n"
            f"- 近期信号：{signal_count} 条（最新：{latest_signal_label}）\n"
            f"- 交易跟踪：在场 {open_count} / 已平仓 {closed_count}\n"
            f"- 快照时间：{generated_label}\n"
            "结论：系统已进入AI管家可服务状态，可继续用自然语言下达查询和受控动作。"
        )

    def _answer_candidate_pool_query(self, user_input: str) -> Optional[str]:
        query = user_input or ""
        if "候选池" not in query:
            return None
        if any(k in query for k in ["清空候选池", "删除候选池"]):
            return None

        pool_path = DATA_CACHE_DIR / "candidate_pool.json"
        if not pool_path.exists():
            return "当前未检测到候选池文件，请先执行选股流程。"
        try:
            payload = json.loads(pool_path.read_text(encoding="utf-8"))
        except Exception:
            return "候选池文件读取失败，请重试。"

        candidates = list(payload.get("candidates") or [])
        if not candidates:
            return "当前候选池为空。可执行“确认选股”让系统重新生成候选池。"

        top_rows = []
        for item in candidates[:5]:
            code = str(item.get("ts_code") or item.get("symbol") or "--")
            name = str(item.get("name") or code)
            try:
                score = float(item.get("score", item.get("total_score", 0)) or 0)
            except Exception:
                score = 0.0
            top_rows.append(f"{code} {name}（{score:.1f}）")

        return (
            f"候选池概览（{payload.get('date', '--')}）：\n"
            f"- 总数：{len(candidates)}\n"
            "- Top5：\n"
            + "\n".join(f"  {idx + 1}. {row}" for idx, row in enumerate(top_rows))
        )

    def _answer_signal_summary_query(self, user_input: str) -> Optional[str]:
        query = user_input or ""
        if not any(k in query for k in ["信号", "告警", "触发", "异动"]):
            return None
        if any(k in query for k in ["买入条件", "符合买吗", "走势如何", "满足条件"]):
            return None

        snapshot = self._read_dashboard_snapshot()
        signals = (snapshot.get("signals") or {}) if isinstance(snapshot, dict) else {}
        items = list(signals.get("latest_items") or [])
        if not items:
            return "当前暂无最新信号记录。"

        rows = []
        for item in items[:5]:
            ts_code = str(item.get("ts_code") or item.get("symbol") or "--")
            signal_type = str(item.get("signal_type") or item.get("direction_label") or "SIGNAL")
            trigger_time = str(item.get("trigger_time") or item.get("created_at") or "--")
            rows.append(f"{ts_code} {signal_type} @ {trigger_time}")

        return (
            f"最新信号摘要（共 {len(items)} 条，展示前5条）：\n"
            + "\n".join(f"- {row}" for row in rows)
        )

    def _answer_holding_risk_query(self, user_input: str) -> Optional[str]:
        query = user_input or ""
        risk_keys = ["持仓风险", "风险扫描", "风险检查", "风控检查", "风险概览"]
        if not any(k in query for k in risk_keys):
            return None

        vt_path = DATA_CACHE_DIR / "virtual_trades.json"
        if not vt_path.exists():
            return "当前没有持仓追踪数据，暂时无法执行风险扫描。"
        try:
            payload = json.loads(vt_path.read_text(encoding="utf-8"))
        except Exception:
            return "持仓追踪数据读取失败，暂时无法执行风险扫描。"

        open_trades = list(payload.get("open_trades") or [])
        if not open_trades:
            return "当前无在场持仓，风险扫描完成：无高风险持仓。"

        high_risk = []
        watch_list = []
        for item in open_trades:
            symbol = str(item.get("symbol") or item.get("ts_code") or "--")
            name = str(item.get("name") or symbol)
            pnl_pct_raw = item.get("pnl_pct")
            try:
                pnl_pct = float(pnl_pct_raw) * 100 if pnl_pct_raw is not None else None
            except Exception:
                pnl_pct = None
            if pnl_pct is None:
                watch_list.append(f"{symbol} {name}: 未返回实时盈亏，建议手动复核")
                continue
            if pnl_pct <= -5:
                high_risk.append(f"{symbol} {name}: {pnl_pct:.2f}%（触发止损关注区）")
            elif pnl_pct >= 8:
                watch_list.append(f"{symbol} {name}: {pnl_pct:.2f}%（可考虑分批止盈/移动止损）")

        if not high_risk and not watch_list:
            return (
                f"持仓风险扫描完成：共 {len(open_trades)} 笔在场持仓，"
                "当前未发现显著高风险信号。"
            )

        lines = [f"持仓风险扫描完成：在场 {len(open_trades)} 笔。"]
        if high_risk:
            lines.append("高风险关注：")
            lines.extend(f"- {row}" for row in high_risk[:5])
        if watch_list:
            lines.append("策略建议：")
            lines.extend(f"- {row}" for row in watch_list[:5])
        return "\n".join(lines)

    def _answer_today_todo_query(self, user_input: str) -> Optional[str]:
        query = user_input or ""
        if not any(k in query for k in ["今日待办", "今天要做什么", "今天做什么", "接下来做什么", "行动建议"]):
            return None

        snapshot = self._read_dashboard_snapshot()
        market_session = ((snapshot.get("meta") or {}).get("market_session") or {}) if isinstance(snapshot, dict) else {}
        session_label = str(market_session.get("status_label") or market_session.get("session_label") or "未知时段")
        candidate_count = int(((snapshot.get("candidate_pool") or {}).get("count") or 0) if isinstance(snapshot, dict) else 0)
        signal_count = int(((snapshot.get("signals") or {}).get("recent_count") or 0) if isinstance(snapshot, dict) else 0)

        return (
            "AI管家今日待办建议：\n"
            f"- 当前时段：{session_label}\n"
            f"- 候选池存量：{candidate_count}，近期信号：{signal_count}\n"
            "- 建议动作1：先问“系统运行情况”确认链路健康\n"
            "- 建议动作2：再问“候选池现在怎么样”筛出重点标的\n"
            "- 建议动作3：盘中可问“最新信号摘要”并按确认词执行动作"
        )

    def _answer_capabilities_query(self, user_input: str) -> Optional[str]:
        query = (user_input or "").lower()
        keys = ["你会什么", "支持什么", "自然语言", "怎么用", "帮助", "help", "指令", "可执行动作"]
        if not any(k in query for k in keys):
            return None
        return (
            "AI管家当前支持：\n"
            "1) 运行巡检：系统运行情况 / 系统体检\n"
            "2) 候选池解读：候选池现在怎么样\n"
            "3) 信号追踪：最新信号摘要\n"
            "4) 绩效统计：最近10天我的胜率多少\n"
            "5) 个股判断：000001.SZ 现在走势如何，符合买入条件吗\n"
            "6) 持仓操作：确认新增持仓 000001.SZ 成本12.5 数量1000\n"
            "7) 持仓操作：确认删除持仓 000001.SZ\n"
            "8) 系统动作：确认选股 / 确认启动监控 / 确认生成交易计划\n"
            "说明：涉及执行动作默认需要“确认词”，保障安全。"
        )

    def _answer_recent_winrate_query(self, user_input: str) -> Optional[str]:
        query = user_input or ""
        if ("胜率" not in query) and ("win rate" not in query.lower()):
            return None

        m = re.search(r"(最近|近)\s*(\d{1,3})\s*天", query)
        days = int(m.group(2)) if m else 10
        days = max(1, min(days, 365))

        vt_path = DATA_CACHE_DIR / "virtual_trades.json"
        if not vt_path.exists():
            return "当前没有检测到虚拟交易记录，暂时无法计算胜率。"

        try:
            payload = json.loads(vt_path.read_text(encoding="utf-8"))
        except Exception:
            return "虚拟交易记录解析失败，暂时无法计算胜率。"

        closed = list(payload.get("closed_trades") or [])
        if not closed:
            return f"最近{days}天暂无已平仓交易，无法计算胜率。"

        now = datetime.now()
        in_window: List[Dict[str, Any]] = []
        for item in closed:
            sell_time = str(item.get("sell_time") or "").strip()
            if not sell_time:
                continue
            dt = None
            try:
                dt = datetime.fromisoformat(sell_time.replace("Z", "+00:00"))
            except Exception:
                try:
                    dt = datetime.strptime(sell_time[:19], "%Y-%m-%d %H:%M:%S")
                except Exception:
                    dt = None
            if dt is None:
                continue
            if (now - dt).days <= days:
                in_window.append(item)

        if not in_window:
            return f"最近{days}天没有平仓记录，暂无可统计胜率。"

        pnl = [float(item.get("pnl_pct", 0) or 0) for item in in_window]
        wins = sum(1 for x in pnl if x > 0)
        win_rate = wins / len(pnl)
        avg_pnl = sum(pnl) / len(pnl)
        return (
            f"最近{days}天战绩统计：\n"
            f"- 平仓笔数：{len(pnl)}\n"
            f"- 胜率：{win_rate:.2%}\n"
            f"- 平均收益：{avg_pnl:.2f}%\n"
            "说明：统计基于本地已平仓虚拟交易记录。"
        )

    def _answer_stock_buy_check(self, user_input: str) -> Optional[str]:
        query = user_input or ""
        if not any(k in query for k in ["买入条件", "符合买吗", "是否能买", "走势如何", "能买吗", "满足条件"]):
            return None

        symbol_match = re.search(r"\b(\d{6}(?:\.(?:SZ|SH))?)\b", query, re.IGNORECASE)
        if not symbol_match:
            return "请先提供股票代码，例如：000001.SZ 现在走势如何，符合我的买入条件吗？"
        symbol = symbol_match.group(1).upper()
        normalized = symbol.split(".", 1)[0]

        candidate_item = None
        try:
            pool_path = DATA_CACHE_DIR / "candidate_pool.json"
            if pool_path.exists():
                pool = json.loads(pool_path.read_text(encoding="utf-8"))
                for item in list(pool.get("candidates") or []):
                    code = str(item.get("ts_code", item.get("symbol", "")) or "").upper()
                    if code.split(".", 1)[0] == normalized:
                        candidate_item = item
                        break
        except Exception:
            candidate_item = None

        signal_rows: List[Dict[str, Any]] = []
        try:
            from src.services.dashboard_service import DashboardDataService

            snapshot = DashboardDataService(project_root=PROJECT_ROOT).build_snapshot()
            signal_rows = list(((snapshot.get("signals") or {}).get("latest_items")) or [])
        except Exception:
            signal_rows = []

        latest_signal = None
        for row in signal_rows:
            code = str(row.get("ts_code", "") or "").upper()
            if code.split(".", 1)[0] == normalized:
                latest_signal = row
                break

        try:
            score = float((candidate_item or {}).get("score", (candidate_item or {}).get("total_score", 0)) or 0)
        except Exception:
            score = 0.0

        in_pool = candidate_item is not None
        signal_ok = latest_signal is not None
        score_ok = score >= 70.0
        pass_buy = in_pool and signal_ok and score_ok

        return (
            f"{symbol} 买点条件检查：\n"
            f"- 候选池命中：{'是' if in_pool else '否'}\n"
            f"- 最新信号命中：{'是' if signal_ok else '否'}\n"
            f"- 评分阈值(>=70)：{'是' if score_ok else '否'}（当前 {score:.1f}）\n"
            f"- 结论：{'当前满足买入条件（可重点跟踪）' if pass_buy else '当前不满足完整买入条件（建议继续观察）'}\n"
            "说明：该结论基于本地候选池与最新信号快照，不构成投资建议。"
        )

    def _handle_manager_shortcuts(self, user_input: str) -> Optional[str]:
        for handler in (
            self._answer_capabilities_query,
            self._answer_system_health_query,
            self._answer_candidate_pool_query,
            self._answer_recent_winrate_query,
            self._answer_stock_buy_check,
            self._answer_signal_summary_query,
            self._answer_holding_risk_query,
            self._answer_today_todo_query,
        ):
            result = handler(user_input)
            if result:
                return result
        return None

    def chat(self, user_input: str, context: Optional[Dict[str, Any]] = None, clear_history: bool = False) -> str:
        if not self.llm.is_available:
            return "[AI链路不可用] 请先检查模型服务与配置。"

        if clear_history:
            self._conversation_history = []

        shortcut = self._handle_manager_shortcuts(user_input)
        if shortcut:
            self._conversation_history.append({"role": "user", "content": user_input})
            self._conversation_history.append({"role": "assistant", "content": shortcut})
            return shortcut

        if self._enable_actions:
            action_result = self._detect_and_execute_action(user_input)
            if action_result:
                self._conversation_history.append({"role": "user", "content": user_input})
                self._conversation_history.append({"role": "assistant", "content": action_result})
                return action_result

        system_data = self._read_system_data()
        context_blob = self._format_system_data(system_data)
        prompt = user_input
        if context_blob:
            prompt = f"[系统实时数据]\n{context_blob}\n\n[用户问题]\n{user_input}"

        response = self.llm.chat(
            prompt=prompt,
            system=self._system_prompt,
            temperature=self._default_temperature,
            max_tokens=self._default_max_tokens,
            timeout=self._default_timeout,
            history=self._conversation_history[-10:],
        )
        self._conversation_history.append({"role": "user", "content": user_input})
        self._conversation_history.append({"role": "assistant", "content": response})
        if len(self._conversation_history) > 20:
            self._conversation_history = self._conversation_history[-20:]
        return response

    def quick_ask(self, prompt_key: str, context: Optional[Dict[str, Any]] = None) -> str:
        prompt = self._quick_prompts.get(prompt_key)
        if not prompt:
            return f"未知预设问题: {prompt_key}，可选: {list(self._quick_prompts.keys())}"
        return self.chat(prompt, context=context, clear_history=True)

    def get_quick_prompt(self, prompt_key: str) -> str:
        prompt = self._quick_prompts.get(prompt_key)
        if not prompt:
            raise ValueError(f"未知预设问题: {prompt_key}，可选: {list(self._quick_prompts.keys())}")
        return prompt

    def chat_with_history(
        self,
        user_input: str,
        context: Optional[Dict[str, Any]] = None,
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        if not self.llm.is_available:
            return "[AI链路不可用] 请先检查模型服务与配置。"

        shortcut = self._handle_manager_shortcuts(user_input)
        if shortcut:
            return shortcut

        if self._enable_actions:
            action_result = self._detect_and_execute_action(user_input)
            if action_result:
                return action_result

        system_data = self._read_system_data()
        context_blob = self._format_system_data(system_data)
        prompt = user_input
        if context_blob:
            prompt = f"[系统实时数据]\n{context_blob}\n\n[用户问题]\n{user_input}"

        return self.llm.chat(
            prompt=prompt,
            system=self._system_prompt,
            temperature=self._default_temperature,
            max_tokens=self._default_max_tokens,
            timeout=self._default_timeout,
            history=(history or [])[-20:],
        )

    def generate_strategy_code(
        self,
        strategy_description: str,
        framework: str = "pandas",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> str:
        if not self.llm.is_available:
            return "[AI链路不可用]"

        prompt = (
            "请根据以下策略描述生成Python量化策略代码。\n"
            f"策略描述: {strategy_description}\n"
            f"框架: {framework}\n"
            "要求：包含数据获取、信号逻辑、回测入口、风控与中文注释。"
        )
        return self.llm.chat_with_code(
            prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )

    def explain_indicator(self, indicator_name: str, value: Any = None) -> str:
        if not self.llm.is_available:
            return f"{indicator_name}: {value}"
        value_text = f"，当前值: {value}" if value is not None else ""
        prompt = f"请解释技术指标 {indicator_name}{value_text} 的含义、使用方法和注意事项。"
        return self.chat(prompt, clear_history=True)

    def clear_history(self):
        self._conversation_history = []

    def get_history(self) -> List[Dict[str, str]]:
        return self._conversation_history.copy()

    def _format_context(self, context: Dict[str, Any]) -> str:
        # Backward-compatible helper, kept for callers that still pass context.
        return json.dumps(context or {}, ensure_ascii=False)

    def get_capabilities(self) -> Dict[str, Any]:
        return {
            "manager_shortcuts": [
                "系统运行情况",
                "候选池现在怎么样",
                "最新信号摘要",
                "最近10天我的胜率多少",
                "000001.SZ 现在走势如何，符合买入条件吗",
                "持仓风险扫描",
                "今天要做什么",
            ],
            "actions_enabled": self._enable_actions,
            "action_whitelist": sorted(self._action_whitelist),
            "require_action_confirmation": self._require_action_confirmation,
        }
