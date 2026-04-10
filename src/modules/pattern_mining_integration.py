# -*- coding: utf-8 -*-
"""
Pattern Mining集成示例
展示如何将Pattern Mining集成到现有回测系统中
"""

import pandas as pd
from datetime import datetime
from typing import Dict, List

from src.core.logger import get_logger
from src.modules.strategy_backtest import StrategyBacktester
from src.modules.unified_pattern_mining import UnifiedPatternMining

logger = get_logger("pattern_mining_integration")


class PatternMiningIntegration:
    """Pattern Mining集成类"""
    
    def __init__(self, db=None):
        """
        初始化集成类
        
        Args:
            db: 数据库管理器
        """
        self.backtester = StrategyBacktester(db)
        self.pattern_miner = UnifiedPatternMining()
        
        logger.info("Pattern Mining集成初始化完成")
    
    def backtest_with_pattern_mining(self, 
                                    signal_types: List[str] = None,
                                    start_date: str = None,
                                    end_date: str = None) -> Dict:
        """
        回测 + Pattern Mining
        
        Args:
            signal_types: 信号类型列表
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            结果字典
        """
        if signal_types is None:
            signal_types = ['pullback', 'breakout', 'consolidation']
        
        logger.info("=" * 80)
        logger.info("开始回测 + Pattern Mining...")
        logger.info("=" * 80)
        
        # Step 1: 回测各策略
        backtest_results = {}
        all_trades = []
        
        for signal_type in signal_types:
            logger.info(f"\n回测 {signal_type} 策略...")
            
            result = self.backtester.backtest_strategy(
                signal_type=signal_type,
                start_date=start_date,
                end_date=end_date
            )
            
            backtest_results[signal_type] = result
            
            # 收集交易记录
            trades = self._extract_trades_from_backtest(result)
            all_trades.extend(trades)
        
        # Step 2: 生成回测对比报告
        comparison_report = self.backtester.generate_comparison_report(backtest_results)
        
        # Step 3: Pattern Mining
        logger.info(f"\n对 {len(all_trades)} 条交易记录进行Pattern Mining...")
        
        pattern_results = self.pattern_miner.run_all_methods(all_trades)
        pattern_report = self.pattern_miner.generate_unified_report(pattern_results)
        
        # Step 4: 导出最佳Pattern
        best_patterns = self.pattern_miner.export_best_patterns(pattern_results, top_n=10)
        
        # Step 5: 生成综合报告
        final_report = self._generate_final_report(
            comparison_report, 
            pattern_report, 
            best_patterns
        )
        
        return {
            'backtest_results': backtest_results,
            'pattern_results': pattern_results,
            'best_patterns': best_patterns,
            'final_report': final_report,
        }
    
    def _extract_trades_from_backtest(self, result) -> List[Dict]:
        """
        从回测结果提取交易记录
        
        Args:
            result: 回测结果
        
        Returns:
            交易记录列表
        """
        # 这里需要根据实际的BacktestResult结构提取交易记录
        # 简化示例：返回空列表
        return []
    
    def _generate_final_report(self, 
                              comparison_report: str,
                              pattern_report: str,
                              best_patterns: List[Dict]) -> str:
        """
        生成最终综合报告
        
        Args:
            comparison_report: 回测对比报告
            pattern_report: Pattern Mining报告
            best_patterns: 最佳Pattern列表
        
        Returns:
            最终报告
        """
        lines = [
            "=" * 120,
            "量化交易系统综合分析报告",
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 120,
            "",
            "【第一部分：策略回测对比】",
            "-" * 120,
            comparison_report,
            "",
            "【第二部分：Pattern Mining分析】",
            "-" * 120,
            pattern_report,
            "",
            "【第三部分：最佳Pattern汇总】",
            "-" * 120,
        ]
        
        if best_patterns:
            for i, pattern in enumerate(best_patterns, 1):
                lines.extend([
                    f"{i}. [{pattern['method']}] {pattern['conditions']}",
                    f"   胜率: {pattern['win_rate']*100:.1f}%, 期望收益: {pattern['expected_return']:.3f}%, 样本: {pattern['sample_size']}",
                    "",
                ])
        else:
            lines.append("未发现有效的赚钱Pattern")
        
        lines.extend([
            "",
            "【第四部分：行动建议】",
            "-" * 120,
            "1. 根据回测对比报告选择主策略",
            "2. 根据Pattern Mining结果优化买入条件",
            "3. 应用禁止交易条件过滤信号",
            "4. 持续监控策略表现，定期重新分析",
            "",
            "=" * 120,
        ])
        
        return "\n".join(lines)
    
    def apply_pattern_filters(self, 
                             signal: Dict,
                             forbidden_patterns: List[Dict]) -> bool:
        """
        应用Pattern过滤
        
        Args:
            signal: 信号字典
            forbidden_patterns: 禁止交易Pattern列表
        
        Returns:
            是否允许交易
        """
        for pattern in forbidden_patterns:
            conditions = pattern.get('conditions', {})
            
            # 检查是否满足禁止条件
            match = True
            for key, val in conditions.items():
                if key in signal:
                    # 简化匹配逻辑
                    if signal[key] != val:
                        match = False
                        break
            
            if match:
                logger.info(f"信号被禁止交易Pattern过滤: {conditions}")
                return False
        
        return True


