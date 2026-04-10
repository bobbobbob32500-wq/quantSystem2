# -*- coding: utf-8 -*-
"""
回测数据管理器
专门处理2026年2月推荐股票的数据下载和管理
包含缓存机制避免重复下载
"""

import os
import json
import hashlib
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from pathlib import Path

from src.core.logger import get_logger
from src.core.config import ConfigManager
from src.modules.backtest.history_recommendation_db import HistoryRecommendationDB
from src.modules.backtest.data_validator import DataValidator, StockCodeValidator

logger = get_logger("backtest_data_manager")


class DataCache:
    """数据缓存管理器"""
    
    def __init__(self, cache_dir: str = "data/backtest_cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_file = self.cache_dir / "cache_metadata.json"
        self.metadata = self._load_metadata()
    
    def _load_metadata(self) -> Dict:
        """加载缓存元数据"""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"加载缓存元数据失败: {e}")
        return {}
    
    def _save_metadata(self):
        """保存缓存元数据"""
        try:
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump(self.metadata, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"保存缓存元数据失败: {e}")
    
    def _get_cache_key(self, symbol: str, start_date: str, end_date: str) -> str:
        """生成缓存键"""
        key_str = f"{symbol}_{start_date}_{end_date}"
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def _get_cache_path(self, cache_key: str) -> Path:
        """获取缓存文件路径"""
        return self.cache_dir / f"{cache_key}.parquet"
    
    def get(self, symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """
        获取缓存数据
        
        Returns:
            DataFrame或None（缓存不存在或过期）
        """
        cache_key = self._get_cache_key(symbol, start_date, end_date)
        cache_path = self._get_cache_path(cache_key)
        
        if not cache_path.exists():
            return None
        
        # 检查缓存是否过期（7天）
        cache_info = self.metadata.get(cache_key, {})
        cache_time = cache_info.get('timestamp', 0)
        
        if datetime.now().timestamp() - cache_time > 7 * 24 * 3600:
            logger.debug(f"缓存过期: {symbol}")
            return None
        
        try:
            df = pd.read_parquet(cache_path)
            logger.debug(f"缓存命中: {symbol}")
            return df
        except Exception as e:
            logger.warning(f"读取缓存失败: {symbol}, {e}")
            return None
    
    def set(self, symbol: str, start_date: str, end_date: str, df: pd.DataFrame):
        """设置缓存数据"""
        cache_key = self._get_cache_key(symbol, start_date, end_date)
        cache_path = self._get_cache_path(cache_key)
        
        try:
            df.to_parquet(cache_path, index=False)
            
            self.metadata[cache_key] = {
                'symbol': symbol,
                'start_date': start_date,
                'end_date': end_date,
                'timestamp': datetime.now().timestamp(),
                'rows': len(df),
            }
            
            self._save_metadata()
            logger.debug(f"缓存已保存: {symbol}, {len(df)}条")
            
        except Exception as e:
            logger.warning(f"保存缓存失败: {symbol}, {e}")
    
    def clear_expired(self, max_age_days: int = 7):
        """清理过期缓存"""
        expired_keys = []
        current_time = datetime.now().timestamp()
        
        for key, info in self.metadata.items():
            cache_time = info.get('timestamp', 0)
            if current_time - cache_time > max_age_days * 24 * 3600:
                expired_keys.append(key)
        
        for key in expired_keys:
            cache_path = self._get_cache_path(key)
            if cache_path.exists():
                cache_path.unlink()
            del self.metadata[key]
        
        self._save_metadata()
        
        if expired_keys:
            logger.info(f"清理过期缓存: {len(expired_keys)}个")
    
    def get_stats(self) -> Dict:
        """获取缓存统计"""
        total_size = 0
        file_count = 0
        
        for cache_file in self.cache_dir.glob("*.parquet"):
            total_size += cache_file.stat().st_size
            file_count += 1
        
        return {
            'file_count': file_count,
            'total_size_mb': total_size / (1024 * 1024),
            'metadata_entries': len(self.metadata),
        }


class BacktestDataManager:
    """回测数据管理器"""
    
    def __init__(
        self,
        db: HistoryRecommendationDB = None,
        cache: DataCache = None,
        config: ConfigManager = None
    ):
        if db is None:
            db = HistoryRecommendationDB()
        if cache is None:
            cache = DataCache()
        if config is None:
            config = ConfigManager()
        
        self.db = db
        self.cache = cache
        self.config = config
        self.validator = DataValidator(db)
        
        # 数据下载器（延迟初始化）
        self._downloader = None
        
        logger.info("回测数据管理器初始化完成")
    
    @property
    def downloader(self):
        """延迟初始化下载器"""
        if self._downloader is None:
            from src.modules.backtest.intraday_data_downloader import IntradayDataDownloader
            token = self.config.get('data_source.tushare_token')
            self._downloader = IntradayDataDownloader(token=token)
        return self._downloader
    
    def prepare_backtest_data(
        self,
        month: str = "2026-02",
        follow_days: int = 7,
        force_download: bool = False
    ) -> Tuple[List[Dict], Dict]:
        """
        准备回测数据
        
        Args:
            month: 月份，如 "2026-02"
            follow_days: 推荐后跟踪天数
            force_download: 强制重新下载
        
        Returns:
            (推荐记录列表, 统计信息)
        """
        logger.info("=" * 70)
        logger.info("准备回测数据")
        logger.info("=" * 70)
        logger.info(f"目标月份: {month}")
        logger.info(f"跟踪天数: {follow_days}")
        
        # 1. 计算日期范围
        start_date = f"{month}-01"
        end_date = f"{month}-28"  # 简化处理
        
        # 2. 获取推荐记录
        recommendations = self.db.get_recommendations(start_date, end_date)
        
        if not recommendations:
            logger.error(f"未找到 {month} 月的推荐记录")
            return [], {'error': '无推荐记录'}
        
        logger.info(f"找到 {len(recommendations)} 条推荐记录")
        
        # 3. 验证股票代码
        valid_recommendations = []
        invalid_symbols = []
        
        for rec in recommendations:
            symbol = rec.get('symbol', '')
            is_valid, errors = StockCodeValidator.validate(symbol)
            
            if is_valid:
                valid_recommendations.append(rec)
            else:
                invalid_symbols.append((symbol, errors))
        
        if invalid_symbols:
            logger.warning(f"发现 {len(invalid_symbols)} 条无效股票代码")
            for symbol, errors in invalid_symbols[:5]:
                logger.warning(f"  {symbol}: {', '.join(errors)}")
        
        logger.info(f"有效推荐记录: {len(valid_recommendations)}条")
        
        # 4. 检查并下载数据
        download_stats = {
            'total': len(valid_recommendations),
            'cached': 0,
            'downloaded': 0,
            'failed': 0,
        }
        
        for i, rec in enumerate(valid_recommendations, 1):
            symbol = rec['symbol']
            rec_date = rec['recommendation_date']
            
            # 计算数据范围：推荐日 + 后续7个交易日
            rec_date_obj = datetime.strptime(rec_date, '%Y-%m-%d')
            data_start = rec_date_obj.strftime('%Y-%m-%d')
            data_end = (rec_date_obj + timedelta(days=follow_days + 5)).strftime('%Y-%m-%d')
            
            logger.info(f"[{i}/{len(valid_recommendations)}] 处理 {symbol} ({rec_date})")
            
            # 检查缓存
            if not force_download:
                cached_df = self.cache.get(symbol, data_start, data_end)
                if cached_df is not None:
                    logger.debug(f"  使用缓存数据: {len(cached_df)}条")
                    download_stats['cached'] += 1
                    continue
            
            # 检查数据库
            existing_df = self.db.get_intraday_data(symbol, data_start, data_end)
            if not existing_df.empty and len(existing_df) > 100:
                logger.debug(f"  数据库已有数据: {len(existing_df)}条")
                # 保存到缓存
                self.cache.set(symbol, data_start, data_end, existing_df)
                download_stats['cached'] += 1
                continue
            
            # 下载数据
            try:
                df = self.downloader.download_intraday_data(
                    symbol=symbol,
                    start_date=data_start,
                    end_date=data_end,
                    freq='1min'
                )
                
                if not df.empty:
                    # 保存到数据库
                    self.db.add_intraday_data(symbol, df)
                    # 保存到缓存
                    self.cache.set(symbol, data_start, data_end, df)
                    
                    logger.info(f"  下载成功: {len(df)}条")
                    download_stats['downloaded'] += 1
                else:
                    logger.warning(f"  下载失败: 无数据")
                    download_stats['failed'] += 1
                    
            except Exception as e:
                logger.error(f"  下载异常: {e}")
                download_stats['failed'] += 1
        
        # 5. 最终验证
        logger.info("\n执行最终数据验证...")
        validation_report = self.validator.validate_recommendations(
            start_date, end_date, follow_days
        )
        validation_report.print_report()
        
        # 6. 统计信息
        stats = {
            'month': month,
            'total_recommendations': len(recommendations),
            'valid_recommendations': len(valid_recommendations),
            'invalid_symbols': len(invalid_symbols),
            'download_stats': download_stats,
            'validation': {
                'valid_stocks': validation_report.valid_stocks,
                'missing_stocks': validation_report.missing_data_stocks,
                'partial_stocks': validation_report.partial_data_stocks,
            },
            'cache_stats': self.cache.get_stats(),
        }
        
        logger.info("=" * 70)
        logger.info("数据准备完成")
        logger.info(f"  缓存命中: {download_stats['cached']}")
        logger.info(f"  新下载: {download_stats['downloaded']}")
        logger.info(f"  下载失败: {download_stats['failed']}")
        logger.info("=" * 70)
        
        return valid_recommendations, stats
    
    def get_backtest_data(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        use_cache: bool = True
    ) -> pd.DataFrame:
        """
        获取回测数据（带缓存）
        
        Args:
            symbol: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            use_cache: 是否使用缓存
        
        Returns:
            分时数据DataFrame
        """
        # 1. 检查缓存
        if use_cache:
            cached_df = self.cache.get(symbol, start_date, end_date)
            if cached_df is not None:
                return cached_df
        
        # 2. 检查数据库
        df = self.db.get_intraday_data(symbol, start_date, end_date)
        
        if not df.empty:
            # 保存到缓存
            if use_cache:
                self.cache.set(symbol, start_date, end_date, df)
            return df
        
        # 3. 下载数据
        try:
            df = self.downloader.download_intraday_data(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                freq='1min'
            )
            
            if not df.empty:
                # 保存到数据库和缓存
                self.db.add_intraday_data(symbol, df)
                if use_cache:
                    self.cache.set(symbol, start_date, end_date, df)
            
            return df
            
        except Exception as e:
            logger.error(f"获取数据失败: {symbol}, {e}")
            return pd.DataFrame()
    
    def check_data_completeness(
        self,
        month: str = "2026-02",
        follow_days: int = 7
    ) -> Dict:
        """
        检查数据完整性
        
        Returns:
            完整性报告
        """
        start_date = f"{month}-01"
        end_date = f"{month}-28"
        
        recommendations = self.db.get_recommendations(start_date, end_date)
        
        if not recommendations:
            return {'error': '无推荐记录'}
        
        complete_count = 0
        incomplete_count = 0
        missing_symbols = []
        
        for rec in recommendations:
            symbol = rec['symbol']
            rec_date = rec['recommendation_date']
            
            rec_date_obj = datetime.strptime(rec_date, '%Y-%m-%d')
            data_start = rec_date_obj.strftime('%Y-%m-%d')
            data_end = (rec_date_obj + timedelta(days=follow_days + 5)).strftime('%Y-%m-%d')
            
            # 检查数据库
            df = self.db.get_intraday_data(symbol, data_start, data_end)
            
            if df.empty:
                incomplete_count += 1
                missing_symbols.append(symbol)
            else:
                # 检查数据覆盖度
                df['date'] = df['trade_time'].dt.date
                unique_dates = df['date'].nunique()
                
                if unique_dates >= follow_days:
                    complete_count += 1
                else:
                    incomplete_count += 1
                    missing_symbols.append(f"{symbol}({unique_dates}/{follow_days}天)")
        
        return {
            'total': len(recommendations),
            'complete': complete_count,
            'incomplete': incomplete_count,
            'completeness_rate': complete_count / len(recommendations) if recommendations else 0,
            'missing_symbols': missing_symbols[:20],  # 最多显示20个
        }
    
    def clear_cache(self):
        """清理缓存"""
        self.cache.clear_expired(max_age_days=0)
        logger.info("缓存已清理")

