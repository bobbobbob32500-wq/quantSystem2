# -*- coding: utf-8 -*-
"""
聚宽研究环境 — 标准突破策略（对齐本地 quantSystem 预设 baseline）

与仓库内其它聚宽脚本的关系：
  - joinquant_breakout_baseline_v1.py（本文件）：选股更严、池更小（rs≥0.80、评分≥60、top_k=20、箱体≤8%），
    买点参数为 BreakoutParams 默认值（缓冲 0.2%、追高 0.8%、量比下限 1.0 等）。
  - joinquant_wide_breakout_v2.py：宽进严出 wide_pool_strict_entry_v2（放宽选股 + buy_tuning 买点）。
  - joinquant_wide_breakout_minute_v1.py：在宽进 v2 候选池上，用分钟线估算量比做盘中触发。

选股层（对应 get_breakout_params_for_backtest("baseline")）：
  rs_quantile_min=0.80, min_signal_score=60, top_k=20,
  atr 用绝对阈值近似（atr_ratio ≤ atr_hard_cap），box_max_range=0.08

买点层（BreakoutParams 类默认值，未在 baseline 预设中覆盖）：
  breakout_buffer=0.002, breakout_max_chase=0.008,
  volume_confirm_ratio=1.2, volume_normal_ratio=1.0, max_intraday_gain=0.05

卖点（本版专用）：T+2 统一卖出（与 wide v2 不同）
  - 建仓日记为 trade_day_idx；当 hold_days = 当前交易日序号 - 建仓日 ≥ 2 时，
    在 14:56 一次性清仓（不再判断止损、MA5、前低、原时间止损）。
  - A 股 T+1：建仓当日 hold_days=0，次日 hold_days=1 可卖但本策略不卖出；
    再下一日 hold_days=2 → 统一卖出。
  - 若需与本地「持仓4日」等规则对照，请用旧版 wide 脚本或自行改回。

使用说明（聚宽）：
  1. 新建股票策略，首行建议：from jqdata import *
  2. 粘贴本文件；回测频率选「每天」。
  3. 若 money 字段报错，可去掉 get_price 的 money 字段，用 volume*收盘价近似成交额。

本地仓库路径：scripts/joinquant_breakout_baseline_v1.py
"""

try:
    from jqdata import *  # noqa: F401,F403
except ImportError:
    pass

try:
    _jq_log = log  # noqa: F821
except NameError:

    class _LocalLog:
        def _out(self, prefix, msg, args):
            text = str(msg) % args if args else str(msg)
            print(prefix + text)

        def info(self, msg, *args):
            self._out("[INFO] ", msg, args)

        def warn(self, msg, *args):
            self._out("[WARN] ", msg, args)

        def error(self, msg, *args):
            self._out("[ERROR] ", msg, args)

    _jq_log = _LocalLog()

# ---------- 与本地 baseline 预设 + BreakoutParams 默认买点一致 ----------
P = {
    "breakout_buffer": 0.002,
    "breakout_max_chase": 0.008,
    "volume_confirm_ratio": 1.2,
    "volume_normal_ratio": 1.0,
    "max_intraday_gain": 0.05,
    "pivot_days": 10,
    "box_max_range": 0.08,
    "top_k": 20,
    "min_score": 60.0,
    "rs_q_min": 0.80,
    "min_avg_amount_20": 80_000_000.0,
    # 本地 baseline 用横截面 ATR 分位；此处用绝对波动率上限做近似，略严于宽池 0.12
    "atr_hard_cap": 0.10,
    # 仅用于卖点：建仓后第 N 个交易日统一卖出（本策略固定为 2，即 T+2）
    "hold_exit_days": 2,
}


def initialize(context):
    set_benchmark("000300.XSHG")
    set_option("use_real_price", True)
    set_order_cost(
        OrderCost(
            open_tax=0,
            close_tax=0.001,
            open_commission=0.0003,
            close_commission=0.0003,
            close_today_commission=0,
            min_commission=5,
        ),
        type="stock",
    )
    set_slippage(PriceRelatedSlippage(0.00246))
    g.watchlist = {}
    g.entry_meta = {}
    g.trade_day_idx = 0

    _jq_log.info(
        "标准突破 baseline：min_score=%.1f rs_q_min=%.2f top_k=%d 箱体≤%.0f%% 卖点=T+%d 统一清仓",
        P["min_score"],
        P["rs_q_min"],
        P["top_k"],
        P["box_max_range"] * 100,
        P["hold_exit_days"],
    )

    run_daily(on_new_trade_day, time="9:00")
    run_daily(prepare_watchlist, time="9:05")
    run_daily(try_breakout_and_trade, time="14:50")
    run_daily(manage_sell, time="14:56")


