# -*- coding: utf-8 -*-
"""
回测引擎
"""

from typing import Dict, Optional
from datetime import datetime
from .data_handler import DataHandler
from .signal_engine import SignalEngine
from .execution_engine import ExecutionEngine
from .portfolio import Portfolio
from .metrics import compute_metrics, print_metrics
from .config import BacktestConfig
from src.core.logger import get_logger

logger = get_logger("backtest_engine")


class BacktestEngine:
    """回测引擎"""
    
    def __init__(self, config: Optional[BacktestConfig] = None):
        """初始化"""
        self.config = config or BacktestConfig()
        
        # 核心组件
        self.data_handler: Optional[DataHandler] = None
        self.signal_engine: Optional[SignalEngine] = None
        self.execution_engine: Optional[ExecutionEngine] = None
        self.portfolio: Optional[Portfolio] = None
        
        # 回测结果
        self.results: Optional[Dict] = None
    
    def run(self, 
            data_dict: Dict[str, any],
            start_date: Optional[str] = None,
            end_date: Optional[str] = None,
            show_progress: bool = True) -> Dict:
        """
        运行回测
        
        Args:
            data_dict: 数据字典 {symbol: DataFrame}
            start_date: 开始日期
            end_date: 结束日期
            show_progress: 是否显示进度
        
        Returns:
            回测结果
        """
        logger.info("="*70)
        logger.info("开始回测")
        logger.info("="*70)
        
        # 初始化组件
        self._init_components(data_dict, start_date, end_date)
        
        # 主循环
        self._run_main_loop(show_progress)
        
        # 计算结果
        self._calculate_results()
        
        logger.info("="*70)
        logger.info("回测完成")
        logger.info("="*70)
        
        return self.results
    
    def _init_components(self, 
                        data_dict: Dict[str, any],
                        start_date: Optional[str],
                        end_date: Optional[str]) -> None:
        """初始化组件"""
        logger.info("初始化回测组件...")
        
        # 数据驱动
        self.data_handler = DataHandler(data_dict, start_date, end_date)
        
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
        logger.info("开始回测主循环...")
        
        bar_count = 0
        total_bars = self.data_handler.total_bars
        
        while True:
            # 获取下一个bar
            bars = self.data_handler.get_next_bar()
            
            if bars is None:
                break
            
            bar_count += 1
            
            # 获取当前日期
            current_date = bars[0]['date']
            current_time = bars[0]['timestamp']
            
            # 显示进度
            if show_progress and bar_count % 10 == 0:
                progress = bar_count / total_bars * 100
                logger.info(f"进度: {progress:.1f}% ({bar_count}/{total_bars})")
            
            # 1. 更新数据窗口
            self.signal_engine.update_data(bars)
            
            # 2. 更新持仓价格
            price_dict = {bar['symbol']: bar['close'] for bar in bars}
            self.portfolio.update_positions(price_dict)
            
            # 3. 风控检查（盘前）
            self.execution_engine.check_risk_control(bars, self.portfolio, current_date)
            
            # 4. 计算信号
            signals = {}
            for bar in bars:
                symbol = bar['symbol']
                position_exists = self.portfolio.has_position(symbol)
                signal = self.signal_engine.generate_signal(symbol, position_exists)
                if signal:
                    signals[symbol] = signal
            
            # 5. 执行交易
            self.execution_engine.execute(bars, signals, self.portfolio, current_date)
            
            # 6. 更新组合
            self.portfolio.update_total_value()
            
            # 7. 记录净值
            self.portfolio.record_equity(current_time, current_date)
        
        logger.info(f"回测完成，共处理 {bar_count} 个交易日")
    
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
    
    def _log_trade_statistics(self) -> None:
        """记录交易统计"""
        trade_history = self.results.get('trade_history', [])
        
        if not trade_history:
            return
        
        logger.info("=" * 70)
        logger.info("交易统计")
        logger.info("=" * 70)
        
        buy_signals = {}
        sell_signals = {}
        
        for trade in trade_history:
            if trade['action'] == 'buy':
                signal_type = trade.get('signal_type', '未知')
                buy_signals[signal_type] = buy_signals.get(signal_type, 0) + 1
            else:
                signal_type = trade.get('signal_type', '未知')
                sell_signals[signal_type] = sell_signals.get(signal_type, 0) + 1
        
        logger.info("买入信号统计:")
        for signal_type, count in buy_signals.items():
            logger.info(f"  {signal_type}: {count}次")
        
        logger.info("卖出信号统计:")
        for signal_type, count in sell_signals.items():
            logger.info(f"  {signal_type}: {count}次")
        
        logger.info("=" * 70)
    
    def _print_trade_statistics(self) -> None:
        """打印交易统计（保留用于命令行输出）"""
        self._log_trade_statistics()
    
    def get_results(self) -> Optional[Dict]:
        """获取结果"""
        return self.results
    
    def get_equity_curve(self) -> list:
        """获取净值曲线"""
        if not self.results:
            return []
        return self.results.get('equity_curve', [])
    
    def get_trade_history(self) -> list:
        """获取交易历史"""
        if not self.results:
            return []
        return self.results.get('trade_history', [])
