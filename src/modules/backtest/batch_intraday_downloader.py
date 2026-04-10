# -*- coding: utf-8 -*-
"""
历史推荐股票分时数据批量下载器
流程：
1. 调用选股模块获取推荐股票（按日期由近到远）
2. 将股票名单保存到文件
3. 根据名单下载分时数据（5分钟K线）
4. 存储到数据库
"""

import pandas as pd
import numpy as np
import json
import os
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from src.core.logger import get_logger
from src.core.config import ConfigManager
from src.modules.backtest.history_recommendation_db import HistoryRecommendationDB
import time

logger = get_logger("batch_intraday_downloader")

RECOMMENDATION_LIST_FILE = "data/recommendation_list.json"


class BatchIntradayDownloader:
    """批量分时数据下载器"""
    
    def __init__(self, db: HistoryRecommendationDB = None):
        """初始化"""
        if db is None:
            db = HistoryRecommendationDB()
        
        self.db = db
        self.config = ConfigManager()
        
        self.bs = None
        self._init_baostock()
    
    def _init_baostock(self):
        """初始化baostock"""
        try:
            import baostock as bs
            lg = bs.login()
            if lg.error_code == '0':
                self.bs = bs
                logger.info("baostock初始化成功")
            else:
                logger.warning(f"baostock登录失败: {lg.error_msg}")
                self.bs = None
        except ImportError:
            logger.warning("baostock未安装，请运行: pip install baostock")
            self.bs = None
    
    def _get_baostock_code(self, symbol: str) -> str:
        """转换股票代码为baostock格式"""
        pure_code = symbol.split('.')[0] if '.' in symbol else symbol
        if symbol.endswith('.SH') or pure_code.startswith('6'):
            return f'sh.{pure_code}'
        else:
            return f'sz.{pure_code}'
    
    def run_stock_selection(self) -> List[Dict]:
        """
        调用选股模块获取推荐股票
        
        Returns:
            推荐股票列表 [{symbol, name, score, industry, recommend_date}, ...]
        """
        logger.info("=" * 70)
        logger.info("步骤1: 调用选股模块获取推荐股票")
        logger.info("=" * 70)
        
        try:
            from src.modules.stock_selector import StockSelector
            
            selector = StockSelector()
            results = selector.run_selection()
            
            if not results:
                logger.warning("选股结果为空")
                return []
            
            recommend_list = []
            today = datetime.now().strftime('%Y-%m-%d')
            
            for stock in results:
                recommend_list.append({
                    'symbol': stock['ts_code'],
                    'name': stock['name'],
                    'score': stock['total_score'],
                    'industry': stock.get('industry', ''),
                    'recommend_date': today
                })
            
            logger.info(f"选股完成，获取 {len(recommend_list)} 只推荐股票")
            
            return recommend_list
            
        except Exception as e:
            logger.error(f"选股失败: {e}")
            return []
    
    def get_historical_recommendations(self) -> List[Dict]:
        """
        从数据库获取历史推荐股票（按日期由近到远排序）
        
        Returns:
            推荐股票列表
        """
        logger.info("从数据库获取历史推荐股票...")
        
        all_recommendations = self.db.get_recommendations()
        
        if not all_recommendations:
            logger.warning("无历史推荐记录")
            return []
        
        df = pd.DataFrame(all_recommendations)
        
        df['recommendation_date'] = pd.to_datetime(df['recommendation_date'])
        
        df = df.sort_values('recommendation_date', ascending=False).reset_index(drop=True)
        
        grouped = df.groupby('symbol').agg({
            'recommendation_date': 'min',
            'name': 'first'
        }).reset_index()
        
        grouped.columns = ['symbol', 'recommend_date', 'name']
        
        grouped['recommend_date'] = grouped['recommend_date'].dt.strftime('%Y-%m-%d')
        
        grouped = grouped.sort_values('recommend_date', ascending=False).reset_index(drop=True)
        
        result = grouped.to_dict('records')
        
        logger.info(f"获取到 {len(result)} 只独立股票（按日期由近到远）")
        
        return result

    def get_unique_recommendations(self) -> List[Dict]:
        """兼容旧接口，返回按股票聚合的历史推荐名单。"""
        recommendations = self.get_historical_recommendations()
        return [
            {
                "symbol": rec.get("symbol"),
                "name": rec.get("name", ""),
                "first_recommend_date": rec.get("recommend_date"),
                "recommend_date": rec.get("recommend_date"),
            }
            for rec in recommendations
        ]
    
    def save_recommendation_list(self, recommendations: List[Dict]) -> str:
        """
        保存推荐股票名单到文件
        
        Args:
            recommendations: 推荐股票列表
        
        Returns:
            保存的文件路径
        """
        os.makedirs(os.path.dirname(RECOMMENDATION_LIST_FILE), exist_ok=True)
        
        data = {
            'generated_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'total_count': len(recommendations),
            'recommendations': recommendations
        }
        
        with open(RECOMMENDATION_LIST_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"推荐股票名单已保存到: {RECOMMENDATION_LIST_FILE}")
        
        return RECOMMENDATION_LIST_FILE
    
    def load_recommendation_list(self) -> List[Dict]:
        """
        从文件加载推荐股票名单
        
        Returns:
            推荐股票列表
        """
        if not os.path.exists(RECOMMENDATION_LIST_FILE):
            logger.warning(f"推荐名单文件不存在: {RECOMMENDATION_LIST_FILE}")
            return []
        
        with open(RECOMMENDATION_LIST_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        recommendations = data.get('recommendations', [])
        logger.info(f"从文件加载 {len(recommendations)} 只推荐股票")
        logger.info(f"名单生成时间: {data.get('generated_time', '未知')}")
        
        return recommendations
    
    def get_trading_days(self, start_date: str, end_date: str) -> List[str]:
        """
        获取交易日历
        
        Args:
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
        
        Returns:
            交易日列表
        """
        if self.bs is None:
            return self._generate_trading_days_fallback(start_date, end_date)
        
        try:
            rs = self.bs.query_trade_dates(start_date, end_date)
            
            if rs.error_code != '0':
                return self._generate_trading_days_fallback(start_date, end_date)
            
            trading_days = []
            while rs.next():
                row = rs.get_row_data()
                if row[1] == '1':
                    trading_days.append(row[0])
            
            return trading_days
            
        except Exception as e:
            logger.warning(f"获取交易日历失败: {e}")
            return self._generate_trading_days_fallback(start_date, end_date)

    def get_next_n_trading_days(self, start_date: str, n: int = 10) -> List[str]:
        """兼容旧接口，返回从 start_date 开始的后续 N 个交易日。"""
        if n <= 0:
            return []

        end_date = (
            datetime.strptime(start_date, '%Y-%m-%d') + timedelta(days=max(n * 3, 10))
        ).strftime('%Y-%m-%d')
        return self.get_trading_days(start_date, end_date)[:n]
    
    def _generate_trading_days_fallback(self, start_date: str, end_date: str) -> List[str]:
        """备用方法生成交易日（排除周末）"""
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')
        
        trading_days = []
        current = start
        while current <= end:
            if current.weekday() < 5:
                trading_days.append(current.strftime('%Y-%m-%d'))
            current += timedelta(days=1)
        
        return trading_days
    
    def download_intraday_data(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        下载指定日期范围的分时数据（5分钟K线）
        
        Args:
            symbol: 股票代码
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
        
        Returns:
            分时数据DataFrame
        """
        if self.bs is None:
            logger.warning(f"baostock未初始化，跳过 {symbol}")
            return pd.DataFrame()
        
        bs_code = self._get_baostock_code(symbol)
        
        try:
            rs = self.bs.query_history_k_data_plus(
                bs_code,
                'date,time,code,open,high,low,close,volume,amount',
                start_date=start_date,
                end_date=end_date,
                frequency='5',
                adjustflag='2'
            )
            
            if rs.error_code != '0':
                logger.warning(f"  查询失败: {rs.error_msg}")
                return pd.DataFrame()
            
            data_list = []
            while rs.next():
                data_list.append(rs.get_row_data())
            
            if not data_list:
                return pd.DataFrame()
            
            df = pd.DataFrame(data_list, columns=rs.fields)
            
            df = self._process_intraday_data(df, symbol)
            
            return df
            
        except Exception as e:
            logger.error(f"  下载失败: {e}")
            return pd.DataFrame()
    
    def _process_intraday_data(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """处理分时数据"""
        result = pd.DataFrame()
        
        result['trade_date'] = df['date']
        
        result['trade_time'] = df['time'].apply(lambda x: self._parse_time(x))
        
        result['symbol'] = symbol
        
        result['open'] = pd.to_numeric(df['open'], errors='coerce')
        result['high'] = pd.to_numeric(df['high'], errors='coerce')
        result['low'] = pd.to_numeric(df['low'], errors='coerce')
        result['close'] = pd.to_numeric(df['close'], errors='coerce')
        result['volume'] = pd.to_numeric(df['volume'], errors='coerce')
        result['amount'] = pd.to_numeric(df['amount'], errors='coerce')
        
        result = result[['symbol', 'trade_time', 'trade_date', 'open', 'high', 'low', 'close', 'volume', 'amount']]
        
        result = result.sort_values('trade_time').reset_index(drop=True)
        
        result = result.dropna(subset=['open', 'close', 'high', 'low'])
        
        return result
    
    def _parse_time(self, time_str: str) -> datetime:
        """解析时间字符串"""
        try:
            if len(time_str) == 17:
                return datetime.strptime(time_str, '%Y%m%d%H%M%S%f')
            elif len(time_str) == 14:
                return datetime.strptime(time_str, '%Y%m%d%H%M%S')
            else:
                return datetime.strptime(time_str[:14], '%Y%m%d%H%M%S')
        except:
            return pd.NaT
    
    def batch_download(self, 
                       recommendations: Optional[List[Dict]] = None,
                       trading_days_count: int = 10,
                       skip_existing: bool = True,
                       show_progress: bool = True) -> Dict[str, int]:
        """
        批量下载推荐股票的分时数据
        
        Args:
            recommendations: 推荐股票列表
            trading_days_count: 下载的交易日数量（从推荐日起）
            skip_existing: 是否跳过已有数据的股票
            show_progress: 是否显示进度
        
        Returns:
            下载统计 {symbol: record_count}
        """
        logger.info("=" * 70)
        logger.info("步骤3: 批量下载分时数据 (数据源: baostock, 频率: 5分钟)")
        logger.info("=" * 70)
        
        if recommendations is None:
            recommendations = self.get_historical_recommendations()

        if not recommendations:
            logger.warning("无推荐股票，退出下载")
            return {}
        
        stats = {}
        total = len(recommendations)
        
        for i, rec in enumerate(recommendations, 1):
            symbol = rec['symbol']
            name = rec.get('name', '')
            recommend_date = rec.get('recommend_date', '')
            
            if show_progress:
                logger.info(f"\n[{i}/{total}] {symbol} ({name})")
                logger.info(f"  推荐日期: {recommend_date}")
            
            if skip_existing:
                existing_data = self.db.get_intraday_data(symbol)
                if not existing_data.empty:
                    existing_dates = existing_data['trade_date'].nunique()
                    if existing_dates >= trading_days_count:
                        logger.info(f"  已有数据: {existing_dates}个交易日，跳过")
                        stats[symbol] = len(existing_data)
                        continue
            
            start_date = recommend_date
            end_date_dt = datetime.strptime(recommend_date, '%Y-%m-%d') + timedelta(days=trading_days_count * 2)
            end_date = end_date_dt.strftime('%Y-%m-%d')
            
            logger.info(f"  目标日期: {start_date} ~ {end_date}")
            
            df = self.download_intraday_data(symbol, start_date, end_date)
            
            if df.empty:
                logger.warning(f"  下载失败: 无数据")
                stats[symbol] = 0
                continue
            
            unique_dates = df['trade_date'].nunique()
            if unique_dates > trading_days_count:
                all_dates = sorted(df['trade_date'].unique())[:trading_days_count]
                df = df[df['trade_date'].isin(all_dates)]
            
            success = self.db.add_intraday_data(symbol, df)
            
            if success:
                logger.info(f"  下载成功: {len(df)}条记录，{df['trade_date'].nunique()}个交易日")
                stats[symbol] = len(df)
            else:
                logger.warning(f"  存储失败")
                stats[symbol] = 0
            
            time.sleep(0.3)
        
        self._print_summary(stats)
        
        return stats

    def download_for_single_stock(
        self,
        symbol: str,
        start_date: str,
        trading_days_count: int = 5,
        save_to_db: bool = True,
    ) -> int:
        """兼容旧接口，下载单只股票指定窗口的分时数据。"""
        trading_days = self.get_next_n_trading_days(start_date, n=trading_days_count)
        end_date = trading_days[-1] if trading_days else (
            datetime.strptime(start_date, '%Y-%m-%d') + timedelta(days=max(trading_days_count * 2, 5))
        ).strftime('%Y-%m-%d')

        df = self.download_intraday_data(symbol, start_date, end_date)
        if df.empty:
            return 0

        if trading_days:
            df = df[df['trade_date'].isin(trading_days)]

        if df.empty:
            return 0

        if save_to_db:
            self.db.add_intraday_data(symbol, df)

        return int(len(df))
    
    def _print_summary(self, stats: Dict[str, int]):
        """打印下载摘要"""
        logger.info("\n" + "=" * 70)
        logger.info("下载完成摘要")
        logger.info("=" * 70)
        
        total_stocks = len(stats)
        success_stocks = sum(1 for v in stats.values() if v > 0)
        total_records = sum(stats.values())
        
        logger.info(f"\n【统计】")
        logger.info(f"  总股票数: {total_stocks}")
        logger.info(f"  成功下载: {success_stocks}")
        logger.info(f"  失败数量: {total_stocks - success_stocks}")
        logger.info(f"  总记录数: {total_records:,}")
        
        if success_stocks > 0:
            avg_records = total_records / success_stocks
            logger.info(f"  平均记录: {avg_records:.0f}条/只")
        
        failed = [k for k, v in stats.items() if v == 0]
        if failed:
            logger.info(f"\n【失败股票】")
            for symbol in failed:
                logger.info(f"  - {symbol}")
        
        logger.info("=" * 70)
    
    def close(self):
        """关闭连接"""
        if self.bs is not None:
            try:
                self.bs.logout()
            except:
                pass


def run_full_workflow(run_selection: bool = True, trading_days: int = 10, skip_existing: bool = True):
    """
    运行完整流程
    
    Args:
        run_selection: 是否运行选股模块（False则从数据库获取历史推荐）
        trading_days: 下载的交易日数量
        skip_existing: 是否跳过已有数据的股票
    """
    downloader = BatchIntradayDownloader()
    
    try:
        if run_selection:
            recommendations = downloader.run_stock_selection()
            
            if not recommendations:
                logger.warning("选股结果为空，尝试从数据库获取历史推荐")
                recommendations = downloader.get_historical_recommendations()
        else:
            recommendations = downloader.get_historical_recommendations()
        
        if not recommendations:
            logger.error("无推荐股票，退出")
            return {}
        
        downloader.save_recommendation_list(recommendations)
        
        stats = downloader.batch_download(
            recommendations=recommendations,
            trading_days_count=trading_days,
            skip_existing=skip_existing
        )
        
        return stats
        
    finally:
        downloader.close()


def run_batch_download(trading_days: int = 10, skip_existing: bool = True):
    """运行批量下载（从数据库获取历史推荐）"""
    return run_full_workflow(run_selection=False, trading_days=trading_days, skip_existing=skip_existing)


def run_selection_and_download(trading_days: int = 10, skip_existing: bool = True):
    """运行选股并下载"""
    return run_full_workflow(run_selection=True, trading_days=trading_days, skip_existing=skip_existing)


if __name__ == "__main__":
    run_full_workflow(run_selection=True)
