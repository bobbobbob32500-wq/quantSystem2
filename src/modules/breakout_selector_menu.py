# -*- coding: utf-8 -*-
"""
选强→等突破 选股模块菜单入口

提供以下功能：
  1. 执行盘前选股（指定日期或取最新交易日）
  2. 查看今日观察池
  3. 查看单只股票因子诊断
  4. 批量回测选股效果（多日回溯，统计选出股票的后续表现）
  5. 参数调整预览（修改阈值后实时查看筛选变化）

选股完成后会自动合并写入 data/cache/candidate_pool.json，
与首页指挥台、Web 看板「候选池」对齐（默认 strategy_profile=breakout；「宽进突破」为 wide_breakout，可与原突破并存）；
「一键日报」仍走原 StockSelector，与突破池独立。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.core.logger import get_logger
from src.modules.breakout_strategy import (
    BreakoutStrategy,
    BreakoutParams,
    WatchItem,
    BreakoutSignal,
    build_breakout_strategy_from_config,
    build_wide_breakout_strategy_from_config,
    resolve_breakout_preset_from_config,
)

logger = get_logger("breakout_selector_menu")


def merge_breakout_watchlist_to_candidate_cache(
    watch_items: List[WatchItem],
    watch_date: str,
    project_root: Optional[Path] = None,
    strategy_profile: str = "breakout",
    strategy_name: str = "breakout_watchlist",
    level_label: str = "突破观察池",
    source: str = "breakout_strategy",
) -> int:
    """
    将突破观察池写入 data/cache/candidate_pool.json，供首页终端指挥台与 Web 看板「候选池」读取。

    仅移除缓存中 **与本次 strategy_profile 相同** 的历史条目，再写入本次结果；
    其他策略（含另一类突破档案）条目予以保留。
    """
    root = project_root or Path(__file__).resolve().parents[2]
    cache_path = root / "data" / "cache" / "candidate_pool.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    profile_key = str(strategy_profile or "breakout").strip() or "breakout"

    prev_candidates: List[dict] = []
    if cache_path.is_file():
        try:
            payload_old = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(payload_old, dict):
                raw = payload_old.get("candidates")
                if isinstance(raw, list):
                    prev_candidates = [
                        c
                        for c in raw
                        if isinstance(c, dict) and c.get("strategy_profile") != profile_key
                    ]
        except Exception as exc:
            logger.warning("读取候选池缓存失败，将覆盖写入: %s", exc)
            prev_candidates = []

    new_rows: List[dict] = []
    wd = str(watch_date or "").strip()
    for item in watch_items or []:
        code = str(getattr(item, "ts_code", "") or "").strip()
        if not code:
            continue
        sym = code.split(".")[0]
        new_rows.append(
            {
                "symbol": sym,
                "ts_code": code,
                "name": str(getattr(item, "name", "") or ""),
                "score": float(getattr(item, "signal_score", 0.0) or 0.0),
                "level": level_label,
                "industry": str(getattr(item, "industry", "") or "未知"),
                "pool_type": "core",
                "strategy_profile": profile_key,
                "strategy_name": strategy_name,
                "source": source,
                "trade_date": wd,
                "trigger_price": float(getattr(item, "trigger_price", 0.0) or 0.0),
                "pivot": float(getattr(item, "pivot", 0.0) or 0.0),
                "stop_loss": float(getattr(item, "stop_loss", 0.0) or 0.0),
            }
        )

    merged = prev_candidates + new_rows
    out_payload = {
        "date": wd,
        "candidates": merged,
        "created_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "breakout_synced": len(new_rows),
    }
    cache_path.write_text(json.dumps(out_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(new_rows)


def build_breakout_pre_market_payload(
    watch_items: List[WatchItem],
    trade_date: str,
    market_analysis: Optional[Dict[str, Any]] = None,
    pool_level_label: str = "突破观察池",
    strategy_label: str = "选强→等突破（观察池）",
) -> Dict[str, Any]:
    """组装与企业微信盘前计划模板兼容的 payload。"""
    stocks: List[Dict[str, Any]] = []
    for it in watch_items or []:
        stocks.append(
            {
                "ts_code": it.ts_code,
                "name": it.name,
                "total_score": float(it.signal_score or 0.0),
                "level": pool_level_label,
            }
        )
    td = str(trade_date or "").strip()
    if len(td) == 8 and td.isdigit():
        report_date = f"{td[:4]}-{td[4:6]}-{td[6:8]}"
    else:
        report_date = datetime.now().strftime("%Y-%m-%d")
    return {
        "report_date": report_date,
        "report_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "strategy_label": strategy_label,
        "stock_selection": stocks,
        "market_analysis": market_analysis if isinstance(market_analysis, dict) else {},
    }


def offer_breakout_wechat_push(
    config: ConfigManager,
    db: DatabaseManager,
    watch_items: List[WatchItem],
    trade_date: str,
    pool_level_label: str = "突破观察池",
    strategy_label: str = "选强→等突破（观察池）",
) -> None:
    """控制台询问后推送盘前计划。"""
    if not watch_items:
        return
    push = input("\n  是否推送盘前计划到企业微信? (y/n): ").strip().lower()
    if push != "y":
        return
    try:
        from src.modules.message_pusher import MessagePusher

        market_analysis: Dict[str, Any] = {}
        try:
            from src.modules.position_controller import PositionController

            pc = PositionController(config, db)
            latest = db.get_latest_trade_date("stock_daily")
            market_analysis = pc.analyze_market(end_date=latest) or {}
        except Exception:
            market_analysis = {}

        payload = build_breakout_pre_market_payload(
            watch_items, trade_date, market_analysis,
            pool_level_label=pool_level_label,
            strategy_label=strategy_label,
        )
        pusher = MessagePusher(config, db)
        if pusher.push_pre_market_selection(payload):
            print("  已推送 ✓")
        else:
            print("  推送失败（请检查消息渠道配置）")
    except Exception as exc:
        logger.exception("突破观察池推送失败")
        print(f"  推送异常: {exc}")


def sync_breakout_watchlist_to_system_cache(
    watch_items: List[WatchItem],
    watch_date: str,
    **merge_kw: Any,
) -> int:
    """
    选股完成后同步候选池并打印提示。
    返回本次写入的突破标的数量。
    merge_kw 透传 merge_breakout_watchlist_to_candidate_cache（如 strategy_profile、level_label）。
    """
    n = merge_breakout_watchlist_to_candidate_cache(watch_items, watch_date, **merge_kw)
    label = str(merge_kw.get("level_label") or "突破观察池")
    print(
        f"\n  已写入候选池缓存 data/cache/candidate_pool.json："
        f"{label} {n} 只（已合并保留其他策略标的，刷新首页/看板可见）"
    )
    return n


# ═══════════════════════════════════════════════════════════════
# 格式化输出工具
# ═══════════════════════════════════════════════════════════════

def _hr(char: str = "─", width: int = 72) -> str:
    return char * width


def _print_watch_list(items: List[WatchItem]) -> None:
    """打印观察池列表"""
    if not items:
        print("  暂无符合条件的股票")
        return

    # 表头
    print(f"\n{'序号':>4}  {'代码':>12}  {'名称':<8}  {'收盘':>7}  {'pivot':>7}  "
          f"{'触发价':>7}  {'止损':>7}  {'RS分位':>6}  {'箱宽%':>5}  "
          f"{'ATR波动分位':>8}  {'评分':>6}  {'行业':<10}")
    print(_hr())
    for i, item in enumerate(items, 1):
        # 止损距离（风险R值参考）
        r_pct = (item.trigger_price - item.stop_loss) / item.trigger_price * 100
        print(
            f"{i:>4}  {item.ts_code:>12}  {item.name:<8}  "
            f"{item.close:>7.2f}  {item.pivot:>7.2f}  "
            f"{item.trigger_price:>7.2f}  {item.stop_loss:>7.2f}  "
            f"{item.rs20_xsec_q:>6.2%}  {item.box_range:>5.1f}  "
            f"{item.atr_ratio_q60:>8.2%}  {item.signal_score:>6.1f}  "
            f"{item.industry:<10}"
        )
    print(_hr())
    print(f"  共 {len(items)} 只股票进入观察池")


def print_breakout_watch_list(items: List[WatchItem]) -> None:
    """对外可用的观察池打印（供 main 等入口复用）。"""
    _print_watch_list(items)


def _print_item_detail(item: WatchItem) -> None:
    """打印单只股票详细因子信息"""
    print(f"\n{'═' * 60}")
    print(f"  {item.name}（{item.ts_code}）  {item.watch_date}")
    print(f"{'═' * 60}")
    print(f"  收盘价     : {item.close:.2f}")
    print(f"  均线       : MA20={item.ma20:.2f}  MA60={item.ma60:.2f}  MA120={item.ma120:.2f}")
    print(f"  趋势状态   : {'多头排列 ✓' if item.ma20 > item.ma60 > item.ma120 else '非多头排列'}")
    print(f"  ─────────────────────────────────────")
    print(f"  近20日涨幅 : {item.rs20:.2f}%")
    print(f"  RS横截面分位: {item.rs20_xsec_q:.2%}（全主板前{(1-item.rs20_xsec_q)*100:.0f}%）")
    print(f"  ─────────────────────────────────────")
    print(f"  ATR14      : {item.atr14:.4f}（占收盘价{item.atr14/item.close*100:.2f}%）")
    print(f"  ATR波动分位 : {item.atr_ratio_q60:.2%}（60日分位，越低越稳）")
    print(f"  10日箱体宽度: {item.box_range:.2f}%（≤8%为佳）")
    print(f"  ─────────────────────────────────────")
    print(f"  突破基准   : pivot={item.pivot:.2f}")
    print(f"  触发价     : {item.trigger_price:.2f}（pivot+0.2%缓冲）")
    print(f"  初始止损   : {item.stop_loss:.2f}（距触发价风险{(item.trigger_price-item.stop_loss)/item.trigger_price*100:.2f}%）")
    print(f"  ─────────────────────────────────────")
    print(f"  综合评分   : {item.signal_score:.1f}/100")
    print(f"  评分明细   : {item.score_detail}")
    print(f"  行业       : {item.industry}")


# ═══════════════════════════════════════════════════════════════
# 批量回测：统计选股后 N 日表现
# ═══════════════════════════════════════════════════════════════

def _run_backtest_review(
    strategy: BreakoutStrategy,
    db: DatabaseManager,
    start_date: str,
    end_date: str,
    hold_days: int = 5,
) -> None:
    """
    批量回溯选股效果：
    对 [start_date, end_date] 区间内每个交易日运行盘前选股，
    仅在下一交易日满足「突破 + 量能」时记为成交，再统计持有 hold_days 的收益。
    """
    print(f"\n  正在批量回溯 {start_date} → {end_date}，突破确认后持有 {hold_days} 天...")

    # 拉取交易日列表
    sql_dates = """
        SELECT DISTINCT trade_date FROM stock_daily
        WHERE trade_date >= ? AND trade_date <= ?
        ORDER BY trade_date ASC
    """
    rows = db.query(sql_dates, (start_date, end_date))
    if not rows:
        print("  数据不足，无法回溯")
        return

    trade_dates = [r["trade_date"] for r in rows]
    print(f"  共 {len(trade_dates)} 个交易日")

    all_dates_rows = db.query(
        "SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date ASC"
    )
    all_dates = [r["trade_date"] for r in all_dates_rows]
    date_pos = {str(d): i for i, d in enumerate(all_dates)}

    # 因子截止日：取请求区间与数据库上限的较小值，并留出持有期
    pad = (datetime.strptime(end_date, "%Y%m%d") + timedelta(days=hold_days * 3)).strftime("%Y%m%d")
    cap_row = db.query("SELECT MAX(trade_date) AS m FROM stock_daily")
    cap = str(cap_row[0]["m"]) if cap_row and cap_row[0].get("m") else end_date
    end_feat = min(pad, cap)

    raw_daily, raw_basic = strategy._load_data(end_feat)
    if raw_daily.empty:
        print("  日线数据不足，无法计算因子")
        return
    features = strategy._compute_features(raw_daily, raw_basic, end_feat)
    print(f"  因子表已构建（截止 {end_feat}），用于 T+1 突破确认")

    # 收盘价序列（确认日之后持有）
    sql_prices = """
        SELECT ts_code, trade_date, close
        FROM stock_daily
        WHERE trade_date >= ? AND trade_date <= ?
        ORDER BY ts_code ASC, trade_date ASC
    """
    price_rows = db.query(sql_prices, (start_date, end_feat))
    if not price_rows:
        print("  价格数据不足")
        return

    price_df = pd.DataFrame(price_rows)
    price_df["trade_date"] = price_df["trade_date"].astype(str)
    price_map = {code: sub.reset_index(drop=True)
                 for code, sub in price_df.groupby("ts_code")}

    all_trades = []
    total_dates = len(trade_dates)

    for i, td in enumerate(trade_dates):
        if (i + 1) % 10 == 0:
            print(f"  进度: {i+1}/{total_dates} ({(i+1)/total_dates*100:.0f}%)")

        td_str = str(td)
        pos = date_pos.get(td_str)
        if pos is None or pos + 1 >= len(all_dates):
            continue
        next_d = str(all_dates[pos + 1])

        try:
            items = strategy.run(end_date=td_str)
        except Exception as e:
            logger.debug("选股失败 %s: %s", td_str, e)
            continue

        if not items:
            continue

        confirm_map = strategy.bars_dict_for_trade_date(features, next_d)
        signals = strategy.confirm_breakout_daily(items, confirm_map)

        for sig in signals:
            sub = price_map.get(sig.ts_code)
            if sub is None or sub.empty:
                continue
            cd = str(sig.confirm_date)
            future = sub[sub["trade_date"] > cd]
            if len(future) < hold_days:
                continue
            entry_price = float(sig.entry_price)
            if entry_price <= 0:
                continue
            exit_close = float(future.iloc[hold_days - 1]["close"])
            ret = exit_close / entry_price - 1.0

            all_trades.append({
                "signal_date": td_str,
                "confirm_date": cd,
                "ts_code": sig.ts_code,
                "name": sig.name,
                "entry_price": entry_price,
                "exit_close": exit_close,
                "ret": ret,
                "score": sig.signal_score,
                "rs_q": next((it.rs20_xsec_q for it in items if it.ts_code == sig.ts_code), 0.0),
                "grade": sig.signal_grade,
                "vol_ratio": sig.volume_ratio,
            })

    if not all_trades:
        print("  无有效交易记录")
        return

    df = pd.DataFrame(all_trades)
    win_rate = float((df["ret"] > 0).mean())
    avg_ret = float(df["ret"].mean())
    median_ret = float(df["ret"].median())
    profit = float(df[df["ret"] > 0]["ret"].mean()) if (df["ret"] > 0).any() else 0.0
    loss = float(df[df["ret"] < 0]["ret"].mean()) if (df["ret"] < 0).any() else 0.0
    profit_factor = float((df[df["ret"] > 0]["ret"].sum()) / (-df[df["ret"] < 0]["ret"].sum())) \
        if (df["ret"] < 0).any() and (-df[df["ret"] < 0]["ret"].sum()) > 0 else 0.0

    print(f"\n{'═' * 60}")
    print(f"  选股回溯结果（突破+量能确认后持有 {hold_days} 天）")
    print(f"{'═' * 60}")
    print(f"  总成交笔数   : {len(df)}")
    print(f"  有成交信号日 : {df['signal_date'].nunique()}")
    if df["signal_date"].nunique() > 0:
        print(f"  日均成交     : {len(df) / df['signal_date'].nunique():.1f} 笔")
    print(f"  胜率         : {win_rate:.2%}")
    print(f"  平均收益     : {avg_ret:.2%}")
    print(f"  中位数收益   : {median_ret:.2%}")
    print(f"  平均盈利     : {profit:.2%}")
    print(f"  平均亏损     : {loss:.2%}")
    print(f"  盈亏比       : {-profit/loss:.2f}" if loss < 0 else "  盈亏比       : N/A")
    print(f"  Profit Factor: {profit_factor:.2f}")
    if "grade" in df.columns:
        for g in sorted(df["grade"].dropna().unique()):
            subg = df.loc[df["grade"] == g, "ret"]
            if subg.empty:
                continue
            print(
                f"  {g}级成交      : {len(subg)} 笔  胜率={(subg > 0).mean():.2%}  均收益={subg.mean():.2%}"
            )
    print(f"{'─' * 60}")

    # 按评分分组看胜率
    df["score_bin"] = pd.cut(df["score"], bins=[0, 60, 70, 80, 100], labels=["<60", "60-70", "70-80", ">80"])
    grp = df.groupby("score_bin", observed=True).agg(
        次数=("ret", "count"),
        胜率=("ret", lambda x: (x > 0).mean()),
        均收益=("ret", "mean"),
    )
    print("\n  评分分层统计：")
    print(grp.to_string())
    print(f"{'═' * 60}")


# ═══════════════════════════════════════════════════════════════
# 主菜单
# ═══════════════════════════════════════════════════════════════

def _breakout_selector_menu_impl(
    config: ConfigManager,
    db: DatabaseManager,
    *,
    banner_title: str,
    preset_line: str,
    strategy: BreakoutStrategy,
    sync_merge_kw: Optional[Dict[str, Any]] = None,
    wechat_pool_level: str = "突破观察池",
    wechat_strategy_label: str = "选强→等突破（观察池）",
    allow_adjust_params: bool = True,
) -> None:
    """突破类选股菜单共用循环（原突破 / 宽进突破）。"""
    merge_kw: Dict[str, Any] = dict(sync_merge_kw or {})
    params = strategy.params
    last_items: List[WatchItem] = []

    while True:
        print(f"\n{'═' * 60}")
        print(f"  {banner_title}")
        print(f"  {preset_line}")
        print(f"{'═' * 60}")
        print("  1. 执行今日选股（取数据库最新交易日）")
        print("  2. 执行指定日期选股")
        print("  3. 查看单只股票因子详情")
        print("  4. 批量回溯选股效果")
        if allow_adjust_params:
            print("  5. 调整关键参数")
        else:
            print("  5. 调整关键参数（宽进突破为固定预设，此项仅作说明）")
        print("  6. 显示当前参数")
        print("  7. 盘中突破监控")
        print("  0. 返回上级菜单")
        print(f"{'─' * 60}")

        choice = input("  请选择: ").strip()

        if choice == "1":
            print("\n  正在执行盘前选股...")
            try:
                last_items = strategy.run()
                _print_watch_list(last_items)
                wd = (
                    last_items[0].watch_date
                    if last_items
                    else strategy._resolve_end_date(None)
                )
                sync_breakout_watchlist_to_system_cache(last_items, wd, **merge_kw)
                offer_breakout_wechat_push(
                    config, db, last_items, wd,
                    pool_level_label=wechat_pool_level,
                    strategy_label=wechat_strategy_label,
                )
            except Exception as e:
                print(f"  选股失败: {e}")
                logger.exception("选股执行失败")

        elif choice == "2":
            date_str = input("  请输入日期 (YYYYMMDD): ").strip()
            if len(date_str) == 8 and date_str.isdigit():
                print(f"\n  正在执行 {date_str} 盘前选股...")
                try:
                    last_items = strategy.run(end_date=date_str)
                    _print_watch_list(last_items)
                    wd = last_items[0].watch_date if last_items else date_str
                    sync_breakout_watchlist_to_system_cache(last_items, wd, **merge_kw)
                    offer_breakout_wechat_push(
                        config, db, last_items, wd,
                        pool_level_label=wechat_pool_level,
                        strategy_label=wechat_strategy_label,
                    )
                except Exception as e:
                    print(f"  选股失败: {e}")
                    logger.exception("选股执行失败")
            else:
                print("  日期格式错误，请输入8位数字，如 20240315")

        elif choice == "3":
            if not last_items:
                print("  请先执行选股（选项1或2）")
                continue
            idx_str = input(f"  请输入序号 (1~{len(last_items)}): ").strip()
            try:
                idx = int(idx_str) - 1
                if 0 <= idx < len(last_items):
                    _print_item_detail(last_items[idx])
                else:
                    print("  序号超出范围")
            except ValueError:
                print("  请输入有效数字")

        elif choice == "4":
            print("\n  批量回溯选股效果")
            start = input("  开始日期 (YYYYMMDD, 如 20230101): ").strip()
            end = input("  结束日期 (YYYYMMDD, 如 20231231): ").strip()
            hold_str = input("  持有天数 (默认5): ").strip()
            hold = int(hold_str) if hold_str.isdigit() else 5

            if len(start) == 8 and len(end) == 8 and start.isdigit() and end.isdigit():
                try:
                    _run_backtest_review(strategy, db, start, end, hold)
                except Exception as e:
                    print(f"  回溯失败: {e}")
                    logger.exception("批量回溯失败")
            else:
                print("  日期格式错误")

        elif choice == "5":
            if not allow_adjust_params:
                print("  宽进突破策略参数固定，请通过配置文件或代码修改预设。")
                continue
            _adjust_params_menu(params, strategy)

        elif choice == "6":
            _print_params(params)

        elif choice == "7":
            from src.modules.breakout_intraday_monitor import breakout_monitor_menu
            breakout_monitor_menu(
                strategy=strategy,
                watch_items=last_items if last_items else None,
                db=db, config=config,
            )

        elif choice == "0":
            break

        else:
            print("  无效输入，请重新选择")


def breakout_selector_menu(config: ConfigManager = None, db: DatabaseManager = None) -> None:
    """选股模块主菜单（原突破：参数来自 stock_selection.breakout.params_preset）"""
    if config is None:
        config = ConfigManager()
    if db is None:
        db = DatabaseManager(config)

    preset_name = resolve_breakout_preset_from_config(config)
    strategy = build_breakout_strategy_from_config(db, config)
    _breakout_selector_menu_impl(
        config,
        db,
        banner_title="选强→等突破→跟强留强  策略系统",
        preset_line=f"参数预设: {preset_name}（配置项 stock_selection.breakout.params_preset）",
        strategy=strategy,
        sync_merge_kw={},
        allow_adjust_params=True,
    )


def wide_breakout_selector_menu(config: ConfigManager = None, db: DatabaseManager = None) -> None:
    """宽进突破策略：选股放宽 + 买点最严（回测预设 wide_pool_strict_entry_v2），独立候选池档案 wide_breakout。"""
    if config is None:
        config = ConfigManager()
    if db is None:
        db = DatabaseManager(config)

    strategy = build_wide_breakout_strategy_from_config(db, config)
    _breakout_selector_menu_impl(
        config,
        db,
        banner_title="宽进突破策略（选强→等突破）",
        preset_line="固定参数: wide_pool_strict_entry_v2（宽选股 + 最严买点 buy_tuning_v1 档）",
        strategy=strategy,
        sync_merge_kw={
            "strategy_profile": "wide_breakout",
            "strategy_name": "wide_breakout_watchlist",
            "level_label": "宽进突破观察池",
            "source": "wide_breakout_strategy",
        },
        wechat_pool_level="宽进突破观察池",
        wechat_strategy_label="宽进突破策略（观察池）",
        allow_adjust_params=False,
    )


def _adjust_params_menu(params: BreakoutParams, strategy: BreakoutStrategy) -> None:
    """参数调整子菜单"""
    print(f"\n{'─' * 60}")
    print("  关键参数调整（回车保持当前值）")
    print(f"{'─' * 60}")

    def _ask(label: str, current, cast=float) -> object:
        val = input(f"  {label} [{current}]: ").strip()
        if val == "":
            return current
        try:
            return cast(val)
        except ValueError:
            print(f"  输入无效，保持原值 {current}")
            return current

    params.rs_quantile_min = _ask("RS横截面分位下限 (0~1, 默认0.80)", params.rs_quantile_min)
    params.box_max_range = _ask("箱体最大宽度 (0~1, 默认0.08)", params.box_max_range)
    params.atr_quantile_max = _ask("ATR分位上限 (0~1, 默认0.50)", params.atr_quantile_max)
    params.min_amt_ma20 = _ask("20日均成交额下限(千元, 8e4≈日均8000万元)", params.min_amt_ma20)
    params.min_signal_score = _ask("最低综合评分 (0~100, 默认55)", params.min_signal_score)
    params.top_k = _ask("观察池最大数量 (默认20)", params.top_k, int)
    params.max_limit_up_count_20d = _ask("20日内最多涨停次数 (默认3)", params.max_limit_up_count_20d, int)

    # 同步到策略实例
    strategy.params = params
    print("  参数已更新 ✓")


def _print_params(params: BreakoutParams) -> None:
    """显示当前策略参数"""
    print(f"\n{'─' * 60}")
    print("  当前策略参数")
    print(f"{'─' * 60}")
    print(f"  【标的过滤】")
    print(f"    上市最少天数    : {params.min_list_days} 天")
    print(f"    20日均成交额下限: {params.min_amt_ma20 / 10:.0f} 万元")
    print(f"    股价区间        : {params.min_price}~{params.max_price} 元")
    print(f"    20日最多涨停次数: {params.max_limit_up_count_20d} 次")
    print(f"  【趋势过滤】")
    print(f"    均线周期        : MA{params.ma_short}/MA{params.ma_mid}/MA{params.ma_long}")
    print(f"    MA20斜率要求    : >{params.ma_slope_min:.3f}")
    print(f"  【强度过滤】")
    print(f"    RS横截面分位    : {params.rs_quantile_min:.0%} ~ {params.rs_quantile_max:.0%}")
    print(f"    RS计算回望      : {params.rs_lookback} 日")
    print(f"  【走稳过滤】")
    print(f"    ATR分位上限     : ≤{params.atr_quantile_max:.0%}（自身历史60日）")
    print(f"    箱体宽度上限    : ≤{params.box_max_range:.0%}（{params.box_days}日）")
    print(f"  【突破确认】")
    print(f"    突破缓冲        : {params.breakout_buffer:.1%}")
    print(f"    最大追高        : {params.breakout_max_chase:.1%}")
    print(f"    A级放量倍数     : ≥{params.volume_confirm_ratio:.1f}x（正常仓位）")
    print(f"    B级量能下限     : ≥{params.volume_normal_ratio:.1f}x（半仓）")
    print(f"    涨幅上限        : {params.max_intraday_gain:.0%}")
    print(f"    最大持仓天数    : {params.max_hold_days} 天")
    print(f"  【市场闸门（三档）】")
    print(f"    基准指数        : {params.index_code}")
    print(f"    谨慎档动量阈值  : 3日<{params.market_ret3_caution:.1%} / 5日<{params.market_ret5_caution:.1%}")
    print(f"    禁止档动量阈值  : 3日<{params.market_ret3_stop:.1%} / 5日<{params.market_ret5_stop:.1%}")
    print(f"    市场广度阈值    : 谨慎<{params.market_breadth_caution:.0%} / 禁止<{params.market_breadth_stop:.0%}")
    print(f"    谨慎档评分提升  : +{params.caution_score_boost:.1f} 分")
    print(f"  【选股输出】")
    print(f"    最低评分门槛    : {params.min_signal_score:.1f}")
    print(f"    观察池最大数量  : {params.top_k} 只")
    print(f"  【评分权重（满分100）】")
    print(f"    RS分位          : {params.weight_rs:.0f}")
    print(f"    趋势质量        : {params.weight_trend:.0f}")
    print(f"    走稳质量        : {params.weight_stability:.0f}")
    print(f"    箱体紧密度      : {params.weight_box:.0f}")
    print(f"    量能趋势        : {params.weight_volume:.0f}")
    print(f"{'─' * 60}")
