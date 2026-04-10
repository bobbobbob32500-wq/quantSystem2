# -*- coding: utf-8 -*-
"""
分时数据下载器
基于观察池记录下载分时数据
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import time as time_module
import tushare as ts
from src.core.logger import get_logger
from src.core.config import ConfigManager
import os
import json

logger = get_logger("intraday_data_downloader")


class IntradayDataDownloader:
    """分时数据下载器"""
    
    def __init__(self, token: Optional[str] = None):
        """初始化"""
        if token:
            ts.set_token(token)
        
        self.pro = ts.pro_api()
        self.config = ConfigManager()
        
        # 数据缓存目录
        self.cache_dir = 'data/intraday_cache'
        os.makedirs(self.cache_dir, exist_ok=True)
    
    def download_for_observation_pool(self, 
                                     observation_records: List[Dict],
                                     freq: str = '1min',
                                     use_cache: bool = True) -> Dict[str, pd.DataFrame]:
        """
        为观察池下载分时数据
        
        Args:
            observation_records: 观察池记录列表
            freq: 数据频率 ('1min', '5min', '15min', '30min', '60min')
            use_cache: 是否使用缓存
        
        Returns:
            分时数据字典 {symbol: DataFrame}
        """
        logger.info("="*70)
        logger.info("开始下载观察池分时数据")
        logger.info("="*70)
        
        minute_data_dict = {}
        
        for i, record in enumerate(observation_records, 1):
            symbol = record['symbol']
            selection_date = record['selection_date']
            sell_date = record.get('sell_date')
            
            logger.info(f"\n[{i}/{len(observation_records)}] 处理 {symbol}")
            logger.info(f"  选入日期: {selection_date}")
            logger.info(f"  清仓日期: {sell_date or '未清仓'}")
            
            # 确定数据范围
            start_date = selection_date
            end_date = sell_date if sell_date else self._get_latest_date()
            
            # 下载分时数据
            df = self.download_intraday_data(
                symbol, 
                start_date, 
                end_date, 
                freq, 
                use_cache
            )
            
            if not df.empty:
                minute_data_dict[symbol] = df
                logger.info(f"  下载完成: {len(df)}条记录")
            else:
                logger.warning(f"  下载失败: 无数据")
        
        logger.info(f"\n下载完成: {len(minute_data_dict)}只股票")
        
        return minute_data_dict
    
    def download_intraday_data(self,
                              symbol: str,
                              start_date: str,
                              end_date: str,
                              freq: str = '1min',
                              use_cache: bool = True) -> pd.DataFrame:
        """
        下载单只股票的分时数据
        
        Args:
            symbol: 股票代码
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            freq: 数据频率
            use_cache: 是否使用缓存
        
        Returns:
            分时数据DataFrame
        """
        # 检查缓存
        cache_key = f"{symbol}_{start_date}_{end_date}_{freq}"
        cache_file = os.path.join(self.cache_dir, f"{cache_key}.parquet")
        
        if use_cache and os.path.exists(cache_file):
            logger.debug(f"从缓存加载: {cache_key}")
            return pd.read_parquet(cache_file)
        
        # 转换股票代码格式
        ts_code = self._convert_symbol(symbol)
        freq = self._normalize_freq(freq)
        
        # 转换日期格式
        start_dt = start_date.replace('-', '') + '093000'
        end_dt = end_date.replace('-', '') + '150000'
        
        retry_wait_seconds = 35
        for attempt in range(3):
            try:
                # 获取分时数据
                df = self.pro.query('stk_mins',
                                   ts_code=ts_code,
                                   start_date=start_dt,
                                   end_date=end_dt,
                                   freq=freq)
                
                if df.empty:
                    logger.warning(f"未获取到数据: {symbol}")
                    return pd.DataFrame()
                
                # 数据处理
                df = self._process_intraday_data(df, symbol)
                
                # 保存缓存
                if use_cache:
                    df.to_parquet(cache_file, index=False)
                    logger.debug(f"保存缓存: {cache_key}")
                
                return df
                
            except Exception as e:
                error_text = str(e)
                is_rate_limited = "每分钟最多访问该接口2次" in error_text
                if is_rate_limited and attempt < 2:
                    logger.warning(
                        "下载受限 %s，等待 %s 秒后重试 (%s/3)",
                        symbol,
                        retry_wait_seconds,
                        attempt + 1,
                    )
                    time_module.sleep(retry_wait_seconds)
                    continue
                logger.error(f"下载失败 {symbol}: {e}")
                return pd.DataFrame()

        return pd.DataFrame()
    
    def _process_intraday_data(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """处理分时数据"""
        # 重命名列
        df = df.rename(columns={
            'trade_time': 'trade_time',
            'open': 'open',
            'high': 'high',
            'low': 'low',
            'close': 'close',
            'vol': 'volume',
            'amount': 'amount',
        })
        
        # 转换时间格式
        df['trade_time'] = pd.to_datetime(df['trade_time'])
        
        # 添加股票代码
        df['symbol'] = symbol
        
        # 添加日期列
        df['trade_date'] = df['trade_time'].dt.date
        
        # 排序
        df = df.sort_values('trade_time').reset_index(drop=True)
        
        return df
    
    def _convert_symbol(self, symbol: str) -> str:
        """转换股票代码格式"""
        if '.' in symbol:
            return symbol
        
        if symbol.startswith('6'):
            return f"{symbol}.SH"
        else:
            return f"{symbol}.SZ"

    def _normalize_freq(self, freq: str) -> str:
        text = str(freq or "").strip().lower()
        mapping = {
            "1": "1MIN",
            "1m": "1MIN",
            "1min": "1MIN",
            "5": "5MIN",
            "5m": "5MIN",
            "5min": "5MIN",
            "15": "15MIN",
            "15m": "15MIN",
            "15min": "15MIN",
            "30": "30MIN",
            "30m": "30MIN",
            "30min": "30MIN",
            "60": "60MIN",
            "60m": "60MIN",
            "60min": "60MIN",
        }
        return mapping.get(text, str(freq))
    
    def _get_latest_date(self) -> str:
        """获取最新日期"""
        return datetime.now().strftime('%Y-%m-%d')
    
    def download_for_backtest(self,
                             backtest_records: List[Dict],
                             freq: str = '1min') -> Dict[str, pd.DataFrame]:
        """
        为回测准备数据
        
        Args:
            backtest_records: 回测记录（包含选入和清仓信息）
            freq: 数据频率
        
        Returns:
            日线数据和分钟数据
        """
        logger.info("准备回测数据...")
        
        # 下载分钟数据
        minute_data_dict = self.download_for_observation_pool(
            backtest_records, 
            freq
        )
        
        # 获取日线数据（用于选股）
        daily_data_dict = self._download_daily_data(backtest_records)
        
        return {
            'daily': daily_data_dict,
            'minute': minute_data_dict,
        }
    
    def _download_daily_data(self, backtest_records: List[Dict]) -> Dict[str, pd.DataFrame]:
        """下载日线数据"""
        daily_data_dict = {}
        
        # 获取所有涉及的日期
        all_dates = set()
        for record in backtest_records:
            all_dates.add(record['selection_date'])
            if record.get('sell_date'):
                all_dates.add(record['sell_date'])
        
        # 找到最早和最晚日期
        dates = sorted(list(all_dates))
        start_date = dates[0]
        end_date = dates[-1]
        
        # 获取所有股票代码
        symbols = list(set(r['symbol'] for r in backtest_records))
        
        logger.info(f"下载日线数据: {len(symbols)}只股票, {start_date} ~ {end_date}")
        
        for symbol in symbols:
            ts_code = self._convert_symbol(symbol)
            
            try:
                df = self.pro.daily(
                    ts_code=ts_code,
                    start_date=start_date.replace('-', ''),
                    end_date=end_date.replace('-', '')
                )
                
                if not df.empty:
                    df['trade_date'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')
                    df = df.sort_values('trade_date').reset_index(drop=True)
                    daily_data_dict[symbol] = df
                    
            except Exception as e:
                logger.error(f"下载日线数据失败 {symbol}: {e}")
        
        return daily_data_dict
    
    def save_observation_records(self, 
                                records: List[Dict],
                                filename: str = 'observation_records.json') -> None:
        """保存观察池记录"""
        filepath = os.path.join(self.cache_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        
        logger.info(f"观察池记录已保存: {filepath}")
    
    def load_observation_records(self, 
                                filename: str = 'observation_records.json') -> List[Dict]:
        """加载观察池记录"""
        filepath = os.path.join(self.cache_dir, filename)
        
        if not os.path.exists(filepath):
            logger.warning(f"观察池记录不存在: {filepath}")
            return []
        
        with open(filepath, 'r', encoding='utf-8') as f:
            records = json.load(f)
        
        logger.info(f"观察池记录已加载: {len(records)}条")
        
        return records
