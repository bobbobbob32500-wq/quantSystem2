# -*- coding: utf-8 -*-
"""
选股结果缓存管理器
避免重复计算，提高效率
"""

import json
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from src.core.logger import get_logger

logger = get_logger("selection_cache")


class SelectionCache:
    """选股结果缓存管理器"""
    
    def __init__(self, cache_dir: str = "data/cache"):
        """
        初始化缓存管理器
        
        Args:
            cache_dir: 缓存目录
        """
        self.cache_dir = cache_dir
        self.cache_file = os.path.join(cache_dir, "selection_cache.json")
        
        # 确保缓存目录存在
        os.makedirs(cache_dir, exist_ok=True)
        
        # 缓存有效期（天）
        self.cache_expire_days = 30  # 选股结果缓存30天（因为回测可能使用历史日期）
        
        # 加载缓存
        self.cache = self._load_cache()
    
    def _load_cache(self) -> Dict:
        """加载缓存文件"""
        if not os.path.exists(self.cache_file):
            return {}
        
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                cache = json.load(f)
            logger.info(f"加载缓存: {len(cache)}条记录")
            return cache
        except Exception as e:
            logger.error(f"加载缓存失败: {e}")
            return {}
    
    def _save_cache(self):
        """保存缓存文件"""
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
            logger.info(f"保存缓存: {len(self.cache)}条记录")
        except Exception as e:
            logger.error(f"保存缓存失败: {e}")
    
    def _is_cache_valid(self, cache_date: str) -> bool:
        """
        检查缓存是否有效
        
        Args:
            cache_date: 缓存日期
            
        Returns:
            是否有效
        """
        try:
            cache_dt = datetime.strptime(cache_date, '%Y%m%d')
            expire_dt = datetime.now() - timedelta(days=self.cache_expire_days)
            return cache_dt >= expire_dt
        except:
            return False
    
    def get_cache_key(self, date: str) -> str:
        """
        生成缓存键
        
        Args:
            date: 日期
            
        Returns:
            缓存键
        """
        return f"selection_{date}"
    
    def get(self, date: str) -> Optional[List[Dict]]:
        """
        获取缓存的选股结果
        
        Args:
            date: 选股日期
            
        Returns:
            选股结果或None
        """
        key = self.get_cache_key(date)
        
        if key not in self.cache:
            logger.info(f"缓存未命中: {date}")
            return None
        
        cache_data = self.cache[key]
        
        # 检查缓存是否过期
        if not self._is_cache_valid(date):
            logger.info(f"缓存已过期: {date}")
            del self.cache[key]
            self._save_cache()
            return None
        
        logger.info(f"缓存命中: {date}")
        return cache_data.get('stocks', [])
    
    def set(self, date: str, stocks: List[Dict]):
        """
        保存选股结果到缓存
        
        Args:
            date: 选股日期
            stocks: 选股结果（前10只）
        """
        key = self.get_cache_key(date)
        
        # 只保存前10只股票
        top_stocks = stocks[:10]
        
        self.cache[key] = {
            'date': date,
            'stocks': top_stocks,
            'cached_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'stock_count': len(top_stocks)
        }
        
        self._save_cache()
        logger.info(f"缓存已保存: {date} {len(top_stocks)}只股票")
    
    def clear_expired(self):
        """清理过期缓存"""
        expired_keys = []
        
        for key, data in self.cache.items():
            date = data.get('date', '')
            if not self._is_cache_valid(date):
                expired_keys.append(key)
        
        for key in expired_keys:
            del self.cache[key]
        
        if expired_keys:
            self._save_cache()
            logger.info(f"清理过期缓存: {len(expired_keys)}条")
    
    def clear_all(self):
        """清空所有缓存"""
        self.cache = {}
        self._save_cache()
        logger.info("清空所有缓存")
    
    def get_stats(self) -> Dict:
        """获取缓存统计信息"""
        valid_count = 0
        expired_count = 0
        
        for key, data in self.cache.items():
            date = data.get('date', '')
            if self._is_cache_valid(date):
                valid_count += 1
            else:
                expired_count += 1
        
        return {
            'total': len(self.cache),
            'valid': valid_count,
            'expired': expired_count,
            'cache_file': self.cache_file
        }
    
    def print_stats(self):
        """打印缓存统计"""
        stats = self.get_stats()
        
        print("\n" + "="*70)
        print("选股缓存统计")
        print("="*70)
        print(f"总缓存数: {stats['total']}")
        print(f"有效缓存: {stats['valid']}")
        print(f"过期缓存: {stats['expired']}")
        print(f"缓存文件: {stats['cache_file']}")
        print("="*70)
        
        if self.cache:
            print("\n缓存详情:")
            print("-"*70)
            for key, data in self.cache.items():
                date = data.get('date', '')
                cached_time = data.get('cached_time', '')
                stock_count = data.get('stock_count', 0)
                is_valid = "有效" if self._is_cache_valid(date) else "过期"
                
                print(f"{date}: {stock_count}只股票 | {cached_time} | {is_valid}")
            print("-"*70)
