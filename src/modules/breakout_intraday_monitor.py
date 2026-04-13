# -*- coding: utf-8 -*-
"""
盘中突破监控模块

核心功能：
  1. 接收盘前选股观察池（WatchList），盘中实时监控突破确认
  2. 当个股价格突破 pivot + buffer 且量能达标时，发出买入信号
  3. 对已持仓的股票，实时检查走弱条件（MA5跌破、止损触发）

数据来源：
  - 盘中实时行情通过轮询方式获取（预留接口，支持多种数据源）
  - 默认使用 Tushare 实时行情（免费额度有限，也可接入其他源）

使用方式：
  monitor = BreakoutIntradayMonitor(strategy, watch_items)
  monitor.start()  # 阻塞式运行，Ctrl+C停止
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Callable

import pandas as pd

from src.core.logger import get_logger
from src.modules.breakout_strategy import (
    BreakoutStrategy,
    BreakoutParams,
    WatchItem,
    BreakoutSignal,
    build_breakout_strategy_from_config,
)

logger = get_logger("breakout_intraday_monitor")


@dataclass
class MonitorState:
    """监控状态"""
    is_running: bool = False
    start_time: Optional[datetime] = None
    check_count: int = 0
    confirmed_signals: List[BreakoutSignal] = field(default_factory=list)
    # 已确认的股票代码（防止重复触发）
    confirmed_codes: set = field(default_factory=set)


class BreakoutIntradayMonitor:
    """
    盘中突破监控

    典型用法：
        strategy = BreakoutStrategy(db, params)
        watch_items = strategy.run(end_date="20240315")
        monitor = BreakoutIntradayMonitor(strategy, watch_items)
        monitor.start()
    """

    def __init__(
        self,
        strategy: BreakoutStrategy,
        watch_items: List[WatchItem],
        quote_fetcher: Optional[Callable] = None,
        poll_interval: int = 15,
        signal_callback: Optional[Callable[[BreakoutSignal], None]] = None,
    ):
        """
        Args:
            strategy: 策略实例（用于调用 confirm_breakout_realtime）
            watch_items: 盘前选出的观察池
            quote_fetcher: 实时行情获取函数，签名 (codes: List[str]) -> Dict[str, Dict]
                           返回 {ts_code: {"price", "high", "open", "vol", "vol_ma20", "time"}}
                           若为 None 则使用默认的模拟/Tushare行情
            poll_interval: 轮询间隔（秒），默认15秒
            signal_callback: 信号触发时的回调函数（用于推送消息等）
        """
        self.strategy = strategy
        self.watch_items = watch_items
        self.quote_fetcher = quote_fetcher or self._default_quote_fetcher
        self.poll_interval = poll_interval
        self.signal_callback = signal_callback
        self.state = MonitorState()

        # 预构建 vol_ma20 查找表（从策略数据库中获取历史均量）
        self._vol_ma20_cache: Dict[str, float] = {}
        self._preload_vol_ma20()

    def _preload_vol_ma20(self):
        """从数据库预加载20日均量，供实时行情补充"""
        try:
            codes = [item.ts_code for item in self.watch_items]
            if not codes:
                return
            placeholders = ",".join(["?"] * len(codes))
            sql = f"""
                SELECT ts_code, AVG(vol) as vol_ma20
                FROM (
                    SELECT ts_code, vol,
                           ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) as rn
                    FROM stock_daily
                    WHERE ts_code IN ({placeholders})
                )
                WHERE rn <= 20
                GROUP BY ts_code
            """
            rows = self.strategy.db.query(sql, tuple(codes))
            if rows:
                for r in rows:
                    self._vol_ma20_cache[str(r["ts_code"])] = float(r["vol_ma20"])
        except Exception as e:
            logger.warning("预加载20日均量失败: %s", e)

    def _default_quote_fetcher(self, codes: List[str]) -> Dict[str, Dict]:
        """
        默认行情获取器（使用 Tushare 实时行情）

        在非交易时段返回空字典（不产生信号）
        """
        now = datetime.now()
        hour, minute = now.hour, now.minute
        current_hm = hour * 100 + minute

        # 非交易时段直接返回空
        if current_hm < 925 or (1132 < current_hm < 1258) or current_hm > 1502:
            return {}

        try:
            import tushare as ts
            # ts.realtime_quote 获取实时行情
            from src.modules.realtime_quote_fetcher import RealtimeQuoteFetcher
            fetcher = RealtimeQuoteFetcher()
            df = fetcher.get_realtime_quotes_batch([str(code).split(".", 1)[0] for code in codes], batch_size=50)
            if df is None or df.empty:
                return {}

            result = {}
            for _, row in df.iterrows():
                code = str(row.get("TS_CODE", row.get("ts_code", row.get("symbol", ""))))
                if not code:
                    continue
                normalized_code = str(code).split(".", 1)[0].zfill(6)
                ts_code = f"{normalized_code}.SH" if normalized_code.startswith("6") else f"{normalized_code}.SZ"
                vol_ma20 = self._vol_ma20_cache.get(ts_code, self._vol_ma20_cache.get(normalized_code, 0))
                result[ts_code] = {
                    "price": float(row.get("PRICE", row.get("price", 0))),
                    "high": float(row.get("HIGH", row.get("high", 0))),
                    "open": float(row.get("OPEN", row.get("open", 0))),
                    "vol": float(row.get("VOL", row.get("vol", row.get("volume", 0)))),
                    "vol_ma20": vol_ma20,
                    "time": str(row.get("TIME", row.get("time", ""))),
                }
            return result
        except ImportError:
            logger.warning("未安装 tushare，无法获取实时行情")
            return {}
        except Exception as e:
            logger.warning("获取实时行情失败: %s", e)
            return {}

    def start(self):
        """
        启动盘中监控（阻塞式，Ctrl+C 停止）

        交易时段内每隔 poll_interval 秒轮询一次：
          1. 获取观察池所有股票的实时行情
          2. 调用 strategy.confirm_breakout_realtime 检测突破
          3. 新确认的信号立即打印+回调
          4. 已确认的股票不再重复触发
        """
        self.state.is_running = True
        self.state.start_time = datetime.now()
        pending_items = [
            item for item in self.watch_items
            if item.ts_code not in self.state.confirmed_codes
        ]

        print(f"\n{'═' * 60}")
        print(f"  盘中突破监控已启动")
        print(f"  观察池: {len(self.watch_items)} 只")
        print(f"  轮询间隔: {self.poll_interval} 秒")
        print(f"  突破缓冲: {self.strategy.params.breakout_buffer:.1%}")
        print(f"  放量倍数: ≥{self.strategy.params.volume_confirm_ratio:.1f}")
        print(f"  按 Ctrl+C 停止")
        print(f"{'═' * 60}")

        self._print_watch_summary()

        try:
            while self.state.is_running:
                now = datetime.now()
                hm = now.hour * 100 + now.minute

                # 收盘后自动停止
                if hm > 1505:
                    print(f"\n  [{now.strftime('%H:%M:%S')}] 已收盘，监控自动停止")
                    break

                # 非交易时段等待
                if hm < 925 or (1132 < hm < 1258):
                    status = "午休等待中..." if hm > 1132 else "等待开盘..."
                    print(f"  [{now.strftime('%H:%M:%S')}] {status}", end="\r")
                    time.sleep(30)
                    continue

                # 过滤掉已确认的股票
                pending_items = [
                    item for item in self.watch_items
                    if item.ts_code not in self.state.confirmed_codes
                ]
                if not pending_items:
                    print(f"\n  [{now.strftime('%H:%M:%S')}] 所有观察池股票已确认，监控结束")
                    break

                # 获取实时行情
                codes = [item.ts_code for item in pending_items]
                quotes = self.quote_fetcher(codes)
                self.state.check_count += 1

                if not quotes:
                    time.sleep(self.poll_interval)
                    continue

                # 突破确认
                new_signals = self.strategy.confirm_breakout_realtime(
                    pending_items, quotes
                )

                for sig in new_signals:
                    if sig.ts_code not in self.state.confirmed_codes:
                        self.state.confirmed_codes.add(sig.ts_code)
                        self.state.confirmed_signals.append(sig)
                        self._print_signal(sig)
                        if self.signal_callback:
                            try:
                                self.signal_callback(sig)
                            except Exception as e:
                                logger.warning("信号回调失败: %s", e)

                # 状态栏
                confirmed = len(self.state.confirmed_signals)
                remaining = len(pending_items) - len(new_signals)
                print(f"  [{now.strftime('%H:%M:%S')}] "
                      f"第{self.state.check_count}次检查 | "
                      f"已确认{confirmed}只 | 待监控{remaining}只",
                      end="\r")

                time.sleep(self.poll_interval)

        except KeyboardInterrupt:
            print(f"\n\n  用户中断，监控已停止")

        self.state.is_running = False
        self._print_summary()

    def stop(self):
        """停止监控"""
        self.state.is_running = False

    def get_confirmed_signals(self) -> List[BreakoutSignal]:
        """获取已确认的所有交易信号"""
        return self.state.confirmed_signals

    def _print_watch_summary(self):
        """打印观察池摘要"""
        print(f"\n  观察池股票：")
        print(f"  {'序号':>4}  {'代码':>12}  {'名称':<8}  {'收盘':>7}  "
              f"{'触发价':>7}  {'止损':>7}  {'评分':>6}")
        print(f"  {'─' * 65}")
        for i, item in enumerate(self.watch_items, 1):
            print(f"  {i:>4}  {item.ts_code:>12}  {item.name:<8}  "
                  f"{item.close:>7.2f}  {item.trigger_price:>7.2f}  "
                  f"{item.stop_loss:>7.2f}  {item.signal_score:>6.1f}")
        print()

    def _print_signal(self, sig: BreakoutSignal):
        """打印突破确认信号"""
        grade_tag = {"A": "★ A级信号（放量突破）", "B": "☆ B级信号（正常量突破）"}
        tag = grade_tag.get(sig.signal_grade, sig.confirm_type)
        print(f"\n  {'━' * 50}")
        print(f"  {tag}")
        print(f"  {'━' * 50}")
        print(f"  代码: {sig.ts_code}  {sig.name}")
        print(f"  入场价: {sig.entry_price:.2f}  (pivot={sig.pivot:.2f})")
        print(f"  止损价: {sig.stop_loss:.2f}  "
              f"(风险R={abs(sig.entry_price - sig.stop_loss) / sig.entry_price * 100:.2f}%)")
        print(f"  量比: {sig.volume_ratio:.2f}x")
        print(f"  综合评分: {sig.signal_score:.1f}")
        print(f"  行业: {sig.industry}")
        print(f"  建议仓位比例: {sig.position_ratio:.0%}")
        pos_size = BreakoutStrategy.calc_position_size(
            equity=100000, entry_price=sig.entry_price,
            stop_loss=sig.stop_loss
        )
        actual_size = int(pos_size * sig.position_ratio // 100) * 100
        print(f"  建议股数: {actual_size}股（基于10万账户，{sig.signal_grade}级仓位）")
        print(f"  {'━' * 50}\n")

    def _print_summary(self):
        """打印监控总结"""
        print(f"\n{'═' * 60}")
        print(f"  监控总结")
        print(f"{'═' * 60}")
        if self.state.start_time:
            elapsed = (datetime.now() - self.state.start_time).total_seconds()
            print(f"  运行时间: {elapsed / 60:.1f} 分钟")
        print(f"  检查次数: {self.state.check_count}")
        print(f"  确认信号: {len(self.state.confirmed_signals)} 只")

        if self.state.confirmed_signals:
            print(f"\n  确认信号列表：")
            bv = [s for s in self.state.confirmed_signals if s.confirm_type == "breakout+volume"]
            bo = [s for s in self.state.confirmed_signals if s.confirm_type == "breakout"]
            print(f"  突破+放量确认: {len(bv)} 只")
            print(f"  仅突破确认:    {len(bo)} 只")
            for sig in self.state.confirmed_signals:
                tag = "★" if sig.confirm_type == "breakout+volume" else "☆"
                print(f"    {tag} {sig.ts_code} {sig.name}  "
                      f"入场{sig.entry_price:.2f}  量比{sig.volume_ratio:.1f}x  "
                      f"评分{sig.signal_score:.1f}")

        not_confirmed = [
            item for item in self.watch_items
            if item.ts_code not in self.state.confirmed_codes
        ]
        if not_confirmed:
            print(f"\n  未触发突破: {len(not_confirmed)} 只")
            for item in not_confirmed:
                print(f"    {item.ts_code} {item.name}  "
                      f"收盘{item.close:.2f}  触发价{item.trigger_price:.2f}  "
                      f"距离{(item.trigger_price / item.close - 1) * 100:.2f}%")

        print(f"{'═' * 60}")


# ═══════════════════════════════════════════════════════════════
# 菜单入口
# ═══════════════════════════════════════════════════════════════

def breakout_monitor_menu(
    strategy: BreakoutStrategy = None,
    watch_items: List[WatchItem] = None,
    db=None, config=None,
):
    """
    盘中突破监控菜单

    可独立使用（先运行盘前选股再启动监控），
    也可从 breakout_selector_menu 中传入已选好的观察池
    """
    from src.core.config import ConfigManager
    from src.core.database import DatabaseManager

    if config is None:
        config = ConfigManager()
    if db is None:
        db = DatabaseManager(config)
    if strategy is None:
        strategy = build_breakout_strategy_from_config(db, config)

    while True:
        print(f"\n{'═' * 60}")
        print(f"  盘中突破监控系统")
        print(f"{'═' * 60}")
        if watch_items:
            print(f"  当前观察池: {len(watch_items)} 只")
        else:
            print(f"  当前观察池: 空（需要先运行盘前选股）")
        print(f"  1. 运行盘前选股（生成今日观察池）")
        print(f"  2. 启动盘中监控")
        print(f"  3. 查看观察池详情")
        print(f"  4. 调整监控参数")
        print(f"  5. 模拟测试（使用历史数据模拟盘中突破）")
        print(f"  0. 返回")
        print(f"{'─' * 60}")

        choice = input("  请选择: ").strip()

        if choice == "1":
            print("\n  正在执行盘前选股...", flush=True)
            try:
                watch_items = strategy.run()
                if watch_items:
                    print(f"\n  选出 {len(watch_items)} 只股票进入观察池")
                    for i, item in enumerate(watch_items, 1):
                        print(f"  {i:>3}. {item.ts_code} {item.name}  "
                              f"触发价={item.trigger_price:.2f}  评分={item.signal_score:.1f}")
                else:
                    print("  今日无符合条件的股票")
            except Exception as e:
                print(f"  选股失败: {e}")

        elif choice == "2":
            if not watch_items:
                print("  请先运行盘前选股（选项1）")
                continue
            interval = input(f"  轮询间隔（秒，默认15）: ").strip()
            interval = int(interval) if interval.isdigit() else 15
            monitor = BreakoutIntradayMonitor(
                strategy=strategy,
                watch_items=watch_items,
                poll_interval=interval,
            )
            monitor.start()

        elif choice == "3":
            if not watch_items:
                print("  观察池为空")
                continue
            for i, item in enumerate(watch_items, 1):
                r_pct = abs(item.trigger_price - item.stop_loss) / item.trigger_price * 100
                print(f"\n  [{i}] {item.ts_code} {item.name}")
                print(f"      收盘={item.close:.2f}  pivot={item.pivot:.2f}  "
                      f"触发价={item.trigger_price:.2f}")
                print(f"      止损={item.stop_loss:.2f}（风险{r_pct:.2f}%）  "
                      f"RS分位={item.rs20_xsec_q:.2%}")
                print(f"      评分={item.signal_score:.1f}  {item.score_detail}")

        elif choice == "4":
            p = strategy.params
            print(f"\n  当前突破确认参数：")
            print(f"    突破缓冲: {p.breakout_buffer:.1%}")
            print(f"    最大追高: {p.breakout_max_chase:.1%}")
            print(f"    放量倍数: ≥{p.volume_confirm_ratio:.1f}")
            print(f"    涨幅上限: {p.max_intraday_gain:.0%}")
            print(f"    最大持仓: {p.max_hold_days} 天")
            adjust = input("\n  是否调整？(y/n): ").strip().lower()
            if adjust == "y":
                v = input(f"    放量倍数 [{p.volume_confirm_ratio}]: ").strip()
                if v:
                    p.volume_confirm_ratio = float(v)
                v = input(f"    突破缓冲 [{p.breakout_buffer}]: ").strip()
                if v:
                    p.breakout_buffer = float(v)
                v = input(f"    最大追高 [{p.breakout_max_chase}]: ").strip()
                if v:
                    p.breakout_max_chase = float(v)
                print("  参数已更新")

        elif choice == "5":
            if not watch_items:
                print("  请先运行盘前选股（选项1）")
                continue
            print("\n  模拟测试：使用数据库最新交易日的日线数据模拟盘中突破...")
            try:
                latest_date = db.query(
                    "SELECT MAX(trade_date) as d FROM stock_daily"
                )[0]["d"]
                codes = [item.ts_code for item in watch_items]
                placeholders = ",".join(["?"] * len(codes))
                rows = db.query(
                    f"SELECT ts_code, open, high, low, close, vol FROM stock_daily "
                    f"WHERE trade_date = ? AND ts_code IN ({placeholders})",
                    (latest_date, *codes)
                )
                if not rows:
                    print("  无法获取行情数据")
                    continue

                confirm_data = {}
                for r in rows:
                    code = str(r["ts_code"])
                    vol_ma20_val = 0
                    vm_rows = db.query(
                        "SELECT AVG(vol) as vm FROM ("
                        "  SELECT vol FROM stock_daily WHERE ts_code=? "
                        "  ORDER BY trade_date DESC LIMIT 20"
                        ")", (code,)
                    )
                    if vm_rows and vm_rows[0]["vm"]:
                        vol_ma20_val = float(vm_rows[0]["vm"])
                    confirm_data[code] = {
                        "price": float(r["close"]),
                        "high": float(r["high"]),
                        "open": float(r["open"]),
                        "vol": float(r["vol"]),
                        "vol_ma20": vol_ma20_val,
                        "time": "10:00:00",
                    }

                signals = strategy.confirm_breakout_realtime(
                    watch_items, confirm_data
                )
                if signals:
                    print(f"\n  模拟确认 {len(signals)} 只：")
                    for sig in signals:
                        tag = "★" if sig.confirm_type == "breakout+volume" else "☆"
                        print(f"    {tag} {sig.ts_code} {sig.name}  "
                              f"入场={sig.entry_price:.2f}  量比={sig.volume_ratio:.1f}x")
                else:
                    print("  无股票触发突破确认")

            except Exception as e:
                print(f"  模拟失败: {e}")

        elif choice == "0":
            break