def on_new_trade_day(context):
    g.trade_day_idx = getattr(g, "trade_day_idx", 0) + 1
    _jq_log.info("[交易日] trade_day_idx=%d 日期=%s", g.trade_day_idx, context.current_dt.date())


def _box_pivot(box_days, high, low, close):
    import numpy as np

    hh = high.shift(1).rolling(box_days).max()
    ll = low.shift(1).rolling(box_days).min()
    box_range = (hh - ll) / close.replace(0, np.nan)
    pivot = hh
    return pivot, box_range


def _score(ret20, box_r, atr_ratio):
    s = 40.0
    s += min(25.0, max(0.0, ret20 * 100))
    s += min(20.0, (1.0 - min(box_r / P["box_max_range"], 1.0)) * 20.0)
    s += min(15.0, (1.0 - min(atr_ratio / 0.55, 1.0)) * 15.0)
    return float(min(100.0, s))


def prepare_watchlist(context):
    import numpy as np

    g.watchlist = {}
    last_day = getattr(context, "previous_date", None)
    if last_day is None:
        _jq_log.warn("[选股] previous_date 为空，跳过")
        return

    stocks = list(get_index_stocks("000300.XSHG"))
    if not stocks:
        return

    try:
        cd = get_current_data()
    except Exception:
        cd = None

    st = {
        "st": 0,
        "数据不足": 0,
        "成交额": 0,
        "均线": 0,
        "箱体波动": 0,
        "pivot无效": 0,
        "atr过高": 0,
        "分数": 0,
        "异常": 0,
    }
    err_sample = None
    candidates = []

    for code in stocks:
        try:
            if cd is not None and code in cd and getattr(cd[code], "is_st", False):
                st["st"] += 1
                continue
            df = get_price(
                code,
                end_date=last_day,
                count=80,
                frequency="daily",
                fields=["open", "high", "low", "close", "volume", "money"],
                skip_paused=True,
                fq="pre",
            )
            if df is None or len(df) < 65:
                st["数据不足"] += 1
                continue
            close = df["close"].astype(float)
            high = df["high"].astype(float)
            low = df["low"].astype(float)
            money = df["money"].astype(float) if "money" in df.columns else close * df["volume"].astype(float)

            if money.tail(20).mean() < P["min_avg_amount_20"]:
                st["成交额"] += 1
                continue

            ma20 = close.rolling(20).mean()
            ma60 = close.rolling(60).mean()
            if ma20.iloc[-1] <= ma60.iloc[-1]:
                st["均线"] += 1
                continue

            pivot, box_range = _box_pivot(P["pivot_days"], high, low, close)
            br = float(box_range.iloc[-1])
            if np.isnan(br) or br > P["box_max_range"]:
                st["箱体波动"] += 1
                continue
            pv = float(pivot.iloc[-1])
            if np.isnan(pv) or pv <= 0:
                st["pivot无效"] += 1
                continue

            ret20 = float(close.iloc[-1] / close.iloc[-21] - 1.0) if len(close) > 21 else 0.0

            tr = np.maximum(
                high - low,
                np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))),
            )
            atr14 = float(tr.tail(14).mean())
            atr_ratio = atr14 / close.iloc[-1] if close.iloc[-1] > 0 else 1.0
            if atr_ratio > P["atr_hard_cap"]:
                st["atr过高"] += 1
                continue

            sc = _score(ret20, br, atr_ratio)
            if sc < P["min_score"]:
                st["分数"] += 1
                continue

            stop = max(float(low.tail(P["pivot_days"]).min()), pv - 1.2 * atr14)
            candidates.append({"code": code, "pivot": pv, "stop": stop, "score": sc, "ret20": ret20})
        except Exception as e:
            st["异常"] += 1
            if err_sample is None:
                err_sample = "%s: %s" % (code, e)

    n0 = len(candidates)
    if not candidates:
        _jq_log.info(
            "[选股] 截止日=%s 沪深300=%d只 初筛候选=0 剔除统计=%s 首条异常=%s",
            last_day,
            len(stocks),
            st,
            err_sample,
        )
        return

    rets = sorted([c["ret20"] for c in candidates])
    idx = int(len(rets) * P["rs_q_min"])
    idx = min(max(idx, 0), len(rets) - 1)
    thr = rets[idx]
    candidates = [c for c in candidates if c["ret20"] >= thr]
    n1 = len(candidates)
    candidates.sort(key=lambda x: x["score"], reverse=True)
    candidates = candidates[: P["top_k"]]

    g.watchlist = {c["code"]: {"pivot": c["pivot"], "stop": c["stop"], "score": c["score"]} for c in candidates}

    _jq_log.info(
        "[选股] 截止日=%s 沪深300=%d只 初筛=%d ret阈值=%.4f(rs_q=%.2f) 分位后=%d 观察池=%d 剔除=%s 异常=%s",
        last_day,
        len(stocks),
        n0,
        thr,
        P["rs_q_min"],
        n1,
        len(g.watchlist),
        st,
        err_sample,
    )


