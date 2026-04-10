# -*- coding: utf-8 -*-
"""
下载指定月份的推荐股票数据
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

logger = get_logger("download_month_data")


class MonthDataDownloader:
    """指定月份数据下载器"""
    
    def __init__(self, token: Optional[str] = None):
        """初始化"""
        if token:
            ts.set_token(token)
        
        self.pro = ts.pro_api()
        self.config = ConfigManager()
        self.db = HistoryRecommendationDB()
    
    def download_month_data(self, year: int, month: int) -> None:
        """
        下载指定月份的数据
        
        Args:
            year: 年份
            month: 月份
        """
        logger.info("="*70)
        logger.info(f"下载 {year}年{month}月 推荐股票数据")
        logger.info("="*70)
        
        # 计算日期范围
        start_date = datetime(year, month, 1)
        if month == 12:
            end_date = datetime(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = datetime(year, month + 1, 1) - timedelta(days=1)
        
        logger.info(f"日期范围: {start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}")
        
        # 生成模拟推荐股票（实际应该从选股系统获取）
        recommendations = self._generate_mock_recommendations(start_date, end_date)
        
        logger.info(f"生成 {len(recommendations)} 只推荐股票")
        
        # 下载分时数据
        self._download_intraday_data_for_recommendations(recommendations)
        
        # 打印统计
        self.db.print_statistics()
    
    def _generate_mock_recommendations(self, start_date: datetime, end_date: datetime) -> list:
        """
        生成模拟推荐股票
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            推荐股票列表
        """
        # 模拟推荐股票列表
        # 实际应该从选股系统或数据库获取
        mock_stocks = [
            {'symbol': '000001', 'name': '平安银行', 'reason': '回踩均线买入', 'score': 85, 'strategy': 'Pullback'},
            {'symbol': '000002', 'name': '万科A', 'reason': '突破买入', 'score': 78, 'strategy': 'Momentum'},
            {'symbol': '600000', 'name': '浦发银行', 'reason': '量价齐升', 'score': 72, 'strategy': 'Momentum'},
            {'symbol': '600036', 'name': '招商银行', 'reason': '回踩支撑', 'score': 80, 'strategy': 'Pullback'},
            {'symbol': '601318', 'name': '中国平安', 'reason': '趋势向上', 'score': 75, 'strategy': 'Momentum'},
        ]
        
        recommendations = []
        
        # 在每个月内生成多个推荐日期
        current_date = start_date
        while current_date <= end_date:
            # 每周推荐2-3只股票
            if current_date.weekday() == 0:  # 周一
                for i, stock in enumerate(mock_stocks[:3]):
                    rec = {
                        'symbol': stock['symbol'],
                        'name': stock['name'],
                        'recommendation_date': current_date.strftime('%Y-%m-%d'),
                        'recommendation_reason': stock['reason'],
                        'recommendation_score': stock['score'],
                        'strategy_type': stock['strategy'],
                        'status': 'active',
                    }
                    recommendations.append(rec)
            
            current_date += timedelta(days=1)
        
        return recommendations
    
    def _download_intraday_data_for_recommendations(self, recommendations: list) -> None:
        """
        为推荐股票下载分时数据
        
        Args:
            recommendations: 推荐股票列表
        """
        logger.info("="*70)
        logger.info("下载分时数据")
        logger.info("="*70)
        
        # 按股票分组，避免重复下载
        symbol_data = {}
        for rec in recommendations:
            symbol = rec['symbol']
            rec_date = rec['recommendation_date']
            
            if symbol not in symbol_data:
                symbol_data[symbol] = {
                    'name': rec['name'],
                    'dates': [],
                }
            
            symbol_data[symbol]['dates'].append(rec_date)
        
        # 下载每个股票的分时数据
        for i, (symbol, data) in enumerate(symbol_data.items(), 1):
            name = data['name']
            dates = data['dates']
            
            logger.info(f"\n[{i}/{len(symbol_data)}] {symbol} - {name}")
            logger.info(f"  推荐次数: {len(dates)}")
            
            # 计算数据范围
            min_date = min(dates)
            max_date = max(dates)
            
            start_dt = datetime.strptime(min_date, '%Y-%m-%d') - timedelta(days=5)
            end_dt = datetime.strptime(max_date, '%Y-%m-%d') + timedelta(days=10)
            
            start_date = start_dt.strftime('%Y-%m-%d')
            end_date = end_dt.strftime('%Y-%m-%d')
            
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
        logger.info("\n保存推荐记录...")
        for rec in recommendations:
            self.db.add_recommendation(rec)
        
        logger.info(f"[OK] 推荐记录已保存: {len(recommendations)}条")
    
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
            
            logger.info(f"  正在下载 {ts_code} 分时数据...")
            
            # 尝试获取真实数据
            try:
                df = self.pro.query('stk_mins',
                                   ts_code=ts_code,
                                   start_date=start_dt,
                                   end_date=end_dt,
                                   freq='1min')
                
                if not df.empty:
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
                    
                    logger.info(f"  下载成功: {len(df)}条")
                    
                    return df
            except Exception as e:
                logger.warning(f"  真实数据下载失败: {e}")
            
            # 使用模拟数据
            logger.info(f"  使用模拟数据...")
            return self._generate_mock_intraday_data(symbol, start_date, end_date)
            
        except Exception as e:
            logger.error(f"下载失败 {symbol}: {e}")
            return pd.DataFrame()
    
    def _generate_mock_intraday_data(self, 
                                    symbol: str,
                                    start_date: str,
                                    end_date: str) -> pd.DataFrame:
        """生成模拟分时数据"""
        # 生成日期范围
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        
        # 生成所有交易日的分时数据
        all_data = []
        current_dt = start_dt
        
        while current_dt <= end_dt:
            # 跳过周末
            if current_dt.weekday() >= 5:
                current_dt += timedelta(days=1)
                continue
            
            # 生成当天的分时数据
            day_data = self._generate_one_day_intraday(symbol, current_dt)
            all_data.append(day_data)
            
            current_dt += timedelta(days=1)
        
        if not all_data:
            return pd.DataFrame()
        
        df = pd.concat(all_data, ignore_index=True)
        logger.info(f"  生成模拟数据: {len(df)}条")
        
        return df
    
    def _generate_one_day_intraday(self, symbol: str, date: datetime) -> pd.DataFrame:
        """生成一天的分时数据"""
        # 生成时间序列
        morning_times = pd.date_range(
            start=date.replace(hour=9, minute=30, second=0),
            end=date.replace(hour=11, minute=30, second=0),
            freq='1min'
        )
        
        afternoon_times = pd.date_range(
            start=date.replace(hour=13, minute=0, second=0),
            end=date.replace(hour=15, minute=0, second=0),
            freq='1min'
        )
        
        times = morning_times.append(afternoon_times)
        
        # 生成价格数据
        base_price = 10.0 + hash(symbol) % 10  # 根据股票代码生成基础价格
        prices = [base_price * (1 + np.random.normal(0, 0.005)) for _ in times]
        
        df = pd.DataFrame({
            'trade_time': times,
            'trade_date': [date.date()] * len(times),
            'open': prices,
            'high': [p * (1 + abs(np.random.normal(0, 0.002))) for p in prices],
            'low': [p * (1 - abs(np.random.normal(0, 0.002))) for p in prices],
            'close': prices,
            'volume': [100000 * (1 + np.random.normal(0, 0.3)) for _ in prices],
            'amount': [p * 100000 for p in prices],
            'symbol': symbol,
        })
        
        return df


def main():
    """主函数"""
    print("\n" + "="*70)
    print("下载2026年2月份推荐股票数据")
    print("="*70)
    
    try:
        # 从配置获取token
        config = ConfigManager()
        token = config.get('tushare_token')
        
        if not token:
            print("\n[ERROR] 未配置Tushare token")
            print("请在config.yaml中配置tushare_token")
            print("\n使用模拟数据进行测试...")
            
            # 使用模拟数据测试
            downloader = MonthDataDownloader()
            downloader.download_month_data(2026, 2)
            
            return
        
        # 运行
        downloader = MonthDataDownloader(token)
        downloader.download_month_data(2026, 2)
        
        print("\n" + "="*70)
        print("[OK] 完成")
        print("="*70)
        
    except Exception as e:
        print(f"\n[FAIL] 执行失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
