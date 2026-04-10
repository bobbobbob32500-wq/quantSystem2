# -*- coding: utf-8 -*-
"""
获取最近一个月推荐股票并下载分时数据
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import tushare as ts
from src.modules.backtest.history_recommendation_db import HistoryRecommendationDB
from src.core.logger import get_logger
from src.core.config import ConfigManager

logger = get_logger("fetch_recent_recommendations")


class RecentRecommendationFetcher:
    """最近推荐股票获取器"""
    
    def __init__(self, token: Optional[str] = None):
        """初始化"""
        if token:
            ts.set_token(token)
        
        self.pro = ts.pro_api()
        self.config = ConfigManager()
        self.db = HistoryRecommendationDB()
    
    def fetch_recent_month_recommendations(self) -> list:
        """
        获取最近一个月的推荐股票
        
        Returns:
            推荐股票列表
        """
        logger.info("="*70)
        logger.info("获取最近一个月的推荐股票")
        logger.info("="*70)
        
        # 计算日期范围
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)
        
        logger.info(f"日期范围: {start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}")
        
        # 模拟推荐股票（实际应该从选股系统获取）
        # 这里使用一些示例股票
        mock_recommendations = [
            {
                'symbol': '000001',
                'name': '平安银行',
                'recommendation_date': (end_date - timedelta(days=5)).strftime('%Y-%m-%d'),
                'recommendation_reason': '回踩均线买入',
                'recommendation_score': 85,
                'strategy_type': 'Pullback',
                'status': 'active',
            },
            {
                'symbol': '000002',
                'name': '万科A',
                'recommendation_date': (end_date - timedelta(days=10)).strftime('%Y-%m-%d'),
                'recommendation_reason': '突破买入',
                'recommendation_score': 78,
                'strategy_type': 'Momentum',
                'status': 'active',
            },
            {
                'symbol': '600000',
                'name': '浦发银行',
                'recommendation_date': (end_date - timedelta(days=15)).strftime('%Y-%m-%d'),
                'recommendation_reason': '量价齐升',
                'recommendation_score': 72,
                'strategy_type': 'Momentum',
                'status': 'active',
            },
        ]
        
        logger.info(f"找到 {len(mock_recommendations)} 只推荐股票")
        
        return mock_recommendations
    
    def download_intraday_data_for_recommendations(self, 
                                                   recommendations: list,
                                                   days_before: int = 5,
                                                   days_after: int = 10) -> None:
        """
        为推荐股票下载分时数据
        
        Args:
            recommendations: 推荐股票列表
            days_before: 推荐前天数
            days_after: 推荐后天数
        """
        logger.info("="*70)
        logger.info("下载分时数据")
        logger.info("="*70)
        
        for i, rec in enumerate(recommendations, 1):
            symbol = rec['symbol']
            rec_date = rec['recommendation_date']
            
            logger.info(f"\n[{i}/{len(recommendations)}] {symbol} - {rec.get('name', '')}")
            logger.info(f"  推荐日期: {rec_date}")
            
            # 计算数据范围
            rec_dt = datetime.strptime(rec_date, '%Y-%m-%d')
            start_date = (rec_dt - timedelta(days=days_before)).strftime('%Y-%m-%d')
            end_date = (rec_dt + timedelta(days=days_after)).strftime('%Y-%m-%d')
            
            logger.info(f"  数据范围: {start_date} ~ {end_date}")
            
            # 下载分时数据
            intraday_df = self._download_intraday_data(symbol, start_date, end_date)
            
            if not intraday_df.empty:
                # 保存到数据库
                self.db.add_intraday_data(symbol, intraday_df)
                logger.info(f"  [OK] 分时数据已保存: {len(intraday_df)}条")
            else:
                logger.warning(f"  [WARN] 无分时数据")
            
            # 保存推荐记录
            self.db.add_recommendation(rec)
    
    def _download_intraday_data(self, 
                               symbol: str,
                               start_date: str,
                               end_date: str) -> pd.DataFrame:
        """下载分时数据"""
        try:
            # 转换股票代码格式
            ts_code = f"{symbol}.SH" if symbol.startswith('6') else f"{symbol}.SZ"
            
            # 转换日期格式
            start_dt = start_date.replace('-', '') + '093000'
            end_dt = end_date.replace('-', '') + '150000'
            
            # 获取分时数据
            df = self.pro.query('stk_mins',
                               ts_code=ts_code,
                               start_date=start_dt,
                               end_date=end_dt,
                               freq='1min')
            
            if df.empty:
                return pd.DataFrame()
            
            # 处理数据
            df = df.rename(columns={
                'trade_time': 'trade_time',
                'open': 'open',
                'high': 'high',
                'low': 'low',
                'close': 'close',
                'vol': 'volume',
                'amount': 'amount',
            })
            
            df['trade_time'] = pd.to_datetime(df['trade_time'])
            df['trade_date'] = df['trade_time'].dt.date
            df['symbol'] = symbol
            
            df = df.sort_values('trade_time').reset_index(drop=True)
            
            return df
            
        except Exception as e:
            logger.error(f"下载分时数据失败 {symbol}: {e}")
            return pd.DataFrame()
    
    def run(self) -> None:
        """运行完整流程"""
        print("\n" + "="*70)
        print("获取最近一个月推荐股票并下载分时数据")
        print("="*70)
        
        # 1. 获取推荐股票
        recommendations = self.fetch_recent_month_recommendations()
        
        # 2. 下载分时数据
        self.download_intraday_data_for_recommendations(recommendations)
        
        # 3. 打印统计
        self.db.print_statistics()
        
        print("\n" + "="*70)
        print("[OK] 完成")
        print("="*70)


def main():
    """主函数"""
    try:
        # 从配置获取token
        config = ConfigManager()
        token = config.get('tushare_token')
        
        if not token:
            print("\n[ERROR] 未配置Tushare token")
            print("请在config.yaml中配置tushare_token")
            return
        
        # 运行
        fetcher = RecentRecommendationFetcher(token)
        fetcher.run()
        
    except Exception as e:
        print(f"\n[FAIL] 执行失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