def try_breakout_and_trade(context):
    if not g.watchlist:
        _jq_log.info("[突破下单] 观察池为空，跳过")
        return

    cash = context.portfolio.available_cash
    n = max(1, len(g.watchlist))
    per = cash * 0.95 / float(n)

    today = context.current_dt.date()
    bt = {"已持仓": 0, "未突破": 0, "追击超限": 0, "日内涨幅": 0, "量比不足": 0, "数据不足": 0, "异常": 0}
    err_bt = None
    bought = 0

    _jq_log.info(
        "[突破下单] 日期=%s 观察池=%d只 可用资金≈%.0f 每票约%.0f",
        today,
        len(g.watchlist),
        cash,
        per,
    )

    for sec, meta in list(g.watchlist.items()):
        if sec in context.portfolio.positions and context.portfolio.positions[sec].total_amount > 0:
            bt["已持仓"] += 1
            continue
        pivot = float(meta["pivot"])
        try:
            df = get_price(
                sec,
                end_date=today,
                count=30,
                frequency="daily",
                fields=["open", "high", "low", "close", "volume"],
                skip_paused=True,
                fq="pre",
            )
            if df is None or len(df) < 2:
                bt["数据不足"] += 1
                continue
            row = df.iloc[-1]
            open_ = float(row["open"])
            high = float(row["high"])
            vol = float(row["volume"])
            vol_ma20 = float(df["volume"].tail(20).mean())

            trigger = pivot * (1.0 + P["breakout_buffer"])
            max_entry = pivot * (1.0 + P["breakout_max_chase"])

            if high < trigger:
                bt["未突破"] += 1
                continue
            entry = trigger
            if entry > max_entry or entry > high:
                bt["追击超限"] += 1
                continue
            if open_ > 0 and (high / open_ - 1.0) > P["max_intraday_gain"]:
                bt["日内涨幅"] += 1
                continue

            vr = vol / vol_ma20 if vol_ma20 > 0 else 0.0
            if vr < P["volume_normal_ratio"]:
                bt["量比不足"] += 1
                continue

            order_target_value(sec, per)
            g.entry_meta[sec] = {
                "entry_day": getattr(g, "trade_day_idx", 0),
            }
            bought += 1
            _jq_log.info(
                "[买入] %s pivot=%.3f 触发=%.3f 量比=%.2f(需≥%.2f) 金额≈%.0f",
                sec,
                pivot,
                trigger,
                vr,
                P["volume_normal_ratio"],
                per,
            )
        except Exception as e:
            bt["异常"] += 1
            if err_bt is None:
                err_bt = "%s: %s" % (sec, e)

    _jq_log.info("[突破下单] 本日汇总 新买入=%d 未成交原因统计=%s 异常=%s", bought, bt, err_bt)


def manage_sell(context):
    """仅 T+2（或 hold_exit_days）统一卖出：无止损、无均线、无前低。"""
    t1_skip = []
    need = int(P.get("hold_exit_days", 2))
    for sec, pos in list(context.portfolio.positions.items()):
        if pos.total_amount <= 0:
            continue
        meta = g.entry_meta.get(sec)
        if not meta:
            continue
        hold_days = getattr(g, "trade_day_idx", 0) - int(meta.get("entry_day", 0))
        if hold_days <= 0:
            t1_skip.append(sec)
            continue
        if hold_days < need:
            continue

        try:
            order_target_value(sec, 0)
            g.entry_meta.pop(sec, None)
            _jq_log.info("[统一卖出] %s 持仓交易日=%d（≥%d）全部清仓", sec, hold_days, need)
        except Exception as e:
            _jq_log.error("[卖出] %s 异常: %s", sec, e)

    if t1_skip:
        tail = ",".join(t1_skip[:10])
        if len(t1_skip) > 10:
            tail += "..."
        _jq_log.info("[卖出] 建仓当日 hold_days=0，本时段不卖出：%s", tail)


if __name__ == "__main__":
    pass
