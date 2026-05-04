# -*- coding: utf-8 -*-
"""
聚宽 — 宽进突破（wide_pool_strict_entry_v2）分钟级回测版

设计目标：在「日线候选池」不变的前提下，尽量贴近实盘：
  - 选股：仍用截止前一交易日的日线（与 joinquant_wide_breakout_v2 相同）。
  - 买点：交易时段内每分钟用分钟线判断是否满足与本地 confirm_breakout_daily 等价的条件；
          量能用「当日累计成交量 / 已过交易分钟数 * 240」估算全日量，再与 vol_ma20 比（避免用全日量作弊）。
  - 卖点：① 盘中：分钟最低价触及初始止损 → 市价清仓；② 尾盘 run_daily：时间止损、MA5、前一日低点（与本地 check_hold_weakness 日线部分一致）。
  - T+1：建仓当日不卖出（与现版一致）。

重要：回测频率必须选「分钟」，否则 handle_data 不按分钟调用。

本地路径：scripts/joinquant_wide_breakout_minute_v1.py
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

# 与本地 wide_pool_strict_entry_v2 / joinquant_wide_breakout_v2 一致
P = {
    "breakout_buffer": 0.004,
    "breakout_max_chase": 0.005,
    "volume_confirm_ratio": 1.42,
    "volume_normal_ratio": 1.08,
    "max_intraday_gain": 0.035,
    "pivot_days": 10,
    "box_max_range": 0.095,
    "top_k": 28,
    "min_score": 58.0,
    "rs_q_min": 0.78,
    "min_avg_amount_20": 80_000_000.0,
    "atr_hard_cap": 0.12,
    "max_hold_days": 4,
    # 开盘后至少经过这么多「交易分钟」才允许买，避免量比估算极不稳定
    "min_elapsed_minutes_for_buy": 30,
    # 全日按 4 小时 = 240 分钟估算（与多数 A 股回测约定一致）
    "full_day_minutes": 240,
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
    g.buy_done_today = set()
    g.per_stock_value = None

    _jq_log.info(
        "分钟版宽进突破初始化：请使用「分钟」频率回测；买点=盘中分钟触发，卖点=盘中止损+尾盘日线"
    )

    run_daily(on_new_trade_day, time="9:00")
    run_daily(prepare_watchlist, time="9:05")
    run_daily(manage_sell_eod, time="14:56")


def before_trading_start(context):
    """每交易日开盘前清空当日下单标记与单笔目标市值。"""
    g.buy_done_today = set()
    g.per_stock_value = None


def on_new_trade_day(context):
    g.trade_day_idx = getattr(g, "trade_day_idx", 0) + 1
    _jq_log.info("[交易日] trade_day_idx=%d 日期=%s", g.trade_day_idx, context.current_dt.date())


def _box_pivot(box_days, high, low, close):
    import numpy as np
    import pandas as pd

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
    """与 v2 完全一致：截止 previous_date 的日线选股。"""
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

    if not candidates:
        _jq_log.info("[选股] 无候选 统计=%s", st)
        return

    rets = sorted([c["ret20"] for c in candidates])
    idx = int(len(rets) * P["rs_q_min"])
    idx = min(max(idx, 0), len(rets) - 1)
    thr = rets[idx]
    candidates = [c for c in candidates if c["ret20"] >= thr]
    candidates.sort(key=lambda x: x["score"], reverse=True)
    candidates = candidates[: P["top_k"]]

    g.watchlist = {c["code"]: {"pivot": c["pivot"], "stop": c["stop"], "score": c["score"]} for c in candidates}


def _trading_minutes_elapsed(now_dt):
    """当日 9:30–15:00 内已经过的交易分钟数（约 0–240）。"""
    h, m = now_dt.hour, now_dt.minute
    cur = h * 60 + m
    t0930 = 9 * 60 + 30
    t1130 = 11 * 60 + 30
    t1300 = 13 * 60
    t1500 = 15 * 60
    if cur < t0930 or cur > t1500:
        return 0
    if cur <= t1130:
        return max(1, cur - t0930 + 1)
    if cur < t1300:
        return 120
    return min(P["full_day_minutes"], 120 + (cur - t1300 + 1))


def _today_minute_ohlcv(sec, context):
    """取当日截至当前的分钟线聚合：开盘、最高、累计量、当日最低价序列用于止损。"""
    import pandas as pd

    try:
        df = get_price(
            sec,
            end_date=context.current_dt,
            count=300,
            frequency="1m",
            fields=["open", "high", "low", "volume"],
            skip_paused=True,
            fq="pre",
        )
    except Exception:
        return None
    if df is None or len(df) == 0:
        return None

    try:
        d0 = pd.Timestamp(context.current_dt).normalize()
        ix = pd.to_datetime(df.index)
        df = df[(ix >= d0) & (ix < d0 + pd.Timedelta(days=1))]
    except Exception:
        pass

    if df is None or len(df) == 0:
        return None

    o = float(df["open"].iloc[0])
    hi = float(df["high"].max())
    lo = float(df["low"].min())
    vol_cum = float(df["volume"].sum())
    low_last = float(df["low"].iloc[-1])
    return {"open": o, "high": hi, "low": lo, "vol_cum": vol_cum, "low_last": low_last, "n_bars": len(df)}


def _ensure_per_stock_value(context):
    if g.per_stock_value is not None:
        return
    n = len(g.watchlist)
    if n <= 0:
        return
    cash = context.portfolio.available_cash
    g.per_stock_value = cash * 0.95 / float(n)


def handle_data(context, data=None):
    """分钟驱动：盘中止损 + 突破买入（与日线版逻辑等价，但用分钟累计量估算量比）。

    注意：聚宽引擎会传入第二个参数 data（当前分钟行情），必须保留形参，即使未使用。
    """
    now = context.current_dt
    elapsed = _trading_minutes_elapsed(now)
    if elapsed <= 0:
        return

    # ---------- 盘中：初始止损（分钟最低价触及）----------
    t1_skip = []
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
        stop_loss = float(meta.get("stop", 0.0))
        if stop_loss <= 0:
            continue
        bar = _today_minute_ohlcv(sec, context)
        if bar is None:
            continue
        if bar["low"] <= stop_loss:
            order_target_value(sec, 0)
            g.entry_meta.pop(sec, None)
            _jq_log.info("[盘中止损] %s 最低=%.3f 线=%.3f", sec, bar["low"], stop_loss)

    # ---------- 买入：观察池内尚未持仓、当日未买过 ----------
    if not g.watchlist:
        return
    if elapsed < P["min_elapsed_minutes_for_buy"]:
        return

    _ensure_per_stock_value(context)
    if g.per_stock_value is None or g.per_stock_value < 3000:
        return

    today_str = now.date()
    for sec, meta in list(g.watchlist.items()):
        if sec in g.buy_done_today:
            continue
        if sec in context.portfolio.positions and context.portfolio.positions[sec].total_amount > 0:
            continue

        pivot = float(meta["pivot"])
        stop_ref = float(meta["stop"])
        try:
            df_d = get_price(
                sec,
                end_date=today_str,
                count=30,
                frequency="daily",
                fields=["volume"],
                skip_paused=True,
                fq="pre",
            )
            if df_d is None or len(df_d) < 20:
                continue
            vol_ma20 = float(df_d["volume"].tail(20).mean())
            if vol_ma20 <= 0:
                continue

            bar = _today_minute_ohlcv(sec, context)
            if bar is None:
                continue

            o = bar["open"]
            hi = bar["high"]
            vol_cum = bar["vol_cum"]
            if o <= 0 or hi <= 0:
                continue

            trigger = pivot * (1.0 + P["breakout_buffer"])
            max_entry = pivot * (1.0 + P["breakout_max_chase"])

            if hi < trigger:
                continue
            entry = trigger
            if entry > max_entry or entry > hi:
                continue
            if o > 0 and (hi / o - 1.0) > P["max_intraday_gain"]:
                continue

            # 估算全日量：累计量 / 已过分钟 * 240
            est_full = vol_cum * (float(P["full_day_minutes"]) / float(max(1, elapsed)))
            vr = est_full / vol_ma20
            if vr < P["volume_normal_ratio"]:
                continue

            order_target_value(sec, g.per_stock_value)
            g.buy_done_today.add(sec)
            g.entry_meta[sec] = {
                "entry_day": getattr(g, "trade_day_idx", 0),
                "stop": stop_ref,
            }
            _jq_log.info(
                "[分钟买入] %s 触发=%.3f 量比估=%.2f 已过%d分 金额≈%.0f",
                sec,
                trigger,
                vr,
                elapsed,
                g.per_stock_value,
            )
        except Exception as e:
            _jq_log.error("[分钟买入] %s %s", sec, e)


def manage_sell_eod(context):
    """尾盘：时间止损、MA5、前低（与日线版一致）；不含盘中已处理的初始止损。"""
    today = context.current_dt.date()
    t1_skip = []
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
        stop_loss = float(meta.get("stop", 0.0))

        try:
            df = get_price(
                sec,
                end_date=today,
                count=15,
                frequency="daily",
                fields=["open", "high", "low", "close"],
                skip_paused=True,
                fq="pre",
            )
            if df is None or len(df) < 3:
                continue
            close = df["close"].astype(float)
            low = df["low"].astype(float)
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            c = float(latest["close"])
            l_ = float(latest["low"])
            ma5 = float(close.tail(5).mean())
            prev_low = float(prev["low"])

            # 若尾盘日线最低价已触及止损，可能盘中已卖；此处再判断一次无妨
            if stop_loss > 0 and l_ <= stop_loss:
                order_target_value(sec, 0)
                g.entry_meta.pop(sec, None)
                _jq_log.info("[尾盘卖出] %s 止损(日线) 最低=%.3f 线=%.3f", sec, l_, stop_loss)
                continue
            if hold_days >= P["max_hold_days"]:
                order_target_value(sec, 0)
                g.entry_meta.pop(sec, None)
                _jq_log.info("[尾盘卖出] %s 时间止损 持仓日=%d", sec, hold_days)
                continue
            if ma5 > 0 and c < ma5:
                order_target_value(sec, 0)
                g.entry_meta.pop(sec, None)
                _jq_log.info("[尾盘卖出] %s 跌破MA5", sec)
                continue
            if prev_low > 0 and c < prev_low:
                order_target_value(sec, 0)
                g.entry_meta.pop(sec, None)
                _jq_log.info("[尾盘卖出] %s 跌破前低", sec)
                continue
        except Exception as e:
            _jq_log.error("[尾盘卖出] %s %s", sec, e)

    if t1_skip:
        _jq_log.info("[尾盘] T+1 当日建仓跳过卖出 %d 只", len(t1_skip))


if __name__ == "__main__":
    pass
