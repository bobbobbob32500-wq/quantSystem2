# -*- coding: utf-8 -*-
"""
分时回测引擎
"""

from typing import Dict, Optional
from datetime import datetime
from .intraday_data_handler import IntradayDataHandler
from .signal_engine import SignalEngine
from .execution_engine import ExecutionEngine
from .portfolio import Portfolio
from .metrics import compute_metrics, print_metrics
from .config import BacktestConfig
from src.core.logger import get_logger

logger = get_logger("intraday_backtest_engine")


class IntradayBacktestEngine:
    """分时回测引擎"""
    
    def __init__(self, config: Optional[BacktestConfig] = None):
        """初始化"""
        self.config = config or BacktestConfig()
        
        # 核心组件
        self.data_handler: Optional[IntradayDataHandler] = None
        self.signal_engine: Optional[SignalEngine] = None
        self.execution_engine: Optional[ExecutionEngine] = None
        self.portfolio: Optional[Portfolio] = None
        
        # 回测结果
        self.results: Optional[Dict] = None
    
    def run(self, 
            daily_data_dict: Dict[str, any],
            minute_data_dict: Dict[str, any],
            start_date: Optional[str] = None,
            end_date: Optional[str] = None,
            show_progress: bool = True) -> Dict:
        """
        运行分时回测
        
        Args:
            daily_data_dict: 日线数据 {symbol: DataFrame}
            minute_data_dict: 分钟数据 {symbol: DataFrame}
            start_date: 开始日期
            end_date: 结束日期
            show_progress: 是否显示进度
        
        Returns:
            回测结果
        """
        logger.info("="*70)
        logger.info("开始分时回测")
        logger.info("="*70)
        
        # 初始化组件
        self._init_components(daily_data_dict, minute_data_dict, start_date, end_date)
        
        # 主循环
        self._run_main_loop(show_progress)
        
        # 计算结果
        self._calculate_results()
        
        logger.info("="*70)
        logger.info("分时回测完成")
        logger.info("="*70)
        
        return self.results
    
    def _init_components(self,
                        daily_data_dict: Dict[str, any],
                        minute_data_dict: Dict[str, any],
                        start_date: Optional[str],
                        end_date: Optional[str]) -> None:
        """初始化组件"""
        logger.info("初始化分时回测组件...")
        
        # 分时数据驱动
        self.data_handler = IntradayDataHandler(
            daily_data_dict, 
            minute_data_dict, 
            start_date, 
            end_date
        )
        
        # 信号引擎
        self.signal_engine = SignalEngine(self.config)
        
        # 执行引擎
        self.execution_engine = ExecutionEngine(self.config)
        
        # 组合管理
        self.portfolio = Portfolio(self.config)
        
        logger.info(f"初始资金: {self.config.initial_capital:,.2f}")
        logger.info(f"最大持仓: {self.config.max_positions}只")
        logger.info(f"单只仓位: {self.config.position_size*100:.0f}%")
    
    def _run_main_loop(self, show_progress: bool) -> None:
        """运行主循环"""
        logger.info("开始分时回测主循环...")
        
        date_count = 0
        total_dates = len(self.data_handler.dates)
        
        # 遍历每个交易日
        while True:
            # 获取下一个交易日
            current_date = self.data_handler.get_next_date()
            
            if current_date is None:
                break
            
            date_count += 1
            date_str = current_date.strftime('%Y-%m-%d')
            
            # 显示进度
            if show_progress and date_count % 5 == 0:
                progress = date_count / total_dates * 100
                logger.info(f"进度: {progress:.1f}% ({date_count}/{total_dates}) - {date_str}")
            
            # 1. 获取日线数据（用于选股）
            daily_bars = self.data_handler.get_daily_bars(current_date)
            
            if not daily_bars:
                continue
            
            # 2. 更新日线数据窗口
            self.signal_engine.update_data(daily_bars)
            
            # 3. 遍历当日分钟数据
            self._process_intraday_data(current_date, date_str)
            
            # 4. 记录当日净值
            self.portfolio.record_equity(current_date, date_str)
        
        logger.info(f"分时回测完成，共处理 {date_count} 个交易日")
    
    def _process_intraday_data(self, current_date: datetime, date_str: str) -> None:
        """处理日内数据"""
        # 获取当日所有分钟数据
        minute_bars = self.data_handler.get_minute_bars(current_date)
        
        if not minute_bars:
            return
        
        # 按时间分组
        time_groups = {}
        for bar in minute_bars:
            time_key = bar['time']
            if time_key not in time_groups:
                time_groups[time_key] = []
            time_groups[time_key].append(bar)
        
        # 遍历每个时间点
        for time_key, bars in time_groups.items():
            # 1. 更新持仓价格
            price_dict = {bar['symbol']: bar['close'] for bar in bars}
            self.portfolio.update_positions(price_dict)
            
            # 2. 风控检查
            self.execution_engine.check_risk_control(bars, self.portfolio, date_str)
            
            # 3. 计算信号
            signals = {}
            for bar in bars:
                symbol = bar['symbol']
                position_exists = self.portfolio.has_position(symbol)
                signal = self.signal_engine.generate_signal(symbol, position_exists)
                if signal:
                    signals[symbol] = signal
            
            # 4. 执行交易
            self.execution_engine.execute(bars, signals, self.portfolio, date_str)
            
            # 5. 更新组合
            self.portfolio.update_total_value()
    
    def _calculate_results(self) -> None:
        """计算结果"""
        logger.info("计算回测结果...")
        
        # 获取基础结果
        results = self.portfolio.get_results()
        
        # 计算绩效指标
        metrics = compute_metrics(
            results['equity_curve'],
            results['trade_history']
        )
        
        # 合并结果
        self.results = {
            **results,
            **metrics,
        }
    
    def print_results(self) -> None:
        """打印结果"""
        if not self.results:
            logger.warning("没有回测结果")
            return
        
        # 打印绩效指标
        print_metrics(self.results)
        
        # 打印交易统计
        self._print_trade_statistics()
    
    def _print_trade_statistics(self) -> None:
        """打印交易统计"""
        trade_history = self.results.get('trade_history', [])
        
        if not trade_history:
            return
        
        print("\n" + "="*70)
        print("交易统计")
        print("="*70)
        
        # 按信号类型统计
        buy_signals = {}
        sell_signals = {}
        
        for trade in trade_history:
            if trade['action'] == 'buy':
                signal_type = trade.get('signal_type', '未知')
                buy_signals[signal_type] = buy_signals.get(signal_type, 0) + 1
            else:
                signal_type = trade.get('signal_type', '未知')
                sell_signals[signal_type] = sell_signals.get(signal_type, 0) + 1
        
        print("\n买入信号统计:")
        for signal_type, count in buy_signals.items():
            print(f"  {signal_type}: {count}次")
        
        print("\n卖出信号统计:")
        for signal_type, count in sell_signals.items():
            print(f"  {signal_type}: {count}次")
        
        print("="*70)
    
    def get_results(self) -> Optional[Dict]:
        """获取结果"""
        return self.results
