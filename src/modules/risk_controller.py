# -*- coding: utf-8 -*-
"""
风控检测模块
实现多维度风控信号检测逻辑
集成自动优化系统
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from src.core.logger import get_logger
from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.core.exceptions import RiskControlException

# 导入自动优化系统
try:
    from src.modules.fully_automatic_system import FullyAutomaticOptimizationSystem
    AUTO_OPTIMIZATION_AVAILABLE = True
except ImportError as e:
    get_logger("risk_control").warning(f"自动优化系统导入失败: {e}")
    AUTO_OPTIMIZATION_AVAILABLE = False

logger = get_logger("risk_control")


class RiskController:
    """风控控制器（集成自动优化）"""
    
    def __init__(self, config: ConfigManager = None, db: DatabaseManager = None,
                 enable_auto_optimization: bool = False):
        """
        初始化风控控制器
        
        Args:
            config: 配置管理器
            db: 数据库管理器
            enable_auto_optimization: 是否启用自动优化
        """
        if config is None:
            config = ConfigManager()
        if db is None:
            db = DatabaseManager(config)
        
        self.config = config
        self.db = db
        
        # 加载风控参数
        self.volume_high_ratio = config.get("risk_control.volume_high_ratio", 0.92)
        self.volume_high_days = config.get("risk_control.volume_high_days", 120)
        self.market_bad_threshold = config.get("risk_control.market_bad_threshold", 48.0)
        self.profit_low_threshold = config.get("risk_control.profit_low_threshold", 5.0)
        self.profit_high_threshold = config.get("risk_control.profit_high_threshold", 15.0)
        self.market_weak_threshold = config.get("risk_control.market_weak_threshold", 45.0)
        
        # ========== 新增：自动优化系统 ==========
        self.enable_auto_optimization = enable_auto_optimization and AUTO_OPTIMIZATION_AVAILABLE
        self.auto_optimizer = None
        
        if self.enable_auto_optimization:
            self._init_auto_optimization()
        
        logger.info(f"风控控制器初始化完成（自动优化:{self.enable_auto_optimization}）")
    
    def _init_auto_optimization(self):
        """初始化自动优化系统"""
        try:
            self.auto_optimizer = FullyAutomaticOptimizationSystem(
                scheduled_interval_minutes=60,
                consecutive_loss_threshold=3,
                drawdown_threshold=0.10
            )
            logger.info("风控自动优化系统初始化成功")
        except Exception as e:
            logger.error(f"风控自动优化系统初始化失败: {e}")
            self.enable_auto_optimization = False
            self.auto_optimizer = None
    
    def trigger_emergency_reoptimization(self, reason: str = "risk_signal"):
        """
        触发紧急重优化
        
        Args:
            reason: 触发原因
        """
        if not self.enable_auto_optimization or not self.auto_optimizer:
            logger.warning("自动优化未启用，无法触发紧急重优化")
            return False
        
        try:
            # 强制重优化
            result = self.auto_optimizer.force_reoptimize()
            
            if result:
                logger.warning(f"风控触发紧急重优化: {reason}")
                return True
            else:
                return False
        except Exception as e:
            logger.error(f"触发紧急重优化失败: {e}")
            return False
    
    def get_stock_daily_data(self, ts_code: str, days: int = 150) -> pd.DataFrame:
        """
        获取个股日线数据
        
        Args:
            ts_code: 股票代码
            days: 获取天数
        
        Returns:
            日线数据DataFrame
        """
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
        
        sql = """
            SELECT trade_date, open, close, high, low, vol, amount, pct_chg
            FROM stock_daily
            WHERE ts_code = ? AND trade_date >= ? AND trade_date <= ?
            ORDER BY trade_date DESC
        """
        
        results = self.db.query(sql, (ts_code, start_date, end_date))
        
        if not results:
            return pd.DataFrame()
        
        df = pd.DataFrame(results)
        # 处理日期格式
        try:
            if len(str(df['trade_date'].iloc[0])) == 8:
                df['trade_date'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')
            else:
                df['trade_date'] = pd.to_datetime(df['trade_date'])
        except:
            df['trade_date'] = pd.to_datetime(df['trade_date'])
        df = df.sort_values('trade_date').reset_index(drop=True)
        
        if len(df) > days:
            df = df.tail(days)
        
        return df
    
    def check_volume_sell_signal(self, df: pd.DataFrame) -> Optional[Dict]:
        """
        检测天量卖出信号
        
        条件: 当日成交量 >= 120日高位成交量 × 92%
        
        Args:
            df: 日线数据
        
        Returns:
            信号字典或None
        """
        if df.empty or len(df) < self.volume_high_days:
            return None
        
        # 获取当日成交量
        today_vol = df['vol'].iloc[-1]
        
        # 计算120日高位成交量
        vol_high = df['vol'].tail(self.volume_high_days).max()
        
        # 判断是否触发信号
        threshold = vol_high * self.volume_high_ratio
        
        if today_vol >= threshold:
            return {
                "signal_type": "天量卖出",
                "trigger": True,
                "reason": f"当日成交量{round(today_vol/10000, 0)}万手 >= 120日高位{round(vol_high/10000, 0)}万手 × {self.volume_high_ratio}",
                "suggestion": "立即卖出",
                "severity": "高"
            }
        
        return None
    
    def check_market_bad_clear_signal(self, market_score: float, profit: float) -> Optional[Dict]:
        """
        检测极差市场清仓信号
        
        条件: 市场评分 < 48分 且 个股盈利 <= 5%
        
        Args:
            market_score: 市场评分
            profit: 个股盈亏比例
        
        Returns:
            信号字典或None
        """
        if market_score < self.market_bad_threshold and profit <= self.profit_low_threshold:
            return {
                "signal_type": "极差市场清仓",
                "trigger": True,
                "reason": f"市场评分{market_score}分 < {self.market_bad_threshold}分，个股盈利{profit}% <= {self.profit_low_threshold}%",
                "suggestion": "立即清仓",
                "severity": "高"
            }
        
        return None
    
    def check_price_profit_signal(self, current_price: float, target_profit: float,
                                   highest_price: float = None,
                                   entry_price: float = None) -> Optional[Dict]:
        """
        检测价格止盈信号 - 优化版：分层跟踪止盈
        
        条件: 
        1. 固定止盈：现价 >= 目标止盈价
        2. 分层跟踪止盈：
           - 盈利<5%：不启动跟踪止盈
           - 盈利5-10%：回撤3%止盈
           - 盈利>10%：回撤5%止盈
        
        Args:
            current_price: 当前价格
            target_profit: 目标止盈价
            highest_price: 持仓期间最高价（用于跟踪止盈）
            entry_price: 买入价（用于计算盈利比例）
        
        Returns:
            信号字典或None
        """
        # 分层跟踪止盈（优化版）
        if highest_price is not None and highest_price > 0 and entry_price is not None and entry_price > 0:
            # 计算当前盈利比例
            profit_pct = (current_price - entry_price) / entry_price * 100
            
            # 分层回撤阈值
            if profit_pct < 5:
                # 盈利<5%：不启动跟踪止盈
                trailing_stop = None
            elif 5 <= profit_pct < 10:
                # 盈利5-10%：回撤3%止盈
                trailing_stop = highest_price * 0.97
            else:
                # 盈利>10%：回撤5%止盈
                trailing_stop = highest_price * 0.95
            
            # 检查是否触发跟踪止盈
            if trailing_stop and current_price < trailing_stop:
                return {
                    "signal_type": "跟踪止盈",
                    "trigger": True,
                    "reason": f"盈利{profit_pct:.1f}%，现价{current_price:.2f}元 < 最高价{highest_price:.2f}元 × {0.97 if profit_pct < 10 else 0.95:.2f}（回撤{3 if profit_pct < 10 else 5}%）",
                    "suggestion": "跟踪止盈，锁定利润",
                    "severity": "中"
                }
        
        # 固定止盈（兜底）
        if target_profit is not None and target_profit > 0:
            if current_price >= target_profit:
                return {
                    "signal_type": "价格止盈",
                    "trigger": True,
                    "reason": f"现价{current_price:.2f}元 >= 目标止盈价{target_profit:.2f}元",
                    "suggestion": "立即止盈",
                    "severity": "中"
                }
        
        return None
    
    def check_trend_profit_signal(self, profit: float, market_score: float) -> Optional[Dict]:
        """
        检测趋势止盈信号
        
        条件: 个股盈利 > 15% 且 市场转弱
        
        Args:
            profit: 个股盈亏比例
            market_score: 市场评分
        
        Returns:
            信号字典或None
        """
        if profit > self.profit_high_threshold and market_score < self.market_weak_threshold:
            return {
                "signal_type": "趋势止盈",
                "trigger": True,
                "reason": f"个股盈利{profit}% > {self.profit_high_threshold}%，市场评分{market_score}分 < {self.market_weak_threshold}分",
                "suggestion": "密切关注，分批止盈",
                "severity": "中"
            }
        
        return None
    
    def check_price_stop_signal(self, current_price: float, target_stop: float,
                                ma10: float = None,
                                recent_prices: list = None) -> Optional[Dict]:
        """
        检测价格止损信号 - 优化版：动态止损 + 瞬时止损
        
        条件: 
        1. 瞬时止损：3分钟跌幅 > 2%（新增）
        2. 动态止损：现价 < max(目标止损价, MA10)
        3. 固定止损：现价 <= 目标止损价
        
        Args:
            current_price: 当前价格
            target_stop: 目标止损价
            ma10: 10日均线（用于动态止损）
            recent_prices: 最近3分钟价格列表（用于瞬时止损）
        
        Returns:
            信号字典或None
        """
        # 瞬时止损（新增：快速下跌立即止损）
        if recent_prices is not None and len(recent_prices) >= 3:
            price_3min_ago = recent_prices[0]
            if price_3min_ago > 0:
                drop_pct = (price_3min_ago - current_price) / price_3min_ago * 100
                if drop_pct > 2.0:  # 3分钟跌幅>2%
                    return {
                        "signal_type": "瞬时止损",
                        "trigger": True,
                        "reason": f"3分钟跌幅{drop_pct:.2f}% > 2%，快速下跌",
                        "suggestion": "立即止损",
                        "severity": "高"
                    }
        
        # 动态止损（优先级次高）
        if ma10 is not None and ma10 > 0:
            # 止损价取目标止损价和MA10的较大值
            dynamic_stop = max(target_stop if target_stop else 0, ma10)
            if current_price < dynamic_stop:
                return {
                    "signal_type": "动态止损",
                    "trigger": True,
                    "reason": f"现价{current_price:.2f}元 < 动态止损价{dynamic_stop:.2f}元（max(目标止损, MA10)）",
                    "suggestion": "立即止损",
                    "severity": "高"
                }
        
        # 固定止损（兜底）
        if target_stop is not None and target_stop > 0:
            if current_price <= target_stop:
                return {
                    "signal_type": "价格止损",
                    "trigger": True,
                    "reason": f"现价{current_price:.2f}元 <= 目标止损价{target_stop:.2f}元",
                    "suggestion": "立即止损",
                    "severity": "高"
                }
        
        return None
    
    def check_all_signals(self, ts_code: str, name: str, 
                         current_price: float, hold_price: float,
                         target_profit: float = None, target_stop: float = None,
                         market_score: float = 50.0) -> List[Dict]:
        """
        执行全部风控检测
        
        Args:
            ts_code: 股票代码
            name: 股票名称
            current_price: 当前价格
            hold_price: 持仓成本
            target_profit: 目标止盈价
            target_stop: 目标止损价
            market_score: 市场评分
        
        Returns:
            触发的信号列表
        """
        signals = []
        
        # 计算盈亏比例
        profit = round((current_price - hold_price) / hold_price * 100, 2) if hold_price > 0 else 0
        
        # 获取日线数据
        df = self.get_stock_daily_data(ts_code, days=150)
        
        # 1. 天量卖出信号
        signal = self.check_volume_sell_signal(df)
        if signal:
            signals.append(signal)
        
        # 2. 极差市场清仓信号
        signal = self.check_market_bad_clear_signal(market_score, profit)
        if signal:
            signals.append(signal)
        
        # 3. 价格止盈信号
        signal = self.check_price_profit_signal(current_price, target_profit)
        if signal:
            signals.append(signal)
        
        # 4. 趋势止盈信号
        signal = self.check_trend_profit_signal(profit, market_score)
        if signal:
            signals.append(signal)
        
        # 5. 价格止损信号
        signal = self.check_price_stop_signal(current_price, target_stop)
        if signal:
            signals.append(signal)
        
        # 为每个信号添加股票信息
        for signal in signals:
            signal['ts_code'] = ts_code
            signal['name'] = name
            signal['current_price'] = current_price
            signal['profit'] = profit
            signal['trigger_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        return signals
    
    def save_signal(self, signal: Dict) -> bool:
        """
        保存信号到数据库
        
        Args:
            signal: 信号信息
        
        Returns:
            是否成功
        """
        try:
            sql = """
                INSERT INTO signal_history (ts_code, name, signal_type, signal_time, trigger_reason, suggestion, push_status)
                VALUES (?, ?, ?, ?, ?, ?, 0)
            """
            
            self.db.execute(sql, (
                signal['ts_code'],
                signal['name'],
                signal['signal_type'],
                signal['trigger_time'],
                signal['reason'],
                signal['suggestion']
            ))
            
            logger.info(f"信号已保存: {signal['ts_code']} - {signal['signal_type']}")
            return True
        except Exception as e:
            logger.error(f"保存信号失败: {e}")
            return False
    
    def run_risk_check(self, hold_list: List[Dict], market_score: float = 50.0) -> Dict:
        """
        执行风控检测
        
        Args:
            hold_list: 持仓列表
            market_score: 市场评分
        
        Returns:
            检测结果
        """
        logger.info("=" * 50)
        logger.info("开始执行风控检测...")
        logger.info("=" * 50)
        
        all_signals = []
        check_results = []
        
        for hold in hold_list:
            ts_code = hold['ts_code']
            name = hold['name']
            hold_price = hold['hold_price']
            target_profit = hold.get('target_profit')
            target_stop = hold.get('target_stop')
            
            # 获取最新价格
            sql = """
                SELECT close FROM stock_daily
                WHERE ts_code = ?
                ORDER BY trade_date DESC
                LIMIT 1
            """
            result = self.db.query_one(sql, (ts_code,))
            
            if not result:
                logger.warning(f"无法获取{ts_code}的最新价格")
                continue
            
            current_price = result['close']
            
            # 执行风控检测
            signals = self.check_all_signals(
                ts_code, name, current_price, hold_price,
                target_profit, target_stop, market_score
            )
            
            # 保存触发的信号
            for signal in signals:
                self.save_signal(signal)
                all_signals.append(signal)
            
            check_results.append({
                "ts_code": ts_code,
                "name": name,
                "current_price": current_price,
                "hold_price": hold_price,
                "profit": round((current_price - hold_price) / hold_price * 100, 2) if hold_price > 0 else 0,
                "signal_count": len(signals),
                "signals": signals
            })
        
        # 按信号数量排序
        check_results.sort(key=lambda x: x['signal_count'], reverse=True)
        
        logger.info("=" * 50)
        logger.info(f"风控检测完成，共检测{len(hold_list)}只持仓")
        logger.info(f"触发信号{len(all_signals)}个")
        for signal in all_signals:
            logger.warning(f"  [{signal['severity']}] {signal['ts_code']} {signal['name']}: {signal['signal_type']} - {signal['suggestion']}")
        logger.info("=" * 50)
        
        return {
            "check_count": len(hold_list),
            "signal_count": len(all_signals),
            "signals": all_signals,
            "check_results": check_results,
            "check_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    
    def generate_report(self, result: Dict) -> str:
        """
        生成风控检测报告
        
        Args:
            result: 检测结果
        
        Returns:
            报告文本
        """
        report_lines = [
            "=" * 60,
            "风控检测报告",
            f"检测时间: {result['check_time']}",
            "=" * 60,
            "",
            f"检测持仓数: {result['check_count']}只",
            f"触发信号数: {result['signal_count']}个",
            ""
        ]
        
        if not result['signals']:
            report_lines.append("无风控信号触发，持仓状态正常")
            return "\n".join(report_lines)
        
        report_lines.append("-" * 60)
        report_lines.append("触发的信号:")
        report_lines.append("")
        
        for i, signal in enumerate(result['signals'], 1):
            report_lines.extend([
                f"【{i}】{signal['ts_code']} {signal['name']}",
                f"    信号类型: {signal['signal_type']} ({signal['severity']}风险)",
                f"    触发原因: {signal['reason']}",
                f"    操作建议: {signal['suggestion']}",
                f"    当前价格: {signal['current_price']}元",
                f"    当前盈亏: {signal['profit']}%",
                ""
            ])
        
        report_lines.extend([
            "-" * 60,
            "请及时处理触发的风控信号！",
            "=" * 60
        ])
        
        return "\n".join(report_lines)


def risk_signal_trigger(stock_data: Dict, market_score: float) -> List[Dict]:
    """
    风控信号触发核心逻辑（按设计文档算法实现）
    
    Args:
        stock_data: 个股数据（字典），包含成交量、现价、盈亏、止盈价、止损价等
        market_score: 市场综合评分
    
    Returns:
        触发的信号列表
    """
    signal_list = []
    
    # 1. 天量卖出信号
    if stock_data.get("vol_today") and stock_data.get("vol_120d_high"):
        if stock_data["vol_today"] >= stock_data["vol_120d_high"] * 0.92:
            signal = {
                "type": "天量卖出",
                "reason": f"当日成交量{stock_data['vol_today']}>=120日高位{stock_data['vol_120d_high']}×92%",
                "suggestion": "立即卖出"
            }
            signal_list.append(signal)
    
    # 2. 极差市场清仓信号
    if market_score < 48.0 and stock_data.get("profit", 0) <= 5.0:
        signal = {
            "type": "极差市场清仓",
            "reason": f"市场评分{market_score}<48分，个股盈利{stock_data.get('profit', 0)}%<=5%",
            "suggestion": "立即清仓"
        }
        signal_list.append(signal)
    
    # 3. 价格止盈信号
    if stock_data.get("current_price") and stock_data.get("target_profit"):
        if stock_data["current_price"] >= stock_data["target_profit"]:
            signal = {
                "type": "价格止盈",
                "reason": f"现价{stock_data['current_price']}>=目标止盈价{stock_data['target_profit']}",
                "suggestion": "立即止盈"
            }
            signal_list.append(signal)
    
    # 4. 趋势止盈信号
    if stock_data.get("profit", 0) > 15.0 and market_score < 45.0:
        signal = {
            "type": "趋势止盈",
            "reason": f"个股盈利{stock_data['profit']}%>15%，市场转弱",
            "suggestion": "密切关注，分批止盈"
        }
        signal_list.append(signal)
    
    # 5. 价格止损信号
    if stock_data.get("current_price") and stock_data.get("target_stop"):
        if stock_data["current_price"] <= stock_data["target_stop"]:
            signal = {
                "type": "价格止损",
                "reason": f"现价{stock_data['current_price']}<=目标止损价{stock_data['target_stop']}",
                "suggestion": "立即止损"
            }
            signal_list.append(signal)
    
    return signal_list
