# -*- coding: utf-8 -*-
"""
公共工具函数模块
提供日期处理、数据转换等通用功能
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Union, Optional, List, Dict, Any
from functools import wraps
import time
import hashlib
import pickle

from src.core.logger import get_logger

logger = get_logger("utils")


def normalize_trade_date(
    df: pd.DataFrame, 
    column: str = 'trade_date',
    format: str = None
) -> pd.DataFrame:
    """
    标准化交易日期格式
    
    Args:
        df: 数据DataFrame
        column: 日期列名
        format: 目标格式，默认转换为datetime
    
    Returns:
        处理后的DataFrame
    """
    if df.empty or column not in df.columns:
        return df
    
    try:
        first_value = str(df[column].iloc[0])
        
        if len(first_value) == 8 and first_value.isdigit():
            df[column] = pd.to_datetime(df[column], format='%Y%m%d')
        else:
            df[column] = pd.to_datetime(df[column])
        
        if format:
            df[column] = df[column].dt.strftime(format)
    except Exception as e:
        logger.warning(f"日期格式转换失败: {e}")
        df[column] = pd.to_datetime(df[column], errors='coerce')
    
    return df


def format_date(
    date: Union[str, datetime, pd.Timestamp],
    output_format: str = '%Y%m%d'
) -> str:
    """
    统一日期格式化
    
    Args:
        date: 日期（字符串、datetime或Timestamp）
        output_format: 输出格式
    
    Returns:
        格式化后的日期字符串
    """
    if date is None:
        return ''
    
    if isinstance(date, str):
        if len(date) == 8 and date.isdigit():
            date = datetime.strptime(date, '%Y%m%d')
        elif '-' in date:
            date = datetime.strptime(date, '%Y-%m-%d')
        else:
            date = pd.to_datetime(date)
    elif isinstance(date, pd.Timestamp):
        date = date.to_pydatetime()
    
    return date.strftime(output_format)


def get_trading_days(
    start_date: Union[str, datetime],
    end_date: Union[str, datetime],
    exclude_weekend: bool = True
) -> List[str]:
    """
    获取日期范围内的交易日列表（简化版，仅排除周末）
    
    Args:
        start_date: 开始日期
        end_date: 结束日期
        exclude_weekend: 是否排除周末
    
    Returns:
        日期列表
    """
    start = pd.to_datetime(format_date(start_date, '%Y-%m-%d'))
    end = pd.to_datetime(format_date(end_date, '%Y-%m-%d'))
    
    dates = pd.date_range(start=start, end=end, freq='D')
    
    if exclude_weekend:
        dates = dates[dates.dayofweek < 5]
    
    return [d.strftime('%Y%m%d') for d in dates]


def calculate_ma(prices: pd.Series, window: int) -> pd.Series:
    """计算移动平均线"""
    return prices.rolling(window=window).mean()


def calculate_ema(prices: pd.Series, span: int) -> pd.Series:
    """计算指数移动平均线"""
    return prices.ewm(span=span, adjust=False).mean()


def calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    """计算RSI指标"""
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calculate_macd(
    prices: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9
) -> Dict[str, pd.Series]:
    """计算MACD指标"""
    ema_fast = calculate_ema(prices, fast)
    ema_slow = calculate_ema(prices, slow)
    
    macd_line = ema_fast - ema_slow
    signal_line = calculate_ema(macd_line, signal)
    histogram = macd_line - signal_line
    
    return {
        'macd': macd_line,
        'signal': signal_line,
        'histogram': histogram
    }


def calculate_bollinger_bands(
    prices: pd.Series,
    period: int = 20,
    std_dev: float = 2.0
) -> Dict[str, pd.Series]:
    """计算布林带"""
    middle = calculate_ma(prices, period)
    std = prices.rolling(window=period).std()
    
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    
    return {
        'upper': upper,
        'middle': middle,
        'lower': lower
    }


def calculate_atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14
) -> pd.Series:
    """计算ATR（平均真实波幅）"""
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = true_range.rolling(window=period).mean()
    
    return atr


def safe_divide(
    numerator: Union[float, pd.Series],
    denominator: Union[float, pd.Series],
    default: float = 0.0
) -> Union[float, pd.Series]:
    """安全除法，避免除零错误"""
    if isinstance(numerator, pd.Series) or isinstance(denominator, pd.Series):
        result = numerator / denominator
        result = result.replace([np.inf, -np.inf], default)
        result = result.fillna(default)
        return result
    else:
        if denominator == 0:
            return default
        return numerator / denominator


def normalize_score(
    value: float,
    min_val: float,
    max_val: float,
    target_min: float = 0.0,
    target_max: float = 100.0
) -> float:
    """
    将值归一化到目标范围
    
    Args:
        value: 原始值
        min_val: 原始最小值
        max_val: 原始最大值
        target_min: 目标最小值
        target_max: 目标最大值
    
    Returns:
        归一化后的值
    """
    if max_val == min_val:
        return (target_min + target_max) / 2
    
    normalized = (value - min_val) / (max_val - min_val)
    return target_min + normalized * (target_max - target_min)


def memoize(timeout: int = 300):
    """
    缓存装饰器
    
    Args:
        timeout: 缓存超时时间（秒）
    """
    cache = {}
    
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = (func.__name__, args, tuple(sorted(kwargs.items())))
            key_hash = hashlib.md5(pickle.dumps(key)).hexdigest()
            
            if key_hash in cache:
                value, timestamp = cache[key_hash]
                if time.time() - timestamp < timeout:
                    return value
            
            result = func(*args, **kwargs)
            cache[key_hash] = (result, time.time())
            return result
        
        return wrapper
    
    return decorator


def timing(func):
    """计时装饰器"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        elapsed = time.time() - start
        logger.debug(f"{func.__name__} 执行耗时: {elapsed:.3f}秒")
        return result
    return wrapper


def retry(times: int = 3, delay: float = 1.0):
    """
    重试装饰器
    
    Args:
        times: 重试次数
        delay: 重试间隔（秒）
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for i in range(times):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if i < times - 1:
                        logger.warning(f"{func.__name__} 执行失败，{delay}秒后重试 ({i+1}/{times}): {e}")
                        time.sleep(delay)
            raise last_exception
        return wrapper
    return decorator


def validate_stock_code(ts_code: str) -> bool:
    """验证股票代码格式"""
    if not ts_code or '.' not in ts_code:
        return False
    
    code, market = ts_code.split('.')
    
    if market == 'SH':
        return code.startswith(('600', '601', '603', '605', '688'))
    elif market == 'SZ':
        return code.startswith(('000', '001', '002', '003', '300', '301'))
    
    return False


def get_stock_market(ts_code: str) -> str:
    """获取股票所属市场"""
    if '.' not in ts_code:
        return 'UNKNOWN'
    
    code, market = ts_code.split('.')
    
    if market == 'SH':
        if code.startswith('688'):
            return '科创板'
        return '沪市主板'
    elif market == 'SZ':
        if code.startswith(('300', '301')):
            return '创业板'
        return '深市主板'
    
    return '其他'


def chunk_list(lst: List, chunk_size: int) -> List[List]:
    """将列表分块"""
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]


def flatten_dict(d: Dict, parent_key: str = '', sep: str = '.') -> Dict:
    """展平嵌套字典"""
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)
