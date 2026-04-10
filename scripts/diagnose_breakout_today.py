# -*- coding: utf-8 -*-
"""诊断今日（数据库最新交易日）突破选股为何为空：闸门 / 各层过滤 / 最终评分"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.breakout_strategy import BreakoutStrategy, BreakoutParams


def main():
    config = ConfigManager()
    db = DatabaseManager(config)
    latest = db.get_latest_trade_date("stock_daily")
    if not latest:
        print("数据库 stock_daily 无数据，请先更新日线。")
        return

    print(f"数据库最新交易日: {latest}")
    params = BreakoutParams()
    params.min_amt_ma20 = 8e4
    params.rs_quantile_max = 0.97
    params.min_signal_score = 60.0
    params.top_k = 15
    strategy = BreakoutStrategy(db=db, params=params)

    raw_daily, raw_basic = strategy._load_data(str(latest))
    if raw_daily.empty:
        print("加载日线失败，检查库路径与权限。")
        return
    features = strategy._compute_features(raw_daily, raw_basic, str(latest))
    snapshot = strategy._build_snapshot(features, str(latest))
    print(f"截面快照股票数: {len(snapshot)}")
    if snapshot.empty:
        print("快照为空，可能 latest 在特征表里无对齐。")
        return

    l1 = strategy._layer_base_filter(snapshot)
    print(f"Layer1 基础过滤: {len(snapshot)} -> {len(l1)}")

    all_dates_rows = db.query(
        "SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date ASC"
    )
    all_dates = [r["trade_date"] for r in all_dates_rows]
    use_ma120 = len(all_dates) >= 180
    if use_ma120:
        l2 = strategy._layer_trend_filter(l1)
        trend_label = "MA20>MA60>MA120"
    else:
        cond = (
            l1["ma20"].notna()
            & l1["ma60"].notna()
            & (l1["ma20"] > l1["ma60"])
            & (l1["ma20_slope"].fillna(-1) > 0)
        )
        l2 = l1.loc[cond].copy()
        trend_label = "MA20>MA60(降级)"
    print(f"Layer2 趋势过滤 ({trend_label}): {len(l1)} -> {len(l2)}")

    l3 = strategy._layer_strength_filter(l2) if not l2.empty else l2
    print(f"Layer3 RS强度: {len(l2)} -> {len(l3)}")

    if use_ma120:
        l4 = strategy._layer_stability_filter(l3) if not l3.empty else l3
    else:
        p = params
        if l3.empty:
            l4 = l3
        else:
            cond = l3["box_range"].notna() & (l3["box_range"] <= p.box_max_range)
            if l3["atr_ratio_q60"].notna().mean() > 0.3:
                cond = cond & (l3["atr_ratio_q60"].fillna(0.5) <= p.atr_quantile_max)
            l4 = l3.loc[cond].copy()
    print(f"Layer4 走稳: {len(l3)} -> {len(l4)}")

    min_sc, eff_k = strategy._market_gate(features, str(latest))
    print(
        f"\n市场闸门: effective_min_score={min_sc}, effective_top_k={eff_k} "
        f"(默认门槛={params.min_signal_score}, 默认top_k={params.top_k})"
    )
    if min_sc >= 999 or eff_k <= 0:
        print(">>> 判定: 禁止开仓档 — 当日不会输出任何观察池股票。")
        return

    if l4.empty:
        print("\n>>> 判定: 走稳/强度/趋势等过滤后已无标的，非闸门卡死。")
        return

    scored = strategy._compute_scores(l4)
    passed = scored[scored["signal_score"] >= min_sc]
    print(f"评分后 >= 闸门门槛: {len(passed)} 只")
    if passed.empty:
        print(
            f">>> 判定: 有候选但综合分都低于门槛 {min_sc}，可提高数据质量或略降 min_signal_score 试跑。"
        )
        top5 = scored.nlargest(5, "signal_score")[
            ["ts_code", "signal_score"]
        ] if len(scored) else None
        if top5 is not None and not top5.empty:
            print("当前最高分 5 只（未过线）:")
            print(top5.to_string(index=False))
        return

    head = passed.sort_values("signal_score", ascending=False).head(eff_k)
    print(f">>> 当日应产出观察池: {len(head)} 只（取 Top eff_k）")
    print(head[["ts_code", "signal_score"]].head(10).to_string(index=False))


if __name__ == "__main__":
    main()
