# -*- coding: utf-8 -*-
"""
批量获取历史推荐股票脚本
功能：获取过去30天的推荐股票名单
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict
from src.core.logger import get_logger
from src.modules.stock_selector import StockSelector
from src.modules.backtest.history_recommendation_db import HistoryRecommendationDB

logger = get_logger("batch_stock_selection")


def get_trading_days(days: int = 30) -> List[str]:
    """获取过去N天的交易日列表"""
    try:
        import baostock as bs
        
        lg = bs.login()
        if lg.error_code != '0':
            return _generate_trading_days_fallback(days)
        
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=days * 2)).strftime('%Y-%m-%d')
        
        rs = bs.query_trade_dates(start_date, end_date)
        
        if rs.error_code != '0':
            bs.logout()
            return _generate_trading_days_fallback(days)
        
        trading_days = []
        while rs.next():
            row = rs.get_row_data()
            if row[1] == '1':
                trading_days.append(row[0])
        
        bs.logout()
        
        trading_days = trading_days[-days:] if len(trading_days) > days else trading_days
        
        return trading_days
        
    except Exception as e:
        logger.warning(f"获取交易日历失败: {e}")
        return _generate_trading_days_fallback(days)


def _generate_trading_days_fallback(days: int) -> List[str]:
    """备用方法生成交易日（排除周末）"""
    trading_days = []
    current = datetime.now()
    count = 0
    
    while count < days:
        if current.weekday() < 5:
            trading_days.append(current.strftime('%Y-%m-%d'))
            count += 1
        current -= timedelta(days=1)
    
    return list(reversed(trading_days))


def run_batch_selection(days: int = 30) -> Dict[str, int]:
    """
    批量执行选股
    
    Args:
        days: 获取过去多少天的推荐
    
    Returns:
        统计结果 {date: stock_count}
    """
    logger.info("=" * 70)
    logger.info(f"开始批量获取过去 {days} 天的推荐股票")
    logger.info("=" * 70)
    
    trading_days = get_trading_days(days)
    
    if not trading_days:
        logger.error("无法获取交易日列表")
        return {}
    
    logger.info(f"获取到 {len(trading_days)} 个交易日")
    logger.info(f"日期范围: {trading_days[0]} ~ {trading_days[-1]}")
    
    selector = StockSelector()
    db = HistoryRecommendationDB()
    
    stats = {}
    
    for i, trade_date in enumerate(trading_days, 1):
        logger.info(f"\n[{i}/{len(trading_days)}] 处理日期: {trade_date}")
        
        try:
            end_date = trade_date.replace('-', '')
            
            results = selector.run_selection(end_date=end_date)
            
            if results:
                for stock in results:
                    recommendation = {
                        'symbol': stock['ts_code'],
                        'name': stock['name'],
                        'recommendation_date': trade_date,
                        'recommendation_score': stock['total_score'],
                        'recommendation_reason': stock.get('level', ''),
                        'strategy_type': stock.get('industry', ''),
                    }
                    db.add_recommendation(recommendation)
                
                stats[trade_date] = len(results)
                logger.info(f"  保存 {len(results)} 只推荐股票")
            else:
                stats[trade_date] = 0
                logger.warning(f"  无推荐结果")
                
        except Exception as e:
            logger.error(f"  处理失败: {e}")
            stats[trade_date] = 0
    
    logger.info("\n" + "=" * 70)
    logger.info("批量选股完成")
    logger.info("=" * 70)
    
    total_stocks = sum(stats.values())
    success_days = sum(1 for v in stats.values() if v > 0)
    
    logger.info(f"\n【统计】")
    logger.info(f"  总交易日: {len(trading_days)}")
    logger.info(f"  成功天数: {success_days}")
    logger.info(f"  总推荐数: {total_stocks}")
    
    if success_days > 0:
        avg_stocks = total_stocks / success_days
        logger.info(f"  平均每天: {avg_stocks:.1f} 只")
    
    return stats


if __name__ == "__main__":
    run_batch_selection(days=30)