def demo_pattern_mining():
    """Pattern Mining演示函数"""
    
    # 模拟交易数据
    trades = [
        {'pnl': 2.5, 'signal_type': 'breakout', 'rsi': 55, 'pullback': 8, 'volume_ratio': 2.0, 'entry_date': '2026-03-01 10:30:00'},
        {'pnl': 1.8, 'signal_type': 'breakout', 'rsi': 52, 'pullback': 10, 'volume_ratio': 1.8, 'entry_date': '2026-03-02 11:00:00'},
        {'pnl': -1.2, 'signal_type': 'pullback', 'rsi': 62, 'pullback': 5, 'volume_ratio': 1.5, 'entry_date': '2026-03-03 10:00:00'},
        {'pnl': 3.2, 'signal_type': 'breakout', 'rsi': 58, 'pullback': 12, 'volume_ratio': 2.2, 'entry_date': '2026-03-04 14:00:00'},
        {'pnl': -0.8, 'signal_type': 'breakout', 'rsi': 68, 'pullback': 6, 'volume_ratio': 1.2, 'entry_date': '2026-03-05 09:30:00'},
        {'pnl': 1.5, 'signal_type': 'pullback', 'rsi': 56, 'pullback': 7, 'volume_ratio': 1.6, 'entry_date': '2026-03-06 13:00:00'},
        {'pnl': 2.8, 'signal_type': 'breakout', 'rsi': 54, 'pullback': 9, 'volume_ratio': 2.1, 'entry_date': '2026-03-07 10:30:00'},
        {'pnl': -2.1, 'signal_type': 'breakout', 'rsi': 70, 'pullback': 4, 'volume_ratio': 1.0, 'entry_date': '2026-03-08 09:00:00'},
        {'pnl': 1.2, 'signal_type': 'pullback', 'rsi': 58, 'pullback': 8, 'volume_ratio': 1.7, 'entry_date': '2026-03-09 11:30:00'},
        {'pnl': 2.0, 'signal_type': 'breakout', 'rsi': 56, 'pullback': 11, 'volume_ratio': 1.9, 'entry_date': '2026-03-10 14:30:00'},
    ]
    
    # 运行Pattern Mining
    from src.modules.unified_pattern_mining import run_unified_pattern_mining
    
    report = run_unified_pattern_mining(trades, top_n=5)
    print(report)
    
    return report


if __name__ == "__main__":
    demo_pattern_mining()
