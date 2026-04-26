# -*- coding: utf-8 -*-
"""
选强→等突破→跟强留强 策略
盘前选股核心模块

设计原则：
  1. 所有因子计算在全主板截面上进行，确保横截面分位的严谨性
  2. 无未来信息泄露：盘前选股只用 T-1 及之前的已收盘数据
  3. 所有参数可配置，后续支持网格搜索最优参数
  4. 直接接入 DatabaseManager，复用现有数据基础设施

选股流程（五层过滤 + 评分排序）：
  Layer 1 - 基础过滤：主板 / 非ST / 上市≥60天 / 流动性 / 价格区间 / 非涨跌停
  Layer 2 - 趋势过滤：MA20 > MA60 > MA120 且 MA20斜率 > 0
  Layer 3 - 强度过滤：全主板横截面 RS20 分位 ≥ 80%
  Layer 4 - 走稳过滤：ATR14/close 60日分位 ≤ 50%，箱体宽度 ≤ 8%
  Layer 5 - 市场闸门：指数5日收益率过弱时提升评分门槛
  评分排序：多因子加权综合评分，输出 WatchList TopK
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.core.database import DatabaseManager
from src.core.config import ConfigManager
from src.core.logger import get_logger

logger = get_logger("breakout_strategy")


# ═══════════════════════════════════════════════════════════════
# 策略参数
# ═══════════════════════════════════════════════════════════════

@dataclass
class BreakoutParams:
    """
    选强→等突破 盘前选股参数
    所有阈值均可参数化，供网格搜索使用
    """

    # ── 标的过滤 ──
    min_list_days: int = 60          # 上市最少交易天数（排除新股高噪声期）
    min_amt_ma20: float = 8e4        # 20日均成交额下限（千元），8e4千元=8000万元（Tushare amount单位为千元）
    min_price: float = 5.0           # 股价下限
    max_price: float = 80.0          # 股价上限

    # ── 趋势参数 ──
    ma_short: int = 20               # 短期均线周期
    ma_mid: int = 60                 # 中期均线周期
    ma_long: int = 120               # 长期均线周期
    ma_slope_min: float = 0.0        # MA20斜率最低要求（相对5日前的变化率）

    # ── 强度参数 ──
    rs_lookback: int = 20            # RS计算回望天数
    rs_quantile_min: float = 0.80    # 全主板横截面 RS20 分位下限
    rs_quantile_max: float = 0.97    # RS分位上限（过滤极端妖股），1.0 表示不限制

    # ── 走稳参数 ──
    atr_period: int = 14             # ATR计算周期
    atr_quantile_max: float = 0.50   # ATR/close 60日分位上限（越低越稳）
    atr_quantile_window: int = 60    # ATR分位计算滚动窗口
    box_days: int = 10               # 箱体宽度计算天数
    box_max_range: float = 0.08      # 箱体最大宽度（相对收盘价），8%

    # ── 突破基准 ──
    pivot_days: int = 10             # 突破 pivot 计算窗口（不含当天）

    # ── 妖股过滤（不赌妖股）──
    max_limit_up_count_20d: int = 3  # 20日内最多涨停次数
    max_limit_down_count_20d: int = 1  # 20日内最多跌停次数

    # ── 市场环境闸门（三档：正常/谨慎/禁止开仓）──
    index_code: str = "000001.SH"            # 市场基准指数
    # 指数趋势：收盘价是否在MA20之上
    market_index_above_ma20: bool = True     # 要求指数在MA20上方才为正常市场
    # 指数短期动量
    market_ret3_caution: float = -0.01       # 3日收益<此值 → 谨慎档
    market_ret5_caution: float = -0.02       # 5日收益<此值 → 谨慎档
    market_ret3_stop: float = -0.025         # 3日收益<此值 → 禁止开仓
    market_ret5_stop: float = -0.04          # 5日收益<此值 → 禁止开仓
    # 市场广度（全主板上涨家数占比）
    market_breadth_caution: float = 0.40     # 上涨家数占比<此值 → 谨慎档
    market_breadth_stop: float = 0.30        # 上涨家数占比<此值 → 禁止开仓
    # 谨慎档动作
    caution_score_boost: float = 8.0         # 谨慎档评分门槛提升
    caution_topk_ratio: float = 0.4          # 谨慎档观察池缩减至40%

    # ── 突破确认参数（核心alpha来源）──
    breakout_buffer: float = 0.002   # 触发价 = pivot × (1 + buffer)，0.2%缓冲防止虚突
    breakout_max_chase: float = 0.008  # 最大追高限制（入场价不超过pivot的0.8%以上）
    volume_confirm_ratio: float = 1.2  # 放量确认倍数（当日量/20日均量 ≥ 此值视为A级；1.2 为信号量与胜率折中）
    volume_normal_ratio: float = 1.0  # 正常量能下限（≥1.0为B级信号，<1.0为缩量不买）
    max_intraday_gain: float = 0.05    # 当日涨幅上限（不追涨停板附近）
    max_hold_days: int = 4           # 最大持仓天数（时间止损）

    # ── v2 灰度保护：高分但确认弱的突破更像低波趋势尾段，默认关闭以保持生产兼容 ──
    enable_high_score_weak_confirm_guard: bool = False
    high_score_weak_confirm_score_min: float = 80.0
    high_score_weak_confirm_volume_min: float = 1.35
    enable_market_ret5_median_guard: bool = False
    market_ret5_median_stop: float = -0.01
    enable_trailing_exit_guard: bool = False
    exit_trail_arm_pct: float = 0.04
    exit_trailing_stop_pct: float = 0.025
    exit_fixed_stop_loss_pct: Optional[float] = None
    exit_use_weakness_rules: bool = True
    exit_grade_overrides: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # ── 选股输出 ──
    top_k: int = 15                  # 观察池最大股票数量
    min_signal_score: float = 60.0   # 最低综合评分（0~100）

    # ── 评分权重（各维度满分如下注释）──
    # RS横截面分位（0~35分）、趋势质量（0~25分）、走稳质量（0~20分）
    # 箱体紧密度（0~12分）、量能趋势（0~8分）
    weight_rs: float = 35.0
    weight_trend: float = 25.0
    weight_stability: float = 20.0
    weight_box: float = 12.0
    weight_volume: float = 8.0

    # ── 主板股票代码前缀 ──
    mainboard_sh_prefixes: Tuple[str, ...] = field(
        default_factory=lambda: ("600", "601", "603", "605")
    )
    mainboard_sz_prefixes: Tuple[str, ...] = field(
        default_factory=lambda: ("000", "001", "002", "003")
    )


def get_breakout_params_for_backtest(preset: str, use_ma120: bool) -> BreakoutParams:
    """
    回测脚本用参数预设。

    预设说明：
      - baseline：选股 + 买点均与历史主报告默认一致。
      - selection_relaxed_v1：仅放宽选股；买点与 baseline 相同（用于拉频率）。
      - win_rate_priority：选股与 baseline **完全相同**；仅收紧买点（提高纯度/胜率倾向，
        成交频率通常下降）。
      - wide_pool_strict_entry_v1：**选股**同 selection_relaxed_v1（池更大），**买点**同
        win_rate_priority（确认更严）；用于在「机会面」与「成交质量」之间折中，需回测验证。
      - wide_pool_strict_entry_v2：选股同 selection_relaxed_v1，**买点**同 buy_tuning_v1（比 v1
        更严一档）；用于检验「宽池 + 最严买点」是否优于 v1 / baseline。
      - buy_tuning_v1：选股同 baseline；在 win_rate_priority 基础上 **进一步收紧** 缓冲、量能与
        日内涨幅，用于买点专项优化（成交频率通常再降，需样本外验证）。

    Args:
        preset: baseline / selection_relaxed_v1 / win_rate_priority /
            wide_pool_strict_entry_v1 / wide_pool_strict_entry_v2 / buy_tuning_v1
        use_ma120: 是否使用 MA120 趋势过滤（与回测脚本入参对齐）
    """
    key = (preset or "baseline").strip().lower()
    p = BreakoutParams()
    p.min_amt_ma20 = 8e4
    p.rs_quantile_max = 0.97
    p.volume_confirm_ratio = 1.2
    p.volume_normal_ratio = 1.0

    if key == "baseline":
        p.rs_quantile_min = 0.80
        p.min_signal_score = 60.0
        p.top_k = 20
        p.atr_quantile_max = 0.50
        p.box_max_range = 0.08
        return p

    if key == "selection_relaxed_v1":
        p.rs_quantile_min = 0.78
        p.min_signal_score = 58.0
        p.top_k = 28
        p.atr_quantile_max = 0.55
        p.box_max_range = 0.095
        return p

    if key == "win_rate_priority":
        # 选股与 baseline 一致
        p.rs_quantile_min = 0.80
        p.min_signal_score = 60.0
        p.top_k = 20
        p.atr_quantile_max = 0.50
        p.box_max_range = 0.08
        # 买点收紧：减少假突破与缩量跟风
        p.breakout_buffer = 0.003
        p.breakout_max_chase = 0.006
        p.volume_confirm_ratio = 1.35
        p.volume_normal_ratio = 1.05
        p.max_intraday_gain = 0.04
        return p

    if key == "buy_tuning_v1":
        p.rs_quantile_min = 0.80
        p.min_signal_score = 60.0
        p.top_k = 20
        p.atr_quantile_max = 0.50
        p.box_max_range = 0.08
        p.breakout_buffer = 0.004
        p.breakout_max_chase = 0.005
        p.volume_confirm_ratio = 1.42
        p.volume_normal_ratio = 1.08
        p.max_intraday_gain = 0.035
        return p

    if key == "wide_pool_strict_entry_v1":
        # 选股层：selection_relaxed_v1
        p.rs_quantile_min = 0.78
        p.min_signal_score = 58.0
        p.top_k = 28
        p.atr_quantile_max = 0.55
        p.box_max_range = 0.095
        # 买点层：win_rate_priority
        p.breakout_buffer = 0.003
        p.breakout_max_chase = 0.006
        p.volume_confirm_ratio = 1.35
        p.volume_normal_ratio = 1.05
        p.max_intraday_gain = 0.04
        return p

    if key == "wide_pool_strict_entry_v2":
        # 选股层：selection_relaxed_v1
        p.rs_quantile_min = 0.78
        p.min_signal_score = 58.0
        p.top_k = 28
        p.atr_quantile_max = 0.55
        p.box_max_range = 0.095
        # 买点层：buy_tuning_v1
        p.breakout_buffer = 0.004
        p.breakout_max_chase = 0.005
        p.volume_confirm_ratio = 1.42
        p.volume_normal_ratio = 1.08
        p.max_intraday_gain = 0.035
        return p

    if key == "optuna_optimized_v1":
        # Optuna三阶段优化后的最优参数（2026-04-14）
        # 样本内: T1胜率50.31%, T1收益0.0473%
        # 样本外: T1胜率59.62%, T1收益1.28%
        p.rs_quantile_min = 0.80
        p.rs_quantile_max = 0.97
        p.min_signal_score = 60.0
        p.top_k = 15
        p.atr_quantile_max = 0.50
        p.box_max_range = 0.08
        # 评分权重（优化后）
        p.weight_rs = 35.0
        p.weight_trend = 25.0
        p.weight_stability = 20.0
        p.weight_box = 12.0
        p.weight_volume = 8.0
        return p

    raise ValueError(
        f"未知回测预设: {preset!r}，支持: baseline, selection_relaxed_v1, "
        f"win_rate_priority, wide_pool_strict_entry_v1, wide_pool_strict_entry_v2, buy_tuning_v1, optuna_optimized_v1"
    )


_BREAKOUT_PRESET_KEYS = frozenset(
    {
        "baseline",
        "selection_relaxed_v1",
        "win_rate_priority",
        "wide_pool_strict_entry_v1",
        "wide_pool_strict_entry_v2",
        "buy_tuning_v1",
        "optuna_optimized_v1",
    }
)


def resolve_breakout_preset_from_config(config: Optional[ConfigManager]) -> str:
    """
    从 config.yaml 的 stock_selection.breakout.params_preset 读取预设名。

    未配置或非法值时回退 baseline，并打日志。
    """
    if config is None:
        return "baseline"
    raw = config.get("stock_selection.breakout", {}) or {}
    if not isinstance(raw, dict):
        return "baseline"
    preset = str(raw.get("params_preset") or "baseline").strip().lower()
    if preset not in _BREAKOUT_PRESET_KEYS:
        logger.warning("未知突破参数预设 %s，已回退 baseline", preset)
        return "baseline"
    return preset


def _resolve_use_ma120_for_breakout(db: DatabaseManager) -> bool:
    """与回测脚本对齐：样本交易日足够时传入 use_ma120=True（预设内部可扩展分支）。"""
    row = db.query_one("SELECT COUNT(DISTINCT trade_date) AS c FROM stock_daily")
    ntd = int(row["c"]) if row and row.get("c") is not None else 0
    return ntd >= 180


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _apply_breakout_runtime_config(params: BreakoutParams, raw: Dict[str, Any]) -> BreakoutParams:
    """把灰度入场与退出配置应用到突破参数，标准突破/宽进突破共用。"""
    guard = raw.get("high_score_weak_confirm_guard", {}) or {}
    if isinstance(guard, dict):
        params.enable_high_score_weak_confirm_guard = _coerce_bool(guard.get("enabled"), False)
        if guard.get("score_min") is not None:
            params.high_score_weak_confirm_score_min = float(guard.get("score_min"))
        if guard.get("volume_min") is not None:
            params.high_score_weak_confirm_volume_min = float(guard.get("volume_min"))

    market_guard = raw.get("market_ret5_median_guard", {}) or {}
    if isinstance(market_guard, dict):
        params.enable_market_ret5_median_guard = _coerce_bool(market_guard.get("enabled"), False)
        if market_guard.get("stop") is not None:
            params.market_ret5_median_stop = float(market_guard.get("stop"))

    exit_guard = raw.get("exit_guard", {}) or {}
    if isinstance(exit_guard, dict):
        if exit_guard.get("max_hold_days") is not None:
            params.max_hold_days = int(exit_guard.get("max_hold_days"))
        params.enable_trailing_exit_guard = _coerce_bool(exit_guard.get("trailing_enabled"), False)
        if exit_guard.get("trail_arm_pct") is not None:
            params.exit_trail_arm_pct = float(exit_guard.get("trail_arm_pct"))
        if exit_guard.get("trailing_stop_pct") is not None:
            params.exit_trailing_stop_pct = float(exit_guard.get("trailing_stop_pct"))
        if exit_guard.get("fixed_stop_loss_pct") is not None:
            params.exit_fixed_stop_loss_pct = float(exit_guard.get("fixed_stop_loss_pct"))
        params.exit_use_weakness_rules = _coerce_bool(exit_guard.get("use_weakness_rules"), True)
        grade_overrides = exit_guard.get("grade_overrides", {}) or {}
        if isinstance(grade_overrides, dict):
            params.exit_grade_overrides = {
                str(k).upper(): v
                for k, v in grade_overrides.items()
                if isinstance(v, dict)
            }
    return params


def build_breakout_strategy_from_config(
    db: DatabaseManager,
    config: Optional[ConfigManager] = None,
) -> BreakoutStrategy:
    """
    按配置构建突破策略实例（菜单、主程序一键选股、看板后台任务共用）。

    配置路径：stock_selection.breakout.params_preset
    """
    preset = resolve_breakout_preset_from_config(config)
    use_ma120 = _resolve_use_ma120_for_breakout(db)
    params = get_breakout_params_for_backtest(preset, use_ma120)
    if config is not None:
        raw = config.get("stock_selection.breakout", {}) or {}
        if isinstance(raw, dict):
            _apply_breakout_runtime_config(params, raw)
    return BreakoutStrategy(db=db, params=params)


def build_wide_breakout_strategy_from_config(
    db: DatabaseManager,
    config: Optional[ConfigManager] = None,
) -> BreakoutStrategy:
    """
    宽进突破策略：选股层同「放宽选股」、买点层同 buy_tuning_v1（回测预设 wide_pool_strict_entry_v2）。

    与 `build_breakout_strategy_from_config` 独立，不读取 params_preset，供专用菜单与一键选股入口。
    配置路径：stock_selection.wide_breakout。若未配置则保持纯 wide_pool_strict_entry_v2。
    """
    use_ma120 = _resolve_use_ma120_for_breakout(db)
    params = get_breakout_params_for_backtest("wide_pool_strict_entry_v2", use_ma120)
    if config is not None:
        raw = config.get("stock_selection.wide_breakout", {}) or {}
        if isinstance(raw, dict):
            _apply_breakout_runtime_config(params, raw)
    return BreakoutStrategy(db=db, params=params)


# ═══════════════════════════════════════════════════════════════
# 选股结果数据类
# ═══════════════════════════════════════════════════════════════

@dataclass
class WatchItem:
    """观察池单只股票记录"""
    ts_code: str
    name: str
    watch_date: str
    close: float
    pivot: float           # 近N日最高价，突破基准
    trigger_price: float   # 触发价 = pivot * (1 + buffer)
    stop_loss: float       # 初始止损价
    atr14: float           # ATR14绝对值
    rs20: float            # 近20日收益率
    rs20_xsec_q: float     # 全主板横截面RS20分位
    atr_ratio_q60: float   # ATR/close 60日分位
    box_range: float       # 10日箱体宽度
    ma20: float
    ma60: float
    ma120: float
    signal_score: float    # 综合评分
    score_detail: str      # 评分细节
    industry: str = ""


@dataclass
class BreakoutSignal:
    """
    经突破确认后的交易信号

    信号分级（基于日线近似回测，实盘以分钟级确认为准）：
      A级（突破+放量≥volume_confirm_ratio）→ 建议正常仓位
      B级（突破+量能≥volume_normal_ratio）→ 建议半仓
      不买（突破但缩量<1.0x）: 过滤掉
    """
    ts_code: str
    name: str
    signal_date: str          # 盘前选股日期
    confirm_date: str         # 突破确认日期（T+1）
    entry_price: float        # 实际入场价（突破触发价）
    pivot: float              # 突破基准
    stop_loss: float          # 初始止损价
    atr14: float
    signal_score: float       # 盘前综合评分
    volume_ratio: float       # 确认当日量比（vol/vol_ma20）
    confirm_type: str         # 确认类型："breakout" / "breakout+volume"
    signal_grade: str = "B"   # 信号等级："A"=突破+放量 / "B"=突破+正常量能
    position_ratio: float = 1.0  # 建议仓位比例（A=1.0, B=0.5）
    industry: str = ""


# ═══════════════════════════════════════════════════════════════
# 主策略类
# ═══════════════════════════════════════════════════════════════

class BreakoutStrategy:
    """
    选强→等突破→跟强留强 盘前选股策略

    典型用法：
        strategy = BreakoutStrategy(db, params)
        watch_list = strategy.run(end_date="20240315")
    """

    def __init__(
        self,
        db: DatabaseManager,
        params: Optional[BreakoutParams] = None,
    ):
        self.db = db
        self.params = params or BreakoutParams()

    def resolve_exit_plan(self, signal_grade: Optional[str] = None) -> Dict[str, Any]:
        """返回指定信号等级的退出参数，供看板/持仓管理复用。"""
        p = self.params
        grade = str(signal_grade or "").upper()
        override = dict(getattr(p, "exit_grade_overrides", {}).get(grade, {}) or {})
        fixed_stop = override.get("fixed_stop_loss_pct", p.exit_fixed_stop_loss_pct)
        plan = {
            "max_hold_days": int(override.get("max_hold_days", p.max_hold_days)),
            "trailing_enabled": bool(getattr(p, "enable_trailing_exit_guard", False)),
            "trail_arm_pct": float(override.get("trail_arm_pct", p.exit_trail_arm_pct)),
            "trailing_stop_pct": float(override.get("trailing_stop_pct", p.exit_trailing_stop_pct)),
            "fixed_stop_loss_pct": None if fixed_stop is None else float(fixed_stop),
            "use_weakness_rules": bool(override.get("use_weakness_rules", p.exit_use_weakness_rules)),
        }
        if grade:
            plan["signal_grade"] = grade
        return plan

    def export_exit_plan(self) -> Dict[str, Any]:
        """导出基础退出方案和分级覆盖，写入候选池/看板缓存。"""
        p = self.params
        grades = sorted(set(["A", "B", *getattr(p, "exit_grade_overrides", {}).keys()]))
        return {
            "base": self.resolve_exit_plan(),
            "by_grade": {grade: self.resolve_exit_plan(grade) for grade in grades},
        }

    # ───────────────────────────────────────────
    # 公开主接口
    # ───────────────────────────────────────────

    def run(self, end_date: str = None) -> List[WatchItem]:
        """
        执行盘前选股，返回观察池列表

        Args:
            end_date: 目标日期 YYYYMMDD（默认取数据库最新交易日）

        Returns:
            按综合评分排序的观察池列表
        """
        resolved = self._resolve_end_date(end_date)
        logger.info("═" * 60)
        logger.info("开始盘前选股 [%s]", resolved)

        # 1. 拉取全主板原始数据
        raw_daily, raw_basic = self._load_data(resolved)
        if raw_daily.empty or raw_basic.empty:
            logger.warning("数据不足，无法执行选股")
            return []

        # 2. 计算全部因子
        features = self._compute_features(raw_daily, raw_basic, resolved)
        if features.empty:
            logger.warning("因子计算结果为空")
            return []

        return self.select_watchlist_from_features(features, resolved)

    def select_watchlist_from_features(
        self,
        features: pd.DataFrame,
        resolved: str,
    ) -> List[WatchItem]:
        """
        在已算好的全量 features 上执行与 run() 相同的选股流水线（便于批量导出历史观察池）。
        """
        resolved = str(resolved)

        # 截面过滤（取截止 end_date 最新一行）
        snapshot = self._build_snapshot(features, resolved)
        if snapshot.empty:
            logger.warning("截面快照为空 [%s]", resolved)
            return []

        layer_log = {"total": len(snapshot)}

        # Layer 1: 基础硬过滤
        snapshot = self._layer_base_filter(snapshot)
        layer_log["after_base"] = len(snapshot)

        # Layer 2~4：历史交易日 < 180 时降级
        n_td = self._count_trade_days_up_to(resolved)
        use_ma120_trend = n_td >= 180
        p = self.params

        if use_ma120_trend:
            snapshot = self._layer_trend_filter(snapshot)
        else:
            cond2 = (
                snapshot["ma20"].notna()
                & snapshot["ma60"].notna()
                & (snapshot["ma20"] > snapshot["ma60"])
                & (snapshot["ma20_slope"].fillna(-1) > p.ma_slope_min)
            )
            snapshot = snapshot.loc[cond2].copy()
            logger.debug(
                "趋势过滤已降级: 截止%s仅%d个交易日(<180)，使用 MA20>MA60",
                resolved,
                n_td,
            )
        layer_log["after_trend"] = len(snapshot)

        # Layer 3: 强度过滤（全主板 RS20 横截面分位）
        snapshot = self._layer_strength_filter(snapshot)
        layer_log["after_strength"] = len(snapshot)

        # Layer 4: 走稳过滤
        if use_ma120_trend:
            snapshot = self._layer_stability_filter(snapshot)
        else:
            if not snapshot.empty:
                cond4 = snapshot["box_range"].notna() & (
                    snapshot["box_range"] <= p.box_max_range
                )
                if snapshot["atr_ratio_q60"].notna().mean() > 0.3:
                    cond4 = cond4 & (
                        snapshot["atr_ratio_q60"].fillna(0.5) <= p.atr_quantile_max
                    )
                snapshot = snapshot.loc[cond4].copy()
        layer_log["after_stability"] = len(snapshot)

        logger.info(
            "过滤漏斗[%s]: 全量%d → 基础%d → 趋势%d → 强度%d → 走稳%d",
            resolved,
            layer_log["total"],
            layer_log["after_base"],
            layer_log["after_trend"],
            layer_log["after_strength"],
            layer_log["after_stability"],
        )

        if snapshot.empty:
            logger.info("选股结果：0只（过滤过严或市场无强势标的）[%s]", resolved)
            return []

        # 综合评分
        snapshot = self._compute_scores(snapshot)

        # 市场闸门（动态调整门槛和数量）
        min_score, top_k = self._market_gate(features, resolved)
        snapshot = snapshot[snapshot["signal_score"] >= min_score].copy()
        if snapshot.empty:
            logger.info("选股结果：0只（未达市场闸门评分 %.1f）[%s]", min_score, resolved)
            return []

        # 排序取 TopK
        snapshot = snapshot.sort_values("signal_score", ascending=False).head(top_k)
        logger.info(
            "选股完成[%s]：%d只进入观察池（门槛%.1f，TopK%d）",
            resolved,
            len(snapshot),
            min_score,
            top_k,
        )

        return self._to_watch_items(snapshot, resolved)

    # ───────────────────────────────────────────
    # 数据加载
    # ───────────────────────────────────────────

    def _resolve_end_date(self, end_date: str = None) -> str:
        """解析选股锚点日期，默认取数据库最新交易日"""
        if end_date:
            return str(end_date)
        latest = self.db.get_latest_trade_date("stock_daily")
        if latest:
            return str(latest)
        return datetime.now().strftime("%Y%m%d")

    def _count_trade_days_up_to(self, end_date: str) -> int:
        """截止 end_date（含）的 stock_daily 交易日数量，用于是否启用 MA120 趋势。"""
        try:
            rows = self.db.query(
                "SELECT COUNT(DISTINCT trade_date) AS c FROM stock_daily WHERE trade_date <= ?",
                (str(end_date),),
            )
            if rows and rows[0].get("c") is not None:
                return int(rows[0]["c"])
        except Exception as e:
            logger.debug("统计交易日失败: %s", e)
        return 0

    def _load_data(self, end_date: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        加载全主板日线数据 + 基础信息
        预留足够的历史深度用于因子计算（MA120 需要至少120交易日）
        """
        p = self.params
        end_dt = datetime.strptime(end_date, "%Y%m%d")
        # 预留 180 自然日保证 MA120、60日ATR分位等因子有足够历史
        start_dt = end_dt - timedelta(days=365)
        start_date = start_dt.strftime("%Y%m%d")

        # 拼接 LIKE 条件覆盖沪深主板
        sh_likes = " OR ".join(f"ts_code LIKE '{p}%.SH'" for p in p.mainboard_sh_prefixes)
        sz_likes = " OR ".join(f"ts_code LIKE '{p}%.SZ'" for p in p.mainboard_sz_prefixes)
        mb_cond = f"({sh_likes} OR {sz_likes})"

        sql_daily = f"""
            SELECT ts_code, trade_date, open, high, low, close, vol, amount, pct_chg
            FROM stock_daily
            WHERE trade_date >= ? AND trade_date <= ?
              AND ({mb_cond})
            ORDER BY ts_code ASC, trade_date ASC
        """
        # 基准指数（如 000001.SH）代码为 000 开头但在沪市，主板 LIKE 条件不会包含，必须单独加载
        sql_index = """
            SELECT ts_code, trade_date, open, high, low, close, vol, amount, pct_chg
            FROM stock_daily
            WHERE trade_date >= ? AND trade_date <= ?
              AND ts_code = ?
            ORDER BY trade_date ASC
        """
        sql_basic = """
            SELECT ts_code, name, industry, list_date
            FROM stock_basic
        """
        try:
            daily_rows = self.db.query(sql_daily, (start_date, end_date))
            index_rows = self.db.query(sql_index, (start_date, end_date, p.index_code))
            basic_rows = self.db.query(sql_basic)
        except Exception as e:
            logger.error("数据库查询失败: %s", e)
            return pd.DataFrame(), pd.DataFrame()

        daily = pd.DataFrame(daily_rows) if daily_rows else pd.DataFrame()
        idx_df = pd.DataFrame(index_rows) if index_rows else pd.DataFrame()
        if not idx_df.empty:
            daily = pd.concat([daily, idx_df], ignore_index=True)
            daily = daily.drop_duplicates(subset=["ts_code", "trade_date"], keep="last")

        basic = pd.DataFrame(basic_rows) if basic_rows else pd.DataFrame()
        if not basic.empty and p.index_code not in basic["ts_code"].astype(str).values:
            idx_basic_row = pd.DataFrame(
                [
                    {
                        "ts_code": p.index_code,
                        "name": "上证指数",
                        "industry": "指数",
                        "list_date": "19901219",
                    }
                ]
            )
            basic = pd.concat([basic, idx_basic_row], ignore_index=True)
        elif basic.empty:
            logger.warning("stock_basic 为空，无法合并个股基础信息")

        logger.info("数据加载完成：日线 %d 行（含基准指数），基础信息 %d 行", len(daily), len(basic))
        return daily, basic

    # ───────────────────────────────────────────
    # 因子计算（全历史，不截断）
    # ───────────────────────────────────────────

    def _compute_features(
        self,
        daily: pd.DataFrame,
        basic: pd.DataFrame,
        end_date: str,
    ) -> pd.DataFrame:
        """
        计算所有策略因子，按股票分组向量化计算

        注意：所有计算基于历史数据，不引入任何未来信息
        """
        p = self.params

        # 数据清洗
        df = daily.copy()
        for col in ["open", "high", "low", "close", "vol", "amount", "pct_chg"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str), format="%Y%m%d", errors="coerce")
        df = df.dropna(subset=["trade_date", "ts_code", "close", "high", "low"]).copy()
        df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

        # 合并基础信息
        basic = basic[["ts_code", "name", "industry", "list_date"]].copy()
        basic["list_date"] = pd.to_datetime(
            basic["list_date"].astype(str).str[:8], format="%Y%m%d", errors="coerce"
        )
        df = df.merge(basic, on="ts_code", how="left")

        g = df.groupby("ts_code", group_keys=False)

        # ── 均线 ──
        for win, col in [
            (5, "ma5"), (p.ma_short, "ma20"),
            (p.ma_mid, "ma60"), (p.ma_long, "ma120"),
        ]:
            df[col] = g["close"].transform(
                lambda s, w=win: s.rolling(w, min_periods=w).mean()
            )

        # MA20 斜率（相对5日前的变化率，正值=上升）
        df["ma20_slope"] = g["ma20"].transform(lambda s: s / s.shift(5) - 1.0)

        # ── 收益率因子 ──
        df["ret_1d"] = g["close"].pct_change()
        df["rs20"] = g["close"].transform(
            lambda s: s / s.shift(p.rs_lookback) - 1.0
        )
        df["ret3"] = g["close"].transform(lambda s: s / s.shift(3) - 1.0)
        df["ret5"] = g["close"].transform(lambda s: s / s.shift(5) - 1.0)

        # ── 量能因子 ──
        df["vol_ma5"] = g["vol"].transform(lambda s: s.rolling(5).mean())
        df["vol_ma20"] = g["vol"].transform(lambda s: s.rolling(20).mean())
        df["amt_ma20"] = g["amount"].transform(lambda s: s.rolling(20).mean())

        # ── ATR14 ──
        df["atr14"] = g.apply(
            lambda sub: self._calc_atr(sub["high"], sub["low"], sub["close"], p.atr_period)
        ).reset_index(level=0, drop=True)
        df["atr_ratio"] = df["atr14"] / df["close"].replace(0, np.nan)

        # ATR/close 在个股自身60日历史内的滚动分位（越低=越稳）
        df["atr_ratio_q60"] = g["atr_ratio"].transform(
            lambda s: s.rolling(p.atr_quantile_window, min_periods=20).rank(pct=True)
        )

        # ── 箱体宽度 ──
        # shift(1) 保证 pivot 不含当天（防止用当天最高价自我触发）
        hh = g["high"].transform(lambda s: s.shift(1).rolling(p.box_days).max())
        ll = g["low"].transform(lambda s: s.shift(1).rolling(p.box_days).min())
        df["box_range"] = (hh - ll) / df["close"].replace(0, np.nan)

        # ── 突破 pivot（近N日最高价，不含当天）──
        df["pivot"] = g["high"].transform(
            lambda s: s.shift(1).rolling(p.pivot_days).max()
        )
        # 近N日最低价（用于止损基准）
        df["ll_n"] = g["low"].transform(
            lambda s: s.shift(1).rolling(p.pivot_days).min()
        )

        # ── 涨跌停识别 ──
        df["is_limit_up"] = (df["pct_chg"] >= 9.7) & (df["close"] >= df["high"] * 0.999)
        df["is_limit_down"] = (df["pct_chg"] <= -9.7) & (df["close"] <= df["low"] * 1.001)
        df["limit_up_count_20"] = g["is_limit_up"].transform(
            lambda s: s.rolling(20, min_periods=1).sum()
        )
        df["limit_down_count_20"] = g["is_limit_down"].transform(
            lambda s: s.rolling(20, min_periods=1).sum()
        )

        # ── 上市天数 ──
        df["list_days"] = (df["trade_date"] - df["list_date"]).dt.days

        # ── 全主板横截面 RS20 分位（按交易日截面，全主板排名）──
        # 基准指数不参与分位排序，避免污染横截面分布
        df["rs20_xsec_q"] = np.nan
        valid_mask = (
            df["rs20"].notna()
            & df["list_days"].fillna(0).gt(p.min_list_days)
            & (df["ts_code"].astype(str) != str(p.index_code))
        )
        for date_val, grp_idx in df[valid_mask].groupby("trade_date").groups.items():
            rs_vals = df.loc[grp_idx, "rs20"]
            if len(rs_vals) > 10:  # 截面样本过小则跳过
                df.loc[grp_idx, "rs20_xsec_q"] = rs_vals.rank(pct=True, method="average")

        logger.info("因子计算完成，共 %d 行", len(df))
        return df

    @staticmethod
    def _calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
        """计算 ATR（真实波幅均值）"""
        prev_close = close.shift(1)
        tr = pd.concat([
            (high - low),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)
        return tr.rolling(period, min_periods=period).mean()

    # ───────────────────────────────────────────
    # 截面快照（取每股最新一行）
    # ───────────────────────────────────────────

    def _build_snapshot(self, features: pd.DataFrame, end_date: str) -> pd.DataFrame:
        """
        构建截面快照：取每只股票在 end_date 当天或之前的最新一行
        这保证了"盘前只用已收盘数据"的严谨性
        """
        target = pd.Timestamp(end_date)
        prev = features[features["trade_date"] <= target].copy()
        if prev.empty:
            return pd.DataFrame()

        snapshot = (
            prev.sort_values(["ts_code", "trade_date"])
            .groupby("ts_code", group_keys=False)
            .tail(1)
            .copy()
        )
        return snapshot.reset_index(drop=True)

    # ───────────────────────────────────────────
    # 五层过滤
    # ───────────────────────────────────────────

    def _layer_base_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Layer 1 基础硬过滤
        - 主板代码（由SQL已过滤，此处作二次校验）
        - 非ST/非退市
        - 上市≥60天
        - 价格区间 [5, 80]
        - 20日均成交额≥8000万
        - 不处于涨跌停状态
        - 近20日涨停次数≤3（不赌妖股）
        - 近20日跌停次数≤1
        """
        p = self.params
        name_col = "name" if "name" in df.columns else None

        cond = (
            (df["close"].between(p.min_price, p.max_price))
            & (df["amt_ma20"].fillna(0) >= p.min_amt_ma20)
            & (df["list_days"].fillna(0) >= p.min_list_days)
            & (~df["is_limit_up"].fillna(False))
            & (~df["is_limit_down"].fillna(False))
            & (df["limit_up_count_20"].fillna(0) <= p.max_limit_up_count_20d)
            & (df["limit_down_count_20"].fillna(0) <= p.max_limit_down_count_20d)
            & (df["vol"].fillna(0) > 0)
            & (df["close"].fillna(0) > 0)
            & (df["pivot"].notna())
        )

        # ST/退市过滤
        if name_col:
            st_mask = df[name_col].fillna("").str.upper().str.contains(r"ST|退", regex=True)
            cond = cond & (~st_mask)

        return df.loc[cond].copy()

    def _layer_trend_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Layer 2 趋势过滤
        - MA20 > MA60 > MA120（多头排列）
        - MA20 斜率 > 0（短期均线向上）
        """
        p = self.params
        cond = (
            df["ma20"].notna()
            & df["ma60"].notna()
            & df["ma120"].notna()
            & (df["ma20"] > df["ma60"])
            & (df["ma60"] > df["ma120"])
            & (df["ma20_slope"].fillna(-1) > p.ma_slope_min)
        )
        return df.loc[cond].copy()

    def _layer_strength_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Layer 3 强度过滤
        - 全主板横截面 RS20 分位 ≥ 80%
        - 即：近20日涨幅在所有主板股票中排前20%
        """
        p = self.params
        cond = (
            df["rs20_xsec_q"].notna()
            & (df["rs20_xsec_q"] >= p.rs_quantile_min)
        )
        if getattr(p, "rs_quantile_max", 1.0) < 1.0:
            cond = cond & (df["rs20_xsec_q"] <= float(p.rs_quantile_max))
        return df.loc[cond].copy()

    def _layer_stability_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Layer 4 走稳过滤
        - ATR/close 60日分位 ≤ 50%（波动率处于自身历史中位数以下）
        - 10日箱体宽度 ≤ 8%（近期横盘整理，价格在收窄）
        """
        p = self.params
        cond = (
            df["atr_ratio_q60"].notna()
            & (df["atr_ratio_q60"] <= p.atr_quantile_max)
            & df["box_range"].notna()
            & (df["box_range"] <= p.box_max_range)
        )
        return df.loc[cond].copy()

    # ───────────────────────────────────────────
    # 综合评分
    # ───────────────────────────────────────────

    def _compute_scores(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        五维度加权评分（满分 100）

        维度一：RS横截面分位（weight_rs=35）
            - 分位越高，得分越高
        维度二：趋势质量（weight_trend=25）
            - MA多头排列紧密程度 + MA20斜率强度
        维度三：走稳质量（weight_stability=20）
            - ATR分位越低得分越高（表示波动已收敛）
        维度四：箱体紧密度（weight_box=12）
            - 箱体越窄突破质量越高
        维度五：量能趋势（weight_volume=8）
            - 5日均量/20日均量，温和放量为佳
        """
        p = self.params
        scored = df.copy()

        # 维度一：RS分位（已经是0~1的分位值，直接映射到满分）
        rs_score = scored["rs20_xsec_q"].fillna(0.0).clip(0.0, 1.0) * p.weight_rs

        # 维度二：趋势质量（两个子维度各50%）
        # 子2a：MA多头排列紧密度 = (MA20 - MA60) / MA60，越紧凑越好，上限0.08
        ma_gap = ((scored["ma20"] - scored["ma60"]) / scored["ma60"].replace(0, np.nan)).fillna(0.0)
        ma_gap_score = (ma_gap.clip(0.0, 0.08) / 0.08)
        # 子2b：MA20斜率强度，上限2%（0.02）
        slope_score = (scored["ma20_slope"].fillna(0.0).clip(0.0, 0.02) / 0.02)
        trend_score = (ma_gap_score * 0.5 + slope_score * 0.5) * p.weight_trend

        # 维度三：走稳质量（ATR分位越低=越稳，反转映射）
        stab_score = (1.0 - scored["atr_ratio_q60"].fillna(0.5).clip(0.0, 1.0)) * p.weight_stability

        # 维度四：箱体紧密度（箱体越窄=得分越高）
        box_score = (
            (1.0 - (scored["box_range"].fillna(p.box_max_range) / p.box_max_range).clip(0.0, 1.0))
            * p.weight_box
        )

        # 维度五：量能趋势（5日均量/20日均量，目标区间 0.8~1.5）
        vol_ratio = (
            scored["vol_ma5"] / scored["vol_ma20"].replace(0, np.nan)
        ).fillna(0.0).clip(0.0, 2.0)
        # 0.8~1.5 内满分，过低或过高均减分
        vol_score_raw = np.where(
            vol_ratio < 0.8,
            vol_ratio / 0.8,                          # 低于0.8线性增长
            np.where(
                vol_ratio <= 1.5,
                1.0,                                  # 0.8~1.5 满分
                1.0 - (vol_ratio - 1.5) / 1.5         # 1.5以上线性衰减
            )
        )
        vol_score = pd.Series(vol_score_raw, index=scored.index).clip(0.0, 1.0) * p.weight_volume

        scored["signal_score"] = (rs_score + trend_score + stab_score + box_score + vol_score).round(2)

        # 评分明细（用于诊断）
        scored["score_detail"] = (
            "RS=" + rs_score.round(1).astype(str)
            + " 趋势=" + trend_score.round(1).astype(str)
            + " 低波=" + stab_score.round(1).astype(str)
            + " 箱体=" + box_score.round(1).astype(str)
            + " 量能=" + vol_score.round(1).astype(str)
        )

        return scored

    # ───────────────────────────────────────────
    # 市场环境闸门
    # ───────────────────────────────────────────

    def _market_gate(
        self, features: pd.DataFrame, end_date: str
    ) -> Tuple[float, int]:
        """
        三档市场环境闸门：
          正常 → 使用默认门槛
          谨慎 → 评分门槛+8，观察池缩至40%
          禁止 → 不开仓（返回极高门槛）

        综合判断维度：
          1. 指数是否在MA20上方
          2. 指数3日/5日收益率
          3. 全主板涨跌家数比（市场广度）

        Returns:
            (effective_min_score, effective_top_k)
        """
        p = self.params
        target = pd.Timestamp(end_date)

        # 取指数数据
        idx = features[
            (features["ts_code"] == p.index_code)
            & (features["trade_date"] <= target)
        ].copy()

        # 计算市场广度（上涨股票占比），按日历日对齐避免因时区/类型导致匹配失败
        ts = features["trade_date"]
        if hasattr(ts.dt, "normalize"):
            td_mask = ts.dt.normalize() == target.normalize()
        else:
            td_mask = ts == target
        all_stocks = features.loc[td_mask]
        breadth = 0.50  # 默认中性
        market_ret5_median = float("nan")
        if not all_stocks.empty and "ret_1d" in all_stocks.columns:
            valid_rets = all_stocks["ret_1d"].dropna()
            if len(valid_rets) > 50:
                breadth = float((valid_rets > 0).mean())
        if not all_stocks.empty and "ret5" in all_stocks.columns:
            valid_ret5 = all_stocks["ret5"].dropna()
            if len(valid_ret5) > 50:
                market_ret5_median = float(valid_ret5.median())

        if (
            getattr(p, "enable_market_ret5_median_guard", False)
            and pd.notna(market_ret5_median)
            and market_ret5_median <= getattr(p, "market_ret5_median_stop", -0.01)
        ):
            logger.info(
                "市场环境: 禁止开仓（全市场5日中位收益=%.2f%% <= %.2f%%）",
                market_ret5_median * 100,
                getattr(p, "market_ret5_median_stop", -0.01) * 100,
            )
            return 999.0, 0

        if idx.empty:
            logger.debug("未找到指数数据，使用默认闸门（breadth=%.1f%%）", breadth * 100)
            return p.min_signal_score, p.top_k

        idx = idx.sort_values("trade_date")
        latest = idx.iloc[-1]
        ret3 = float(latest.get("ret3", 0.0)) if pd.notna(latest.get("ret3")) else 0.0
        ret5 = float(latest.get("ret5", 0.0)) if pd.notna(latest.get("ret5")) else 0.0
        close = float(latest.get("close", 0.0))
        ma20 = float(latest.get("ma20", 0.0)) if pd.notna(latest.get("ma20")) else 0.0
        index_below_ma20 = (ma20 > 0 and close < ma20)

        # ── 判定三档 ──
        stop_signals = 0
        caution_signals = 0

        # 维度1：指数在MA20下方
        if p.market_index_above_ma20 and index_below_ma20:
            caution_signals += 1

        # 维度2：指数3日收益率
        if ret3 <= p.market_ret3_stop:
            stop_signals += 1
        elif ret3 <= p.market_ret3_caution:
            caution_signals += 1

        # 维度3：指数5日收益率
        if ret5 <= p.market_ret5_stop:
            stop_signals += 1
        elif ret5 <= p.market_ret5_caution:
            caution_signals += 1

        # 维度4：市场广度
        if breadth <= p.market_breadth_stop:
            stop_signals += 1
        elif breadth <= p.market_breadth_caution:
            caution_signals += 1

        # 综合裁决
        if stop_signals >= 2:
            # 两个以上维度触发"禁止"→ 不开仓
            logger.info(
                "市场环境: 禁止开仓（ret3=%.2f%% ret5=%.2f%% breadth=%.1f%% idx<%sMa20）",
                ret3 * 100, ret5 * 100, breadth * 100,
                "" if not index_below_ma20 else "低于",
            )
            return 999.0, 0  # 极高门槛，等于空仓

        if stop_signals >= 1 or caution_signals >= 2:
            # 谨慎档
            effective_score = p.min_signal_score + p.caution_score_boost
            effective_k = max(3, int(p.top_k * p.caution_topk_ratio))
            logger.info(
                "市场环境: 谨慎（ret3=%.2f%% ret5=%.2f%% breadth=%.1f%%），门槛%.1f，TopK%d",
                ret3 * 100, ret5 * 100, breadth * 100, effective_score, effective_k,
            )
            return effective_score, effective_k

        # 正常
        return p.min_signal_score, p.top_k

    # ───────────────────────────────────────────
    # 输出转换
    # ───────────────────────────────────────────

    def _to_watch_items(
        self, snapshot: pd.DataFrame, watch_date: str
    ) -> List[WatchItem]:
        """将 DataFrame 行转换为 WatchItem 列表"""
        p = self.params
        items: List[WatchItem] = []

        for _, row in snapshot.iterrows():
            close = float(row.get("close", 0.0))
            pivot = float(row.get("pivot", close))
            atr14 = float(row.get("atr14", 0.0)) if pd.notna(row.get("atr14")) else 0.0
            ll_n = float(row.get("ll_n", 0.0)) if pd.notna(row.get("ll_n")) else 0.0

            # 触发价 = pivot × (1 + 缓冲)，与 confirm_breakout_* 一致
            trigger = round(pivot * (1 + p.breakout_buffer), 2)

            # 止损 = max(近N日最低价, pivot - 1.2 × ATR14)
            stop_atr = pivot - 1.2 * atr14 if atr14 > 0 else pivot * 0.95
            stop_loss = round(max(ll_n, stop_atr), 2) if ll_n > 0 else round(stop_atr, 2)

            items.append(WatchItem(
                ts_code=str(row.get("ts_code", "")),
                name=str(row.get("name", "")),
                watch_date=watch_date,
                close=close,
                pivot=round(pivot, 2),
                trigger_price=trigger,
                stop_loss=stop_loss,
                atr14=round(atr14, 4),
                rs20=round(float(row.get("rs20", 0.0)) * 100, 2),  # 转为百分比
                rs20_xsec_q=round(float(row.get("rs20_xsec_q", 0.0)), 4),
                atr_ratio_q60=round(float(row.get("atr_ratio_q60", 0.0)), 4),
                box_range=round(float(row.get("box_range", 0.0)) * 100, 2),  # 转为百分比
                ma20=round(float(row.get("ma20", 0.0)), 2),
                ma60=round(float(row.get("ma60", 0.0)), 2),
                ma120=round(float(row.get("ma120", 0.0)), 2),
                signal_score=round(float(row.get("signal_score", 0.0)), 2),
                score_detail=str(row.get("score_detail", "")),
                industry=str(row.get("industry", "")),
            ))

        return items

    # ───────────────────────────────────────────
    # 持仓走弱检查（供持仓管理调用）
    # ───────────────────────────────────────────

    def check_hold_weakness(
        self,
        ts_code: str,
        daily_df: pd.DataFrame,
        stop_loss: float,
        hold_days: int,
        entry_price: Optional[float] = None,
        peak_price: Optional[float] = None,
        signal_grade: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        检查持仓是否走弱（供持仓管理模块调用）

        判断逻辑（满足任一则退出）：
          1. 移动止盈：盈利达到启动线后，从峰值回撤超过阈值
          2. 时间止损：持仓达最大天数
          3. ATR止损：当日最低价触及止损线
          4. 跌破MA5：收盘价低于5日均线
          5. 跌破前日低点：收盘价低于前一日最低价

        Args:
            ts_code: 股票代码（仅用于日志）
            daily_df: 最近N日行情，至少包含 close/low/ma5 列，按时间升序
            stop_loss: 入场时确定的初始止损价
            hold_days: 已持仓天数
            entry_price: 入场价；提供后可启用移动止盈
            peak_price: 外部记录的持仓峰值价；不传则用 daily_df 内 high 兜底
            signal_grade: 突破确认等级；提供后可使用 A/B 分层退出参数

        Returns:
            (should_exit, exit_reason)
        """
        p = self.params
        grade_cfg = {}
        if signal_grade:
            grade_cfg = dict(getattr(p, "exit_grade_overrides", {}).get(str(signal_grade).upper(), {}) or {})
        max_hold_days = int(grade_cfg.get("max_hold_days", p.max_hold_days))
        trail_arm_pct = float(grade_cfg.get("trail_arm_pct", p.exit_trail_arm_pct))
        trailing_stop_pct = float(grade_cfg.get("trailing_stop_pct", p.exit_trailing_stop_pct))
        fixed_stop_loss_pct = grade_cfg.get("fixed_stop_loss_pct", p.exit_fixed_stop_loss_pct)
        use_weakness_rules = grade_cfg.get("use_weakness_rules", p.exit_use_weakness_rules)
        if not isinstance(use_weakness_rules, bool):
            use_weakness_rules = str(use_weakness_rules).strip().lower() in {"1", "true", "yes", "on"}

        if daily_df.empty or len(daily_df) < 2:
            if hold_days >= max_hold_days:
                return True, f"时间止损（持仓{hold_days}天达上限{max_hold_days}天）"
            return False, ""

        latest = daily_df.iloc[-1]
        prev = daily_df.iloc[-2]

        close = float(latest.get("close", 0.0))
        low = float(latest.get("low", close))
        ma5 = float(latest.get("ma5", 0.0)) if pd.notna(latest.get("ma5")) else 0.0
        prev_low = float(prev.get("low", 0.0))

        ep = float(entry_price or 0.0)
        effective_stop_loss = float(stop_loss)
        if ep > 0 and fixed_stop_loss_pct is not None:
            effective_stop_loss = ep * (1.0 + float(fixed_stop_loss_pct))

        if low <= effective_stop_loss:
            if ep > 0 and fixed_stop_loss_pct is not None:
                return True, f"固定止损触发（最低价{low:.2f}≤止损线{effective_stop_loss:.2f}）"
            return True, f"ATR止损触发（最低价{low:.2f}≤止损线{effective_stop_loss:.2f}）"

        if getattr(p, "enable_trailing_exit_guard", False):
            if ep > 0 and close > 0:
                high_series = pd.to_numeric(daily_df.get("high", pd.Series(dtype=float)), errors="coerce")
                observed_peak = float(high_series.max()) if not high_series.dropna().empty else close
                if peak_price is not None and float(peak_price) > 0:
                    observed_peak = max(observed_peak, float(peak_price))
                peak_ret = observed_peak / ep - 1.0
                close_ret = close / ep - 1.0
                trail_floor_ret = peak_ret - trailing_stop_pct
                if peak_ret >= trail_arm_pct and close_ret <= trail_floor_ret:
                    return (
                        True,
                        f"移动止盈触发（峰值收益{peak_ret*100:.2f}%回落至{close_ret*100:.2f}%）",
                    )

        if hold_days >= max_hold_days:
            return True, f"时间止损（持仓{hold_days}天达上限{max_hold_days}天）"

        if not use_weakness_rules:
            return False, ""

        if ma5 > 0 and close < ma5:
            return True, f"跌破MA5（收盘{close:.2f}<MA5={ma5:.2f}）"

        if prev_low > 0 and close < prev_low:
            return True, f"跌破前日低点（收盘{close:.2f}<前低{prev_low:.2f}）"

        return False, ""

    # ───────────────────────────────────────────
    # 仓位计算（以风险定仓）
    # ───────────────────────────────────────────

    # ───────────────────────────────────────────
    # 突破确认（核心alpha来源）
    # ───────────────────────────────────────────

    def bars_dict_for_trade_date(
        self,
        features: pd.DataFrame,
        trade_date_str: str,
    ) -> Dict[str, pd.Series]:
        """
        从全量因子表中截取某一交易日的截面，供 confirm_breakout_daily 使用。

        Returns:
            ts_code -> 该行行情与因子（需含 high/open/vol/vol_ma20/trade_date）
        """
        if features is None or features.empty or "trade_date" not in features.columns:
            return {}
        td_col = features["trade_date"]
        if not pd.api.types.is_datetime64_any_dtype(td_col):
            return {}
        key = str(trade_date_str).strip()
        mask = td_col.dt.strftime("%Y%m%d") == key
        sub = features.loc[mask]
        return {str(r["ts_code"]): r for _, r in sub.iterrows()}

    def confirm_breakout_daily(
        self,
        watch_items: List[WatchItem],
        confirm_date_row: Dict[str, pd.Series],
    ) -> List[BreakoutSignal]:
        """
        日线级别突破确认：检查观察池股票在 T+1 是否发生有效突破

        确认逻辑：
          1. 当日最高价 ≥ pivot × (1 + buffer) → 价格突破
          2. 入场价 = pivot × (1 + buffer)，不高于 pivot × (1 + max_chase)
          3. 当日涨幅 ≤ max_intraday_gain → 不追涨停板
          4. 当日成交量 ≥ vol_ma20 × volume_confirm_ratio → 放量确认（可选加分）

        Args:
            watch_items: 盘前选出的观察池
            confirm_date_row: {ts_code: 该股票确认日（通常为T+1）的截面行 Series}，需含
                              open/high/low/close/vol/vol_ma20/trade_date

        Returns:
            确认通过的交易信号列表
        """
        p = self.params
        signals: List[BreakoutSignal] = []

        for item in watch_items:
            row = confirm_date_row.get(item.ts_code)
            if row is None:
                continue

            high = float(row.get("high", 0))
            open_price = float(row.get("open", 0))
            vol = float(row.get("vol", 0))
            vol_ma20 = float(row.get("vol_ma20", 0)) if pd.notna(row.get("vol_ma20")) else 0

            if open_price <= 0 or high <= 0:
                continue

            pivot = item.pivot
            trigger = pivot * (1 + p.breakout_buffer)

            # 条件1：最高价突破触发价
            if high < trigger:
                continue

            # 条件2：入场价不追高
            entry_price = trigger
            max_entry = pivot * (1 + p.breakout_max_chase)
            if entry_price > max_entry:
                continue
            if entry_price > high:
                continue

            # 条件3：当日涨幅限制
            if open_price > 0 and (high / open_price - 1) > p.max_intraday_gain:
                continue

            # 条件4：量能分级过滤
            vol_ratio = vol / vol_ma20 if vol_ma20 > 0 else 0.0

            # 缩量突破不可靠，直接过滤
            if vol_ratio < p.volume_normal_ratio:
                continue

            # A级：放量突破（量比≥1.1x） / B级：正常量能突破
            if vol_ratio >= p.volume_confirm_ratio:
                grade = "A"
                pos_ratio = 1.0
                confirm_type = "breakout+volume"
            else:
                grade = "B"
                pos_ratio = 0.5
                confirm_type = "breakout"

            if (
                p.enable_high_score_weak_confirm_guard
                and item.signal_score >= p.high_score_weak_confirm_score_min
                and vol_ratio < p.high_score_weak_confirm_volume_min
            ):
                continue

            confirm_date_str = str(row.get("trade_date", ""))
            if hasattr(row.get("trade_date"), "strftime"):
                confirm_date_str = row["trade_date"].strftime("%Y%m%d")

            signals.append(BreakoutSignal(
                ts_code=item.ts_code,
                name=item.name,
                signal_date=item.watch_date,
                confirm_date=confirm_date_str,
                entry_price=round(entry_price, 2),
                pivot=item.pivot,
                stop_loss=item.stop_loss,
                atr14=item.atr14,
                signal_score=item.signal_score,
                volume_ratio=round(vol_ratio, 2),
                confirm_type=confirm_type,
                signal_grade=grade,
                position_ratio=pos_ratio,
                industry=item.industry,
            ))

        return signals

    def confirm_breakout_realtime(
        self,
        watch_items: List[WatchItem],
        realtime_quotes: Dict[str, Dict],
    ) -> List[BreakoutSignal]:
        """
        盘中实时突破确认（供盘中监控模块调用）

        与日线确认逻辑一致，但数据来源是实时行情：
          realtime_quotes[ts_code] = {
              "price": 当前价, "high": 当日最高, "open": 开盘价,
              "vol": 当日累计成交量, "vol_ma20": 20日均量,
              "time": 当前时间字符串 "HH:MM:SS"
          }

        额外约束：
          - 09:30~09:35 不确认（开盘波动期）
          - 14:50以后不确认（尾盘不追）
        """
        p = self.params
        signals: List[BreakoutSignal] = []

        for item in watch_items:
            quote = realtime_quotes.get(item.ts_code)
            if quote is None:
                continue

            time_str = str(quote.get("time", ""))
            if time_str:
                try:
                    hm = time_str.replace(":", "")[:4]
                    hm_int = int(hm)
                    if hm_int < 935 or hm_int > 1450:
                        continue
                except (ValueError, IndexError):
                    pass

            price = float(quote.get("price", 0))
            high = float(quote.get("high", 0))
            open_price = float(quote.get("open", 0))
            vol = float(quote.get("vol", 0))
            vol_ma20 = float(quote.get("vol_ma20", 0))

            if price <= 0 or open_price <= 0:
                continue

            pivot = item.pivot
            trigger = pivot * (1 + p.breakout_buffer)

            if high < trigger:
                continue

            entry_price = trigger
            max_entry = pivot * (1 + p.breakout_max_chase)
            if entry_price > max_entry or entry_price > high:
                continue

            if (high / open_price - 1) > p.max_intraday_gain:
                continue

            vol_ratio = vol / vol_ma20 if vol_ma20 > 0 else 0.0

            if vol_ratio < p.volume_normal_ratio:
                continue

            if vol_ratio >= p.volume_confirm_ratio:
                grade = "A"
                pos_ratio = 1.0
                confirm_type = "breakout+volume"
            else:
                grade = "B"
                pos_ratio = 0.5
                confirm_type = "breakout"

            if (
                p.enable_high_score_weak_confirm_guard
                and item.signal_score >= p.high_score_weak_confirm_score_min
                and vol_ratio < p.high_score_weak_confirm_volume_min
            ):
                continue

            signals.append(BreakoutSignal(
                ts_code=item.ts_code,
                name=item.name,
                signal_date=item.watch_date,
                confirm_date=datetime.now().strftime("%Y%m%d"),
                entry_price=round(entry_price, 2),
                pivot=item.pivot,
                stop_loss=item.stop_loss,
                atr14=item.atr14,
                signal_score=item.signal_score,
                volume_ratio=round(vol_ratio, 2),
                confirm_type=confirm_type,
                signal_grade=grade,
                position_ratio=pos_ratio,
                industry=item.industry,
            ))

        return signals

    # ───────────────────────────────────────────
    # 仓位计算（以风险定仓）
    # ───────────────────────────────────────────

    @staticmethod
    def calc_position_size(
        equity: float,
        entry_price: float,
        stop_loss: float,
        risk_pct: float = 0.005,
        lot_size: int = 100,
    ) -> int:
        """
        以风险定仓：单笔最大亏损 = equity × risk_pct

        position_size = equity × risk_pct / (entry_price - stop_loss)

        Returns:
            整手股数（100股整数倍）
        """
        risk_per_share = entry_price - stop_loss
        if risk_per_share <= 0 or entry_price <= 0:
            return 0
        max_risk = equity * risk_pct
        raw_shares = max_risk / risk_per_share
        lots = int(raw_shares // lot_size)
        return max(0, lots * lot_size)
