"""
修复版最终实盘策略 - 强势回调二次启动
修复了特征计算和涨停检测问题
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Tuple, Optional
import logging
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

logger = logging.getLogger(__name__)


class FinalStrategyFixed:
    """修复版最终实盘策略 - 强势回调二次启动"""
    
    def __init__(self, config: Dict = None):
        """
        初始化策略
        
        Args:
            config: 策略配置字典
        """
        self.config = config or self._get_default_config()
        logger.info("修复版最终实盘策略初始化完成")
    
    def _get_default_config(self) -> Dict:
        """获取默认配置"""
        return {
            # Step 1: 基础过滤（放宽条件）
            'base_filter': {
                'sh_prefixes': ['600', '601', '603', '605'],
                'sz_prefixes': ['000', '001', '002'],
                'exclude_prefixes': ['300', '688', '8'],
                'min_listing_days': 60,
                'min_price': 2.0,  # 放宽到2元
                'min_avg_amount_20': 3e7,  # 放宽到3000万
                'max_avg_amount_20': 5e9,   # 50亿
                'max_limit_down_20': 5,     # 放宽到5次
            },
            
            # Step 2: 强势宽入口（放宽条件）
            'strength_events': {
                'limit_up_count_10_min': 1,      # 10日内涨停次数≥1
                'return_5_min': 0.05,            # 放宽到5%
                'return_10_min': 0.08,           # 放宽到8%
                'breakout_price_ratio': 0.95,     # 放宽到95%
                'breakout_volume_ratio': 1.2,     # 放宽到1.2倍
                'lookback_high': 20,             # 前高计算周期
            },
            
            # Step 3: 回调结构（核心筛选）
            'pullback_structure': {
                'days_range': [2, 10],           # 放宽到2-10天
                'drawdown_range': [0.01, 0.15],  # 放宽到1%-15%
                'decay_ratio_max': 0.8,          # 放宽到0.8
                'down_days_ratio_max': 0.8,      # 下跌天数比例≤80%
            },
            
            # Step 4: 缩量确认
            'volume_condition': {
                'volume_shrink_ratio': 1.0,      # 放宽到1.0
                'lookback_volume': 5,            # 5日均量
            },
            
            # Step 5: 趋势结构（不能放松）
            'trend_structure': {
                'ma5_above_ma10': True,
                'close_above_ma10_ratio': 0.95,  # 放宽到95%
                'close_near_ma5_pct': 0.05,      # 放宽到5%
            },
            
            # Step 6: 趋势方向（保底）
            'trend_direction': {
                'ma10_slope_lookback': 3,        # MA10斜率计算周期
                'ma10_slope_min': -0.01,         # 允许轻微负斜率
            },
            
            # Step 8: 评分排序
            'scoring': {
                'strength_weight': 0.30,
                'pullback_weight': 0.30,
                'trend_weight': 0.20,
                'volume_weight': 0.20,
                'min_total_score': 50,           # 降低到50分
            },
            
            # 选股控制
            'selection': {
                'max_candidates': 15,            # 最多15只
                'sort_by': 'total_score',        # 按总分排序
            }
        }
    
    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        准备特征数据
        
        Args:
            df: 原始数据DataFrame
            
        Returns:
            包含所有计算特征的DataFrame
        """
        logger.info("准备特征数据...")
        df = df.copy()
        
        # 确保日期格式
        if 'trade_date' in df.columns:
            df['trade_date'] = pd.to_datetime(df['trade_date'], errors='coerce')
        if 'list_date' in df.columns:
            df['list_date'] = pd.to_datetime(df['list_date'], errors='coerce')
        
        # 按股票代码和日期排序
        df = df.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
        
        # 按股票分组计算
        g = df.groupby('ts_code', group_keys=False)
        
        # 1. 基础字段
        df['prev_close'] = g['close'].shift(1)
        df['ret'] = df['close'] / df['prev_close'] - 1
        
        # 使用原始pct_chg或计算
        if 'pct_chg' not in df.columns or df['pct_chg'].isnull().all():
            df['pct_chg'] = df['ret'] * 100  # 百分比
        else:
            # 确保pct_chg是数值
            df['pct_chg'] = pd.to_numeric(df['pct_chg'], errors='coerce')
        
        # 2. 涨停检测 - 使用涨幅≥9.5%
        df['is_limit_up'] = (df['pct_chg'] >= 9.5).astype(int)
        df['count_limit_up_10'] = g['is_limit_up'].transform(lambda x: x.rolling(10, min_periods=5).sum())
        
        # 3. 涨幅计算
        df['return_5'] = g['close'].transform(lambda x: x / x.shift(5) - 1)
        df['return_10'] = g['close'].transform(lambda x: x / x.shift(10) - 1)
        
        # 4. 前高计算
        lookback = self.config['strength_events']['lookback_high']
        df['high_20'] = g['high'].transform(lambda x: x.rolling(lookback, min_periods=lookback//2).max())
        df['is_near_high'] = (df['close'] >= df['high_20'] * 
                              self.config['strength_events']['breakout_price_ratio']).astype(int)
        
        # 5. 量能计算
        df['ma_vol_5'] = g['vol'].transform(lambda x: x.rolling(5, min_periods=3).mean())
        df['ma_vol_20'] = g['vol'].transform(lambda x: x.rolling(20, min_periods=10).mean())
        df['volume_ratio'] = df['vol'] / df['ma_vol_5'].clip(lower=1)
        
        # 6. 成交额计算
        df['ma_amount_20'] = g['amount'].transform(lambda x: x.rolling(20, min_periods=10).mean())
        
        # 7. 均线计算
        df['ma5'] = g['close'].transform(lambda x: x.rolling(5, min_periods=3).mean())
        df['ma10'] = g['close'].transform(lambda x: x.rolling(10, min_periods=5).mean())
        
        # 8. 趋势斜率
        slope_lookback = self.config['trend_direction']['ma10_slope_lookback']
        df['ma10_slope'] = g['ma10'].transform(lambda x: x - x.shift(slope_lookback))
        
        # 9. 上市天数
        if 'list_date' in df.columns and not df['list_date'].isnull().all():
            df['listed_days'] = (df['trade_date'] - df['list_date']).dt.days
        else:
            df['listed_days'] = g.cumcount() + 1
        
        # 10. 板块过滤标识
        code_str = df['ts_code'].astype(str)
        df['is_main_board'] = (
            code_str.str.startswith(tuple(self.config['base_filter']['sh_prefixes'])) |
            code_str.str.startswith(tuple(self.config['base_filter']['sz_prefixes']))
        )
        
        # 11. 风险过滤标识
        if 'is_st' not in df.columns:
            if 'name' in df.columns:
                df['is_st'] = df['name'].astype(str).str.contains('ST|\\*ST|退', regex=True).astype(int)
            else:
                df['is_st'] = 0
        
        if 'is_suspended' not in df.columns:
            # 简单判断停牌: 成交量为0或极小
            df['is_suspended'] = (df['vol'].fillna(0) <= 100).astype(int)
        
        # 12. 跌停判断
        df['is_limit_down'] = (df['pct_chg'] <= -9.5).astype(int)
        df['count_limit_down_20'] = g['is_limit_down'].transform(lambda x: x.rolling(20, min_periods=10).sum())
        
        # 13. 添加强势事件上下文
        df = self._add_strength_context(df)
        
        # 填充NaN值
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        df[numeric_cols] = df[numeric_cols].fillna(0)
        
        logger.info(f"特征数据准备完成, 数据形状: {df.shape}")
        return df
    
    def _add_strength_context(self, df: pd.DataFrame) -> pd.DataFrame:
        """添加强势事件上下文信息"""
        df = df.copy()
        
        result = []
        
        for code, sub in df.groupby('ts_code'):
            sub = sub.sort_values('trade_date').reset_index(drop=True).copy()
            
            # 初始化列
            sub['last_strength_idx'] = np.nan
            sub['days_since_last_strength'] = np.nan
            sub['strength_type'] = ''
            sub['close_d0'] = np.nan
            sub['peak_close_since_d0'] = np.nan
            
            # 找到所有强势日
            strength_indices = []
            strength_types = []
            
            for i in range(len(sub)):
                # 检查是否满足强势条件
                is_strength = False
                strength_type = []
                
                # 涨停
                if sub.iloc[i]['count_limit_up_10'] >= self.config['strength_events']['limit_up_count_10_min']:
                    is_strength = True
                    strength_type.append('limit_up')
                
                # 5日涨幅≥5%
                if sub.iloc[i]['return_5'] >= self.config['strength_events']['return_5_min']:
                    is_strength = True
                    strength_type.append('return_5')
                
                # 10日涨幅≥8%
                if sub.iloc[i]['return_10'] >= self.config['strength_events']['return_10_min']:
                    is_strength = True
                    strength_type.append('return_10')
                
                # 放量突破
                if (sub.iloc[i]['is_near_high'] == 1 and 
                    sub.iloc[i]['volume_ratio'] >= self.config['strength_events']['breakout_volume_ratio']):
                    is_strength = True
                    strength_type.append('breakout')
                
                if is_strength:
                    strength_indices.append(i)
                    strength_types.append('|'.join(strength_type))
            
            if not strength_indices:
                result.append(sub)
                continue
            
            # 为每一天找到最近的强势日
            for i in range(len(sub)):
                # 找到最近的强势日(在i之前)
                recent_strength = [idx for idx in strength_indices if idx < i]
                if recent_strength:
                    last_idx = recent_strength[-1]
                    sub.loc[i, 'last_strength_idx'] = last_idx
                    sub.loc[i, 'days_since_last_strength'] = i - last_idx
                    sub.loc[i, 'strength_type'] = strength_types[strength_indices.index(last_idx)]
                    sub.loc[i, 'close_d0'] = sub.loc[last_idx, 'close']
                    
                    # 强势后最高收盘价
                    if last_idx <= i:
                        sub.loc[i, 'peak_close_since_d0'] = sub.loc[last_idx:i+1, 'close'].max()
            
            result.append(sub)
        
        result_df = pd.concat(result, axis=0).reset_index(drop=True)
        
        # 计算回撤
        result_df['drawdown'] = 1 - result_df['close'] / result_df['peak_close_since_d0']
        result_df['drawdown'] = result_df['drawdown'].fillna(0)
        
        # 计算回调速度
        result_df['return_3'] = result_df.groupby('ts_code')['close'].transform(
            lambda x: x / x.shift(3) - 1
        )
        result_df['return_10_since_strength'] = result_df.groupby('ts_code')['close'].transform(
            lambda x: x / x.shift(10) - 1
        )
        
        # 避免除零
        result_df['decay_ratio'] = np.where(
            result_df['return_10_since_strength'] != 0,
            abs(result_df['return_3']) / abs(result_df['return_10_since_strength']),
            0
        )
        
        # 计算下跌天数比例
        result_df['is_down_day'] = (result_df['ret'] < 0).astype(int)
        result_df['down_days_ratio'] = result_df.groupby('ts_code')['is_down_day'].transform(
            lambda x: x.rolling(5, min_periods=3).mean()
        )
        
        return result_df
    
    def apply_base_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        """Step 1: 应用基础过滤"""
        cfg = self.config['base_filter']
        
        cond = (
            df['is_main_board'] &
            (df['is_st'] == 0) &
            (df['is_suspended'] == 0) &
            (df['listed_days'] >= cfg['min_listing_days']) &
            (df['close'] >= cfg['min_price']) &
            (df['ma_amount_20'].between(cfg['min_avg_amount_20'], cfg['max_avg_amount_20'])) &
            (df['count_limit_down_20'] <= cfg['max_limit_down_20'])
        )
        
        filtered = df[cond].copy()
        logger.info(f"基础过滤后: {len(filtered)}/{len(df)}")
        return filtered
    
    def apply_strength_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        """Step 2: 应用强势过滤(OR逻辑)"""
        cfg = self.config['strength_events']
        
        cond = (
            (df['count_limit_up_10'] >= cfg['limit_up_count_10_min']) |
            (df['return_5'] >= cfg['return_5_min']) |
            (df['return_10'] >= cfg['return_10_min']) |
            ((df['is_near_high'] == 1) & 
             (df['volume_ratio'] >= cfg['breakout_volume_ratio']))
        )
        
        filtered = df[cond].copy()
        logger.info(f"强势过滤后: {len(filtered)}/{len(df)}")
        return filtered
    
    def apply_pullback_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        """Step 3: 应用回调结构过滤"""
        cfg = self.config['pullback_structure']
        
        # 必须有强势事件
        cond = (df['days_since_last_strength'] >= cfg['days_range'][0]) & \
               (df['days_since_last_strength'] <= cfg['days_range'][1])
        
        # 回撤幅度
        cond = cond & (df['drawdown'] >= cfg['drawdown_range'][0]) & \
               (df['drawdown'] <= cfg['drawdown_range'][1])
        
        # 回调速度
        cond = cond & (df['decay_ratio'] <= cfg['decay_ratio_max'])
        
        # 下跌天数比例
        cond = cond & (df['down_days_ratio'] <= cfg['down_days_ratio_max'])
        
        filtered = df[cond].copy()
        logger.info(f"回调过滤后: {len(filtered)}/{len(df)}")
        return filtered
    
    def apply_volume_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        """Step 4: 应用缩量确认"""
        cfg = self.config['volume_condition']
        
        cond = (df['volume_ratio'] <= cfg['volume_shrink_ratio'])
        
        filtered = df[cond].copy()
        logger.info(f"缩量过滤后: {len(filtered)}/{len(df)}")
        return filtered
    
    def apply_trend_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        """Step 5: 应用趋势结构过滤"""
        cfg = self.config['trend_structure']
        
        cond = (df['ma5'] > df['ma10']) if cfg['ma5_above_ma10'] else True
        cond = cond & (df['close'] >= df['ma10'] * cfg['close_above_ma10_ratio'])
        cond = cond & (abs(df['close'] - df['ma5']) / df['ma5'] <= cfg['close_near_ma5_pct'])
        
        filtered = df[cond].copy()
        logger.info(f"趋势过滤后: {len(filtered)}/{len(df)}")
        return filtered
    
    def apply_trend_direction_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        """Step 6: 应用趋势方向过滤"""
        cfg = self.config['trend_direction']
        
        cond = (df['ma10_slope'] >= cfg['ma10_slope_min'])
        
        filtered = df[cond].copy()
        logger.info(f"趋势方向过滤后: {len(filtered)}/{len(df)}")
        return filtered
    
    def apply_comprehensive_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        """Step 7: 应用综合过滤"""
        # 确保有强势事件
        cond = (df['strength_type'] != '')
        
        # 确保回调天数合理
        cond = cond & (df['days_since_last_strength'] >= 2)
        
        filtered = df[cond].copy()
        logger.info(f"综合过滤后: {len(filtered)}/{len(df)}")
        return filtered
    
    def calculate_scores(self, df: pd.DataFrame) -> pd.DataFrame:
        """Step 8: 计算综合评分"""
        cfg = self.config['scoring']
        df = df.copy()
        
        # 强势评分
        strength_score = np.zeros(len(df))
        
        # 涨停次数
        strength_score += df['count_limit_up_10'].clip(upper=5) * 5
        
        # 涨幅
        strength_score += np.clip(df['return_5'] * 100, 0, 20)
        strength_score += np.clip(df['return_10'] * 100, 0, 20)
        
        # 放量突破
        strength_score += (df['is_near_high'] == 1).astype(int) * 10
        strength_score += np.clip((df['volume_ratio'] - 1) * 10, 0, 10)
        
        # 回调评分
        pullback_score = np.zeros(len(df))
        
        # 回调天数(2-7天最佳)
        days_score = np.where(
            (df['days_since_last_strength'] >= 2) & (df['days_since_last_strength'] <= 5),
            20,
            np.where(
                (df['days_since_last_strength'] >= 6) & (df['days_since_last_strength'] <= 7),
                15,
                10
            )
        )
        pullback_score += days_score
        
        # 回撤幅度(3%-8%最佳)
        drawdown_score = np.where(
            (df['drawdown'] >= 0.03) & (df['drawdown'] <= 0.08),
            20,
            np.where(
                (df['drawdown'] >= 0.01) & (df['drawdown'] <= 0.10),
                15,
                10
            )
        )
        pullback_score += drawdown_score
        
        # 趋势评分
        trend_score = np.zeros(len(df))
        
        # 均线多头排列
        ma_score = np.where(
            (df['ma5'] > df['ma10']) & (df['ma10'] > df['ma5'].shift(1)),
            15,
            np.where(df['ma5'] > df['ma10'], 10, 5)
        )
        trend_score += ma_score
        
        # 价格在均线上方
        trend_score += np.where(df['close'] > df['ma10'], 10, 5)
        
        # 量能评分
        volume_score = np.zeros(len(df))
        
        # 缩量程度
        volume_score += np.where(
            df['volume_ratio'] <= 0.7,
            20,
            np.where(df['volume_ratio'] <= 0.9, 15, 10)
        )
        
        # 成交额稳定性
        volume_score += np.where(
            df['ma_amount_20'] >= 1e8,
            10,
            np.where(df['ma_amount_20'] >= 5e7, 7, 5)
        )
        
        # 计算总分
        df['strength_score'] = strength_score
        df['pullback_score'] = pullback_score
        df['trend_score'] = trend_score
        df['volume_score'] = volume_score
        
        df['total_score'] = (
            df['strength_score'] * cfg['strength_weight'] +
            df['pullback_score'] * cfg['pullback_weight'] +
            df['trend_score'] * cfg['trend_weight'] +
            df['volume_score'] * cfg['volume_weight']
        )
        
        return df
    
    def select_candidates(self, df: pd.DataFrame, date: str = None) -> pd.DataFrame:
        """
        选择候选股票
        
        Args:
            df: 原始数据DataFrame
            date: 选股日期
            
        Returns:
            候选股票DataFrame
        """
        logger.info("开始选股...")
        
        # 准备特征
        df_features = self.prepare_features(df)
        
        if date:
            df_features = df_features[df_features['trade_date'] == pd.to_datetime(date)]
        
        if len(df_features) == 0:
            logger.warning("没有数据可用于选股")
            return pd.DataFrame()
        
        # 应用过滤
        print("\n" + "=" * 80)
        print("修复版最终实盘策略 - 过滤层统计")
        print("=" * 80)
        print(f"初始股票数: {len(df_features)}")
        
        # Step 1: 基础过滤
        df_filtered = self.apply_base_filter(df_features)
        print(f"1. 基础过滤后: {len(df_filtered)}")
        
        if len(df_filtered) == 0:
            print("基础过滤后无股票, 检查条件是否过严")
            return pd.DataFrame()
        
        # Step 2: 强势过滤
        df_filtered = self.apply_strength_filter(df_filtered)
        print(f"2. 强势过滤后: {len(df_filtered)}")
        
        if len(df_filtered) == 0:
            print("强势过滤后无股票, 市场可能缺乏强势股")
            return pd.DataFrame()
        
        # Step 3: 回调过滤
        df_filtered = self.apply_pullback_filter(df_filtered)
        print(f"3. 回调过滤后: {len(df_filtered)}")
        
        if len(df_filtered) == 0:
            print("回调过滤后无股票, 可能没有合适的回调结构")
            return pd.DataFrame()
        
        # Step 4: 缩量过滤
        df_filtered = self.apply_volume_filter(df_filtered)
        print(f"4. 缩量过滤后: {len(df_filtered)}")
        
        if len(df_filtered) == 0:
            print("缩量过滤后无股票, 可能量能不符合要求")
            return pd.DataFrame()
        
        # Step 5: 趋势过滤
        df_filtered = self.apply_trend_filter(df_filtered)
        print(f"5. 趋势过滤后: {len(df_filtered)}")
        
        if len(df_filtered) == 0:
            print("趋势过滤后无股票, 趋势结构不符合要求")
            return pd.DataFrame()
        
        # Step 6: 趋势方向过滤
        df_filtered = self.apply_trend_direction_filter(df_filtered)
        print(f"6. 趋势方向过滤后: {len(df_filtered)}")
        
        if len(df_filtered) == 0:
            print("趋势方向过滤后无股票, 趋势方向不符合要求")
            return pd.DataFrame()
        
        # Step 7: 综合过滤
        df_filtered = self.apply_comprehensive_filter(df_filtered)
        print(f"7. 综合过滤后: {len(df_filtered)}")
        
        if len(df_filtered) == 0:
            print("综合过滤后无股票")
            return pd.DataFrame()
        
        # Step 8: 评分排序
        df_scored = self.calculate_scores(df_filtered)
        
        # 过滤最低分
        min_score = self.config['scoring']['min_total_score']
        df_scored = df_scored[df_scored['total_score'] >= min_score]
        print(f"8. 评分过滤后(≥{min_score}分): {len(df_scored)}")
        
        # 排序
        sort_by = self.config['selection']['sort_by']
        df_scored = df_scored.sort_values(sort_by, ascending=False)
        
        # 限制数量
        max_candidates = self.config['selection']['max_candidates']
        candidates = df_scored.head(max_candidates)
        
        print(f"最终候选: {len(candidates)}")
        print("=" * 80)
        
        logger.info(f"选股完成, 找到{len(candidates)}只候选股票")
        return candidates
    
    def get_buy_points(self, candidates: pd.DataFrame) -> pd.DataFrame:
        """
        生成买点建议
        
        Args:
            candidates: 候选股票DataFrame
            
        Returns:
            买点建议DataFrame
        """
        if len(candidates) == 0:
            return pd.DataFrame()
        
        buy_points = []
        
        for _, row in candidates.iterrows():
            # 买点类型判断
            buy_type = []
            buy_price = row['close']
            buy_reason = []
            
            # 1. 回踩MA5买点
            if abs(row['close'] - row['ma5']) / row['ma5'] <= 0.02:
                buy_type.append('回踩MA5')
                buy_price = min(buy_price, row['ma5'] * 1.01)
                buy_reason.append(f"价格接近MA5({row['ma5']:.2f})")
            
            # 2. 突破前高买点
            if row['is_near_high'] == 1 and row['volume_ratio'] >= 1.2:
                buy_type.append('突破前高')
                buy_price = min(buy_price, row['high_20'] * 1.01)
                buy_reason.append(f"突破前高({row['high_20']:.2f})且放量")
            
            # 3. 缩量企稳买点
            if row['volume_ratio'] <= 0.8 and row['close'] > row['ma10']:
                buy_type.append('缩量企稳')
                buy_price = min(buy_price, row['close'] * 0.99)
                buy_reason.append(f"缩量企稳于MA10({row['ma10']:.2f})上方")
            
            # 默认买点
            if not buy_type:
                buy_type.append('趋势跟随')
                buy_price = row['close']
                buy_reason.append(f"趋势良好,回调到位")
            
            buy_points.append({
                'ts_code': row['ts_code'],
                'name': row.get('name', ''),
                'close': row['close'],
                'strength_type': row.get('strength_type', ''),
                'days_since_strength': row.get('days_since_last_strength', 0),
                'drawdown': row.get('drawdown', 0),
                'volume_ratio': row.get('volume_ratio', 1),
                'ma5': row.get('ma5', 0),
                'ma10': row.get('ma10', 0),
                'total_score': row.get('total_score', 0),
                'buy_type': '|'.join(buy_type),
                'buy_price': buy_price,
                'buy_reason': '; '.join(buy_reason)
            })
        
        return pd.DataFrame(buy_points)
