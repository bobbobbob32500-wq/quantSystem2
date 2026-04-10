# -*- coding: utf-8 -*-
"""
市场分析模块
实现市场综合评分v3.1算法，量化评估A股整体市场环境
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Tuple, Optional

from src.core.logger import get_logger
from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.core.exceptions import MarketAnalysisException

logger = get_logger("market_analysis")


class MarketAnalyzer:
    """市场分析器"""
    
    def __init__(self, config: ConfigManager = None, db: DatabaseManager = None):
        """
        初始化市场分析器
        
        Args:
            config: 配置管理器
            db: 数据库管理器
        """
        if config is None:
            config = ConfigManager()
        if db is None:
            db = DatabaseManager(config)
        
        self.config = config
        self.db = db
        
        # 加载评分参数
        self.trend_weight = config.get("market_analysis.trend_weight", 0.4)
        self.width_weight = config.get("market_analysis.width_weight", 0.35)
        self.volume_weight = config.get("market_analysis.volume_weight", 0.25)
        self.volume_coefficient = config.get("market_analysis.volume_coefficient", 1.0)
        self.weak_threshold = config.get("market_analysis.weak_threshold", 45.0)
        self.indices = config.get("market_analysis.indices", ["000001.SH", "399001.SZ", "399006.SZ"])
        
        logger.info("市场分析器初始化完成")
    
    def get_index_data(self, ts_code: str, days: int = 60) -> pd.DataFrame:
        """
        获取指数历史数据
        
        Args:
            ts_code: 指数代码
            days: 获取天数
        
        Returns:
            指数数据DataFrame
        """
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")  # 多取一些数据
        
        sql = """
            SELECT trade_date, open, close, high, low, vol, amount, pct_chg
            FROM stock_daily
            WHERE ts_code = ? AND trade_date >= ? AND trade_date <= ?
            ORDER BY trade_date DESC
        """
        
        results = self.db.query(sql, (ts_code, start_date, end_date))
        
        if not results:
            logger.warning(f"未获取到指数{ts_code}的数据")
            return pd.DataFrame()
        
        df = pd.DataFrame(results)
        # 处理日期格式：YYYYMMDD 或 YYYY-MM-DD
        try:
            if len(str(df['trade_date'].iloc[0])) == 8:
                df['trade_date'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')
            else:
                df['trade_date'] = pd.to_datetime(df['trade_date'])
        except:
            df['trade_date'] = pd.to_datetime(df['trade_date'])
        df = df.sort_values('trade_date').reset_index(drop=True)
        
        # 取最近N天
        if len(df) > days:
            df = df.tail(days)
        
        return df
    
    def calculate_ma(self, prices: pd.Series, window: int) -> pd.Series:
        """计算移动平均线"""
        return prices.rolling(window=window).mean()
    
    def calculate_trend_score(self, index_data: Dict[str, pd.DataFrame]) -> Tuple[float, Dict]:
        """
        计算趋势得分
        
        Args:
            index_data: 各指数数据字典
        
        Returns:
            (趋势得分, 详细信息)
        """
        detail = {}
        scores = []
        
        for index_code, df in index_data.items():
            if df.empty or len(df) < 20:
                continue
            
            # 计算均线
            close = df['close']
            ma5 = self.calculate_ma(close, 5)
            ma10 = self.calculate_ma(close, 10)
            ma20 = self.calculate_ma(close, 20)
            ma60 = self.calculate_ma(close, 60) if len(df) >= 60 else ma20
            
            # 最新值
            latest_close = close.iloc[-1]
            latest_ma5 = ma5.iloc[-1]
            latest_ma10 = ma10.iloc[-1]
            latest_ma20 = ma20.iloc[-1]
            latest_ma60 = ma60.iloc[-1]
            
            # 均线排列得分 (0-40分)
            ma_score = 0
            if latest_close > latest_ma5 > latest_ma10 > latest_ma20:
                ma_score = 40  # 完美多头排列
            elif latest_close > latest_ma5 > latest_ma10:
                ma_score = 30  # 短期多头
            elif latest_close > latest_ma5:
                ma_score = 20  # 站上5日线
            elif latest_close < latest_ma5 < latest_ma10 < latest_ma20:
                ma_score = 5   # 空头排列
            else:
                ma_score = 15  # 震荡
            
            # 趋势斜率得分 (0-30分)
            if len(df) >= 10:
                recent_ma5 = ma5.iloc[-10:]
                slope = (recent_ma5.iloc[-1] - recent_ma5.iloc[0]) / recent_ma5.iloc[0] * 100
                if slope > 3:
                    slope_score = 30
                elif slope > 1:
                    slope_score = 25
                elif slope > 0:
                    slope_score = 20
                elif slope > -1:
                    slope_score = 15
                elif slope > -3:
                    slope_score = 10
                else:
                    slope_score = 5
            else:
                slope_score = 15
            
            # 价格位置得分 (0-30分)
            high_20 = df['high'].tail(20).max()
            low_20 = df['low'].tail(20).min()
            if high_20 != low_20:
                position = (latest_close - low_20) / (high_20 - low_20)
                position_score = position * 30
            else:
                position_score = 15
            
            # 单指数得分
            index_score = ma_score + slope_score + position_score
            scores.append(index_score)
            
            detail[index_code] = {
                "ma_score": round(ma_score, 1),
                "slope_score": round(slope_score, 1),
                "position_score": round(position_score, 1),
                "total_score": round(index_score, 1)
            }
        
        if not scores:
            return 50.0, detail  # 默认中性
        
        # 取各指数平均分
        trend_score = np.mean(scores)
        return round(trend_score, 1), detail
    
    def calculate_width_score(self) -> Tuple[float, Dict]:
        """
        计算市场宽度得分
        
        Returns:
            (宽度得分, 详细信息)
        """
        detail = {}
        
        # 获取最新交易日
        latest_date = self.db.get_latest_trade_date("stock_daily")
        if not latest_date:
            logger.warning("无日线数据，无法计算市场宽度")
            return 50.0, detail
        
        # 获取当日全市场涨跌情况
        sql = """
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN pct_chg > 0 THEN 1 ELSE 0 END) as up_count,
                SUM(CASE WHEN pct_chg < 0 THEN 1 ELSE 0 END) as down_count,
                SUM(CASE WHEN pct_chg >= 9.9 THEN 1 ELSE 0 END) as limit_up,
                SUM(CASE WHEN pct_chg <= -9.9 THEN 1 ELSE 0 END) as limit_down,
                AVG(ABS(pct_chg)) as avg_change
            FROM stock_daily
            WHERE trade_date = ? AND pct_chg IS NOT NULL
        """
        
        result = self.db.query_one(sql, (latest_date,))
        
        if not result or result['total'] == 0:
            return 50.0, detail
        
        total = result['total']
        up_count = result['up_count'] or 0
        down_count = result['down_count'] or 0
        limit_up = result['limit_up'] or 0
        limit_down = result['limit_down'] or 0
        avg_change = result['avg_change'] or 0
        
        # 涨跌比得分 (0-40分)
        if up_count + down_count > 0:
            up_ratio = up_count / (up_count + down_count)
            up_down_score = up_ratio * 40
        else:
            up_down_score = 20
        
        # 涨停跌停比得分 (0-30分)
        if limit_up + limit_down > 0:
            limit_ratio = limit_up / (limit_up + limit_down)
            limit_score = limit_ratio * 30
        else:
            limit_score = 15
        
        # 平均振幅得分 (0-30分)
        if avg_change > 3:
            volatility_score = 30
        elif avg_change > 2:
            volatility_score = 25
        elif avg_change > 1:
            volatility_score = 20
        else:
            volatility_score = 15
        
        width_score = up_down_score + limit_score + volatility_score
        
        detail = {
            "total_stocks": total,
            "up_count": up_count,
            "down_count": down_count,
            "limit_up": limit_up,
            "limit_down": limit_down,
            "up_ratio": round(up_count / total * 100, 1) if total > 0 else 0,
            "avg_change": round(avg_change, 2),
            "up_down_score": round(up_down_score, 1),
            "limit_score": round(limit_score, 1),
            "volatility_score": round(volatility_score, 1)
        }
        
        return round(width_score, 1), detail
    
    def calculate_volume_score(self, index_data: Dict[str, pd.DataFrame]) -> Tuple[float, Dict]:
        """
        计算量能得分
        
        Args:
            index_data: 各指数数据字典
        
        Returns:
            (量能得分, 详细信息)
        """
        detail = {}
        scores = []
        
        for index_code, df in index_data.items():
            if df.empty or len(df) < 20:
                continue
            
            # 成交量数据
            vol = df['vol']
            latest_vol = vol.iloc[-1]
            
            # 计算量能均线
            vol_ma5 = self.calculate_ma(vol, 5)
            vol_ma20 = self.calculate_ma(vol, 20)
            
            latest_vol_ma5 = vol_ma5.iloc[-1]
            latest_vol_ma20 = vol_ma20.iloc[-1]
            
            # 量能放大得分 (0-40分)
            if latest_vol_ma20 > 0:
                vol_ratio = latest_vol / latest_vol_ma20
                if vol_ratio > 2:
                    vol_expand_score = 40
                elif vol_ratio > 1.5:
                    vol_expand_score = 35
                elif vol_ratio > 1.2:
                    vol_expand_score = 30
                elif vol_ratio > 1:
                    vol_expand_score = 25
                elif vol_ratio > 0.8:
                    vol_expand_score = 20
                else:
                    vol_expand_score = 10
            else:
                vol_expand_score = 20
            
            # 量能趋势得分 (0-30分)
            if len(df) >= 10:
                recent_vol_ma5 = vol_ma5.iloc[-10:]
                vol_slope = (recent_vol_ma5.iloc[-1] - recent_vol_ma5.iloc[0]) / recent_vol_ma5.iloc[0] * 100 if recent_vol_ma5.iloc[0] > 0 else 0
                if vol_slope > 20:
                    vol_trend_score = 30
                elif vol_slope > 10:
                    vol_trend_score = 25
                elif vol_slope > 0:
                    vol_trend_score = 20
                elif vol_slope > -10:
                    vol_trend_score = 15
                else:
                    vol_trend_score = 10
            else:
                vol_trend_score = 15
            
            # 量价配合得分 (0-30分)
            close = df['close']
            close_ma5 = self.calculate_ma(close, 5)
            
            price_up = close_ma5.iloc[-1] > close_ma5.iloc[-5] if len(close_ma5) >= 5 else False
            vol_up = vol_ma5.iloc[-1] > vol_ma5.iloc[-5] if len(vol_ma5) >= 5 else False
            
            if price_up and vol_up:
                vp_score = 30  # 量价齐升
            elif not price_up and not vol_up:
                vp_score = 20  # 量价齐跌
            elif price_up and not vol_up:
                vp_score = 15  # 价升量缩
            else:
                vp_score = 25  # 价跌量增
            
            index_score = vol_expand_score + vol_trend_score + vp_score
            scores.append(index_score)
            
            detail[index_code] = {
                "vol_ratio": round(latest_vol / latest_vol_ma20, 2) if latest_vol_ma20 > 0 else 1,
                "vol_expand_score": round(vol_expand_score, 1),
                "vol_trend_score": round(vol_trend_score, 1),
                "vp_score": round(vp_score, 1),
                "total_score": round(index_score, 1)
            }
        
        if not scores:
            return 50.0, detail
        
        volume_score = np.mean(scores)
        return round(volume_score, 1), detail
    
    def calculate_market_score_v3(self) -> Dict:
        """
        计算市场综合评分v3.1
        
        Returns:
            评分结果字典
        """
        logger.info("开始计算市场综合评分...")
        
        # 获取各指数数据
        index_data = {}
        for index_code in self.indices:
            df = self.get_index_data(index_code, days=60)
            if not df.empty:
                index_data[index_code] = df
        
        if not index_data:
            logger.error("无法获取指数数据")
            raise MarketAnalysisException("无法获取指数数据")
        
        # 计算各维度得分
        trend_score, trend_detail = self.calculate_trend_score(index_data)
        width_score, width_detail = self.calculate_width_score()
        volume_score, volume_detail = self.calculate_volume_score(index_data)
        
        # 计算综合评分
        base_score = (
            trend_score * self.trend_weight +
            width_score * self.width_weight +
            volume_score * self.volume_weight
        )
        total_score = round(base_score * self.volume_coefficient, 1)
        
        # 判断市场转弱
        market_weak = total_score < self.weak_threshold
        
        # 生成操作建议
        suggestion = self._generate_suggestion(total_score)
        
        result = {
            "total_score": total_score,
            "trend_score": trend_score,
            "width_score": width_score,
            "volume_score": volume_score,
            "trend_weight": self.trend_weight,
            "width_weight": self.width_weight,
            "volume_weight": self.volume_weight,
            "volume_coefficient": self.volume_coefficient,
            "market_weak": market_weak,
            "suggestion": suggestion,
            "trend_detail": trend_detail,
            "width_detail": width_detail,
            "volume_detail": volume_detail,
            "calculate_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        logger.info(f"市场综合评分计算完成: {total_score}分, 市场转弱: {market_weak}")
        return result
    
    def _generate_suggestion(self, total_score: float) -> str:
        """
        生成操作建议
        
        Args:
            total_score: 综合评分
        
        Returns:
            操作建议文本
        """
        if total_score < 40:
            return "极差，建议空仓，立即清理低盈利/亏损持仓"
        elif total_score < 60:
            return "震荡，精选个股，轻仓操作，严格设置止损止盈"
        elif total_score < 80:
            return "偏强，适度加仓，跟随板块热点，持有强势股"
        else:
            return "强势，重仓持有，把握主升浪，趋势破位前不轻易止盈"
    
    def get_market_status(self) -> str:
        """
        获取市场状态描述
        
        Returns:
            市场状态文本
        """
        result = self.calculate_market_score_v3()
        score = result['total_score']
        
        if score < 40:
            return "极差"
        elif score < 60:
            return "震荡"
        elif score < 80:
            return "偏强"
        else:
            return "强势"
    
    def save_analysis_result(self, result: Dict) -> bool:
        """
        保存分析结果到数据库
        
        Args:
            result: 分析结果
        
        Returns:
            是否成功
        """
        try:
            sql = """
                INSERT INTO system_log (log_time, log_level, module_name, log_content)
                VALUES (?, ?, ?, ?)
            """
            
            log_content = f"市场评分:{result['total_score']}, 趋势:{result['trend_score']}, 宽度:{result['width_score']}, 量能:{result['volume_score']}, 建议:{result['suggestion']}"
            
            self.db.execute(sql, (
                result['calculate_time'],
                "INFO",
                "market_analysis",
                log_content
            ))
            
            logger.info("市场分析结果已保存")
            return True
        except Exception as e:
            logger.error(f"保存分析结果失败: {e}")
            return False
    
    def run_analysis(self) -> Dict:
        """
        执行完整的市场分析
        
        Returns:
            分析结果
        """
        logger.info("=" * 50)
        logger.info("开始执行市场分析...")
        logger.info("=" * 50)
        
        try:
            result = self.calculate_market_score_v3()
            self.save_analysis_result(result)
            
            logger.info("=" * 50)
            logger.info(f"市场综合评分: {result['total_score']}分")
            logger.info(f"趋势得分: {result['trend_score']}分 (权重{result['trend_weight']})")
            logger.info(f"宽度得分: {result['width_score']}分 (权重{result['width_weight']})")
            logger.info(f"量能得分: {result['volume_score']}分 (权重{result['volume_weight']})")
            logger.info(f"量能系数: {result['volume_coefficient']}")
            logger.info(f"市场转弱: {result['market_weak']}")
            logger.info(f"操作建议: {result['suggestion']}")
            logger.info("=" * 50)
            
            return result
        except Exception as e:
            logger.error(f"市场分析执行失败: {e}")
            raise MarketAnalysisException(f"市场分析执行失败: {e}")
