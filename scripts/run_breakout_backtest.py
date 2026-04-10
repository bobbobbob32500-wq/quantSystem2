# -*- coding: utf-8 -*-
"""
突破选股策略历史回测脚本
计算 T+1 / T+2 / T+3 的收益和胜率

入场规则（与策略设计一致）：
  信号日 T 收盘后产生观察池；仅在下一交易日 T+1 出现「突破 pivot×(1+缓冲) + 量能≥阈值」时，
  以触发价入场（日线近似）；缩量突破一律不计入成交。
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.breakout_strategy import BreakoutStrategy, BreakoutParams


def main():
    print("=" * 70, flush=True)
    print("  选强->等突破 策略历史回测（突破+量能确认入场）", flush=True)
    print("=" * 70, flush=True)

    config = ConfigManager()
    db = DatabaseManager(config)

    # 1. 确认数据范围
    info = db.query(
        "SELECT MIN(trade_date) as min_d, MAX(trade_date) as max_d, "
        "COUNT(DISTINCT trade_date) as days FROM stock_daily"
    )
    min_d, max_d, total_days = info[0]["min_d"], info[0]["max_d"], info[0]["days"]
    print(f"\n  数据范围: {min_d} -> {max_d}, 共 {total_days} 个交易日", flush=True)

    all_dates_rows = db.query(
        "SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date ASC"
    )
    all_dates = [r["trade_date"] for r in all_dates_rows]

    # 数据有限时自适应warmup：MA120需约180自然日（120交易日），但数据不够时降级
    if len(all_dates) >= 180:
        warmup_skip = 125
        use_ma120 = True
    elif len(all_dates) >= 75:
        warmup_skip = 65  # 用MA60做多头判断，跳过65天
        use_ma120 = False
        print(f"  注意: 数据仅{len(all_dates)}个交易日, MA120不可用, 降级为MA20>MA60趋势过滤", flush=True)
    else:
        print(f"  数据不足（共{len(all_dates)}天，至少需75天），无法回测")
        return

    if len(all_dates) <= warmup_skip + 10:
        print(f"  数据不足（共{len(all_dates)}天，warmup需{warmup_skip}天+10天），无法回测")
        return

    backtest_dates = all_dates[warmup_skip:]
    # 保留最后3天作为持有期退出空间
    signal_dates = backtest_dates[:-3]

    print(f"  回测窗口: {signal_dates[0]} -> {signal_dates[-1]}, 共 {len(signal_dates)} 个信号日", flush=True)
    print(f"  Warmup跳过前 {warmup_skip} 天", flush=True)

    # 2. 初始化策略（与网格搜索结论对齐 + 成交额单位千元）
    params = BreakoutParams()
    params.min_amt_ma20 = 8e4  # 约8000万元（Tushare amount=千元）
    params.rs_quantile_max = 0.97  # 过滤极端强势妖股
    params.min_signal_score = 60.0  # 回测显示<60分段均收为负
    params.top_k = 15
    # 与 BreakoutParams 默认一致：A 级放量 ≥1.2×20 日均量；B 级 ≥1.0×
    params.volume_confirm_ratio = 1.2
    params.volume_normal_ratio = 1.0
    if not use_ma120:
        params.atr_quantile_max = 0.50
        params.box_max_range = 0.08
    strategy = BreakoutStrategy(db=db, params=params)

    # 3. 预计算特征（只计算一次，覆盖全部日期）
    print("\n  [步骤1/2] 正在计算全量因子...", flush=True)
    raw_daily, raw_basic = strategy._load_data(max_d)
    if raw_daily.empty:
        print("  日线数据为空，退出")
        return
    features = strategy._compute_features(raw_daily, raw_basic, max_d)
    print(f"  因子计算完成, 共 {len(features)} 行", flush=True)

    # 4. 构建价格查找表（用于计算持有收益）
    price_df = features[["ts_code", "trade_date", "open", "close"]].copy()
    price_df = price_df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    # 按股票构建日期索引
    price_map = {}
    for code, sub in price_df.groupby("ts_code"):
        sub = sub.sort_values("trade_date").reset_index(drop=True)
        sub["date_str"] = sub["trade_date"].dt.strftime("%Y%m%d")
        price_map[code] = sub

    # 5. 逐日执行选股并计算持有收益
    print(f"\n  [步骤2/2] 开始逐日回测 (共{len(signal_dates)}天)...", flush=True)
    all_trades = []
    dates_with_signals = 0
    total_signal_count = 0
    gate_stats = {"normal": 0, "caution": 0, "stop": 0}
    grade_counts = {"A": 0, "B": 0}

    # 信号日 -> 下一交易日（用于 T+1 突破确认）
    date_pos = {d: i for i, d in enumerate(all_dates)}

    for i, td in enumerate(signal_dates):
        if (i + 1) % 10 == 0:
            pct = (i + 1) / len(signal_dates) * 100
            print(f"  进度: {i+1}/{len(signal_dates)} ({pct:.0f}%) 信号{total_signal_count}条", flush=True)

        # 构建截面快照
        snapshot = strategy._build_snapshot(features, td)
        if snapshot.empty:
            continue

        # Layer 1~4 过滤
        filtered = strategy._layer_base_filter(snapshot)
        if filtered.empty:
            continue

        # 趋势过滤（数据不足时降级）
        if use_ma120:
            filtered = strategy._layer_trend_filter(filtered)
        else:
            # 降级：只要求 MA20 > MA60 且 MA20 上升
            cond = (
                filtered["ma20"].notna()
                & filtered["ma60"].notna()
                & (filtered["ma20"] > filtered["ma60"])
                & (filtered["ma20_slope"].fillna(-1) > 0)
            )
            filtered = filtered.loc[cond].copy()
        if filtered.empty:
            continue

        # 强度过滤
        filtered = strategy._layer_strength_filter(filtered)
        if filtered.empty:
            continue

        # 走稳过滤（数据不足时放宽ATR分位窗口）
        if use_ma120:
            filtered = strategy._layer_stability_filter(filtered)
        else:
            p = strategy.params
            cond = (
                filtered["box_range"].notna()
                & (filtered["box_range"] <= p.box_max_range)
            )
            # ATR分位如果大部分为NaN则跳过该条件
            if filtered["atr_ratio_q60"].notna().mean() > 0.3:
                cond = cond & (
                    filtered["atr_ratio_q60"].fillna(0.5) <= p.atr_quantile_max
                )
            filtered = filtered.loc[cond].copy()
        if filtered.empty:
            continue

        # 评分+市场闸门
        scored = strategy._compute_scores(filtered)
        min_score, top_k = strategy._market_gate(features, td)

        # 统计闸门档位
        if min_score >= 999 or top_k <= 0:
            gate_stats["stop"] += 1
            continue
        elif min_score > strategy.params.min_signal_score:
            gate_stats["caution"] += 1
        else:
            gate_stats["normal"] += 1

        scored = scored[scored["signal_score"] >= min_score].copy()
        if scored.empty:
            continue
        scored = scored.sort_values("signal_score", ascending=False).head(top_k)

        pos = date_pos.get(td)
        if pos is None or pos + 1 >= len(all_dates):
            continue
        next_d = all_dates[pos + 1]
        confirm_map = strategy.bars_dict_for_trade_date(features, next_d)
        watch_items = strategy._to_watch_items(scored, td)
        confirmed = strategy.confirm_breakout_daily(watch_items, confirm_map)
        if not confirmed:
            continue

        dates_with_signals += 1

        for sig in confirmed:
            code = sig.ts_code
            sub = price_map.get(code)
            if sub is None:
                continue

            match_idx = sub.index[sub["date_str"] == sig.confirm_date]
            if len(match_idx) == 0:
                continue
            confirm_idx = int(match_idx[0])

            entry_price = float(sig.entry_price)
            if entry_price <= 0:
                continue

            grade_counts[sig.signal_grade] = grade_counts.get(sig.signal_grade, 0) + 1

            match_scored = scored.loc[scored["ts_code"] == code]
            if match_scored.empty:
                rs_q = atr_q = box_r = 0.0
            else:
                r0 = match_scored.iloc[0]
                rs_q = float(r0.get("rs20_xsec_q", 0) or 0)
                atr_q = float(r0.get("atr_ratio_q60", 0) or 0)
                box_r = float(r0.get("box_range", 0) or 0)

            trade_record = {
                "signal_date": td,
                "confirm_date": sig.confirm_date,
                "ts_code": code,
                "name": sig.name,
                "signal_score": float(sig.signal_score),
                "rs20_xsec_q": rs_q,
                "atr_ratio_q60": atr_q,
                "box_range": box_r,
                "pivot": float(sig.pivot),
                "entry_price": entry_price,
                "stop_loss": float(sig.stop_loss),
                "signal_grade": sig.signal_grade,
                "volume_ratio": float(sig.volume_ratio),
            }

            # 确认日收盘索引 = confirm_idx；持有 N 个交易日后的收盘 = confirm_idx + N
            for hold_n in [1, 2, 3]:
                target_idx = confirm_idx + hold_n
                if target_idx < len(sub):
                    exit_close = float(sub.loc[target_idx, "close"])
                    ret = exit_close / entry_price - 1.0
                    trade_record[f"ret_t{hold_n}"] = ret
                else:
                    trade_record[f"ret_t{hold_n}"] = np.nan

            all_trades.append(trade_record)
            total_signal_count += 1

    print(f"\n  回测完成！", flush=True)
    print(f"  信号日数: {dates_with_signals}", flush=True)
    print(f"  总成交笔数: {total_signal_count}", flush=True)
    print(
        f"  市场闸门统计: 正常={gate_stats['normal']}天  谨慎={gate_stats['caution']}天  "
        f"禁止开仓={gate_stats['stop']}天",
        flush=True,
    )
    print(
        f"  确认成交分级: A级(放量≥{params.volume_confirm_ratio:.1f}x)={grade_counts.get('A', 0)}笔  "
        f"B级={grade_counts.get('B', 0)}笔",
        flush=True,
    )

    if not all_trades:
        print("  无有效交易记录，退出")
        return

    df = pd.DataFrame(all_trades)
    df = df.sort_values(["signal_date", "confirm_date", "ts_code"]).reset_index(drop=True)

    # 导出成交明细（UTF-8 BOM 便于 Excel 打开）
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    rep_dir = os.path.join(root, "data", "reports")
    os.makedirs(rep_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path_latest = os.path.join(rep_dir, "breakout_backtest_trades_latest.csv")
    path_stamp = os.path.join(rep_dir, f"breakout_backtest_trades_{stamp}.csv")
    df.to_csv(path_latest, index=False, encoding="utf-8-sig")
    df.to_csv(path_stamp, index=False, encoding="utf-8-sig")
    print(f"\n  回测成交明细已导出:", flush=True)
    print(f"    {path_latest}", flush=True)
    print(f"    {path_stamp}", flush=True)

    # 6. 汇总统计
    print("\n" + "=" * 70, flush=True)
    print("  整体回测结果", flush=True)
    print("=" * 70, flush=True)
    print(f"  回测窗口       : {signal_dates[0]} -> {signal_dates[-1]}", flush=True)
    print(f"  有信号交易日数 : {dates_with_signals}", flush=True)
    print(f"  总成交笔数     : {len(df)}（仅统计突破+量能确认）", flush=True)
    sig_avg = len(df) / max(dates_with_signals, 1)
    print(f"  日均成交笔数   : {sig_avg:.1f}", flush=True)
    print(f"  市场闸门       : 正常{gate_stats['normal']}天 谨慎{gate_stats['caution']}天 禁止{gate_stats['stop']}天", flush=True)

    print(f"\n  {'持有期':>8}  {'总笔数':>6}  {'胜率':>8}  {'均收益':>10}  {'中位数收益':>10}  "
          f"{'均盈利':>10}  {'均亏损':>10}  {'盈亏比':>8}  {'PF':>8}")
    print("  " + "-" * 96)

    for hold_n in [1, 2, 3]:
        col = f"ret_t{hold_n}"
        valid = df[col].dropna()
        if valid.empty:
            print(f"  T+{hold_n}     无数据")
            continue

        total = len(valid)
        win_rate = (valid > 0).mean()
        avg_ret = valid.mean()
        med_ret = valid.median()
        avg_win = valid[valid > 0].mean() if (valid > 0).any() else 0.0
        avg_loss = valid[valid < 0].mean() if (valid < 0).any() else 0.0
        payoff = -avg_win / avg_loss if avg_loss < 0 else 0.0
        gross_win = valid[valid > 0].sum()
        gross_loss = -valid[valid < 0].sum()
        pf = gross_win / gross_loss if gross_loss > 0 else 0.0

        print(f"  T+{hold_n}       {total:>6}  {win_rate:>8.2%}  {avg_ret:>10.4%}  {med_ret:>10.4%}  "
              f"{avg_win:>10.4%}  {avg_loss:>10.4%}  {payoff:>8.2f}  {pf:>8.2f}")

    # 7. 按评分分层统计
    print(f"\n{'=' * 70}")
    print("  按评分分层 — T+1收益统计")
    print("=" * 70)
    df["score_bin"] = pd.cut(
        df["signal_score"],
        bins=[0, 55, 60, 65, 70, 75, 80, 100],
        labels=["<55", "55-60", "60-65", "65-70", "70-75", "75-80", ">80"]
    )
    for label, grp in df.groupby("score_bin", observed=True):
        valid = grp["ret_t1"].dropna()
        if valid.empty:
            continue
        wr = (valid > 0).mean()
        ar = valid.mean()
        cnt = len(valid)
        print(f"  评分{label:>8}  笔数={cnt:>5}  胜率={wr:.2%}  均收益={ar:.4%}")

    # 7b. 按 A/B 信号分级 — T+1
    if "signal_grade" in df.columns and df["signal_grade"].notna().any():
        print(f"\n{'=' * 70}")
        print("  按信号分级（A=放量突破 / B=正常量能突破）— T+1")
        print("=" * 70)
        for g in sorted(df["signal_grade"].dropna().unique()):
            valid = df.loc[df["signal_grade"] == g, "ret_t1"].dropna()
            if valid.empty:
                continue
            wr = (valid > 0).mean()
            ar = valid.mean()
            cnt = len(valid)
            print(f"  {g}级  笔数={cnt:>5}  胜率={wr:.2%}  均收益={ar:.4%}")

    # 8. 按RS分位分层
    print(f"\n{'=' * 70}")
    print("  按RS横截面分位 — T+1收益统计")
    print("=" * 70)
    df["rs_bin"] = pd.cut(
        df["rs20_xsec_q"],
        bins=[0, 0.80, 0.85, 0.90, 0.95, 1.01],
        labels=["80-85%", "85-90%", "90-95%", "95-100%", ">100%"],
        right=False
    )
    for label, grp in df.groupby("rs_bin", observed=True):
        valid = grp["ret_t1"].dropna()
        if valid.empty:
            continue
        wr = (valid > 0).mean()
        ar = valid.mean()
        cnt = len(valid)
        print(f"  RS分位{label:>10}  笔数={cnt:>5}  胜率={wr:.2%}  均收益={ar:.4%}")

    # 9. 按月统计
    print(f"\n{'=' * 70}")
    print("  按月份 — T+1统计")
    print("=" * 70)
    df["month"] = df["signal_date"].str[:6]
    for month, grp in df.groupby("month"):
        valid = grp["ret_t1"].dropna()
        if valid.empty:
            continue
        wr = (valid > 0).mean()
        ar = valid.mean()
        cnt = len(valid)
        print(f"  {month}  笔数={cnt:>5}  胜率={wr:.2%}  均收益={ar:.4%}")

    # 10. 汇总模拟净值曲线（等权组合）
    print(f"\n{'=' * 70}")
    print("  等权组合净值走势（每日信号等权买入，T+1退出）")
    print("=" * 70)
    daily_ret = df.groupby("signal_date")["ret_t1"].mean().dropna().sort_index()
    if not daily_ret.empty:
        equity = (1.0 + daily_ret).cumprod()
        total_ret = float(equity.iloc[-1] - 1.0)
        max_dd = float((equity / equity.cummax() - 1.0).min())
        sharpe = float(daily_ret.mean() / daily_ret.std() * np.sqrt(252)) if daily_ret.std() > 0 else 0.0

        print(f"  总收益     : {total_ret:.2%}")
        print(f"  最大回撤   : {max_dd:.2%}")
        print(f"  日夏普比率 : {sharpe:.2f}")
        print(f"  交易日数   : {len(daily_ret)}")

    print(f"\n{'=' * 70}")
    print("  回测完毕")
    print("=" * 70)


if __name__ == "__main__":
    main()
