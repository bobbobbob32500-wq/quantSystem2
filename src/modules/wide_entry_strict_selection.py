"""
宽进严选策略框架
基于ChatGPT建议的完整实现
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Tuple, Optional
import logging
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

logger = logging.getLogger(__name__)


class WideEntryStrictSelection:
    """宽进严选策略框架"""
    
    def __init__(self, config: Dict = None):
        """
        初始化策略
        
        Args:
            config: 策略配置字典
        """
        self.config = config or self._get_default_config()
        logger.info("宽进严选策略框架初始化完成")
    
    def _get_default_config(self) -> Dict:
        """获取默认配置"""
        return {
            # ① 基础过滤（硬规则）
            'basic_filter': {
                'sh_prefixes': ['600', '601', '603', '605'],
                'sz_prefixes': ['000', '001', '002'],
                'exclude_prefixes': ['300', '688', '8'],
                'min_listing_days': 60,
                'min_price': 3.0,
                'min_avg_amount_20': 5e7,  # 5000万
                'max_avg_amount_20': 5e9,   # 50亿
                'max_limit_down_20': 2,
            },
            
            # ② 强势宽入口（OR逻辑）
            'strength_events': {
                'limit_up_count_10_min': 1,  # 10日内涨停次数≥1
                'return_5_min': 0.08,        # 5日涨幅≥8%
                'return_10_min': 0.12,       # 10日涨幅≥12%
                'breakout_price_ratio': 0.98,  # 接近前高98%
                'breakout_volume_ratio': 1.5,  # 放量1.5倍
                'lookback_high': 20,         # 前高计算周期
            },
            
            # ③ 回调结构（核心筛选）
            'pullback_structure': {
                'days_range': [2, 7],        # 回调2-7天
                'drawdown_range': [0.01, 0.10],  # 回撤1%-10%
                'decay_ratio_max': 0.7,      # 回调速度≤0.7
                'down_days_ratio_max': 0.8,  # 下跌天数比例≤80%
            },
            
            # ④ 缩量条件
            'volume_condition': {
                'volume_shrink_ratio': 0.9,  # 量比≤0.9
                'lookback_volume': 5,        # 5日均量
            },
            
            # ⑤ 趋势结构
            'trend_structure': {
                'ma5_above_ma10': True,
                'close_above_ma10_ratio': 0.99,  # 收盘≥MA10的99%
                'close_near_ma5_pct': 0.03,      # 收盘在MA5的±3%内
                'ma10_slope_min': 0.0,          # MA10斜率≥0
                'ma5_slope_min': 0.0,           # MA5斜率≥0
                'slope_lookback': 3,            # 斜率计算周期
            },
            
            # ⑥ 波动过滤
            'volatility_filter': {
                'atr10_ratio_max': 0.10,       # ATR10/收盘价≤10%
                'avg_range_10_max': 0.15,      # 10日平均振幅≤15%
            },
            
            # 评分系统
            'scoring': {
                'strength_weight': 0.30,
                'pullback_weight': 0.30,
                'trend_weight': 0.20,
                'volume_weight': 0.20,
                'min_total_score': 60,         # 最低总分
            },
            
            # 选股控制
            'selection': {
                'max_candidates': 15,
                'sort_by': 'total_score',
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
        logger.info("开始准备特征数据...")
        df = df.copy()
        
        # 确保日期格式
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        if 'list_date' in df.columns:
            df['list_date'] = pd.to_datetime(df['list_date'], errors='coerce')
        
        # 按股票代码和日期排序
        df = df.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
        
        # 按股票分组计算
        g = df.groupby('ts_code', group_keys=False)
        
        # 1. 基础字段
        df['prev_close'] = g['close'].shift(1)
        df['ret'] = df['close'] / df['prev_close'] - 1
        df['pct_chg'] = df['ret'] * 100  # 百分比
        
        # 2. 涨停检测
        df['is_limit_up'] = (df['pct_chg'] >= 9.5).astype(int)
        df['count_limit_up_10'] = g['is_limit_up'].transform(lambda x: x.rolling(10, min_periods=5).sum())
        
        # 3. 均线计算
        df['ma5'] = g['close'].transform(lambda x: x.rolling(5, min_periods=3).mean())
        df['ma10'] = g['close'].transform(lambda x: x.rolling(10, min_periods=5).mean())
        df['ma20'] = g['close'].transform(lambda x: x.rolling(20, min_periods=10).mean())
        
        # 4. 量能计算
        df['ma_vol_5'] = g['vol'].transform(lambda x: x.rolling(5, min_periods=3).mean())
        df['ma_vol_20'] = g['vol'].transform(lambda x: x.rolling(20, min_periods=10).mean())
        df['volume_ratio'] = df['vol'] / df['ma_vol_5'].clip(lower=1)
        
        # 5. 成交额计算
        df['ma_amount_20'] = g['amount'].transform(lambda x: x.rolling(20, min_periods=10).mean())
        
        # 6. 上市天数
        if 'list_date' in df.columns:
            df['listed_days'] = (df['trade_date'] - df['list_date']).dt.days
        else:
            df['listed_days'] = g.cumcount() + 1
        
        # 7. 板块过滤标识
        code_str = df['ts_code'].astype(str)
        df['is_main_board'] = (
            code_str.str.startswith(tuple(self.config['basic_filter']['sh_prefixes'])) |
            code_str.str.startswith(tuple(self.config['basic_filter']['sz_prefixes']))
        )
        
        # 8. 风险过滤标识
        if 'is_st' not in df.columns:
            if 'name' in df.columns:
                df['is_st'] = df['name'].astype(str).str.contains('ST|\\*ST|退', regex=True).astype(int)
            else:
                df['is_st'] = 0
        
        if 'is_suspended' not in df.columns:
            df['is_suspended'] = (df['vol'].fillna(0) <= 100).astype(int)
        
        # 9. 跌停判断
        df['is_limit_down'] = (df['pct_chg'] <= -9.5).astype(int)
        df['count_limit_down_20'] = g['is_limit_down'].transform(lambda x: x.rolling(20, min_periods=10).sum())
        
        # 10. 涨幅计算
        df['return_5'] = g['close'].transform(lambda x: x / x.shift(5) - 1)
        df['return_10'] = g['close'].transform(lambda x: x / x.shift(10) - 1)
        
        # 11. 前高计算
        lookback = self.config['strength_events']['lookback_high']
        df['high_20'] = g['high'].transform(lambda x: x.rolling(lookback, min_periods=lookback//2).max())
        df['is_near_high'] = (df['close'] >= df['high_20'] * 
                              self.config['strength_events']['breakout_price_ratio']).astype(int)
        
        # 12. 趋势斜率
        slope_lookback = self.config['trend_structure']['slope_lookback']
        df['ma10_slope'] = g['ma10'].transform(lambda x: x - x.shift(slope_lookback))
        df['ma5_slope'] = g['ma5'].transform(lambda x: x - x.shift(slope_lookback))
        
        # 13. 波动率计算
        # ATR计算
        df['tr'] = np.maximum(
            df['high'] - df['low'],
            np.maximum(
                abs(df['high'] - df['prev_close']),
                abs(df['low'] - df['prev_close'])
            )
        )
        df['atr10'] = g['tr'].transform(lambda x: x.rolling(10, min_periods=5).mean())
        df['atr_ratio'] = df['atr10'] / df['close']
        
        # 平均振幅
        df['daily_range'] = (df['high'] - df['low']) / df['close']
        df['avg_range_10'] = g['daily_range'].transform(lambda x: x.rolling(10, min_periods=5).mean())
        
        # 14. 回调相关特征
        # 计算最近强势日
        df = self._add_strength_context(df)
        
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
            sub['ret_d0_next'] = np.nan
            sub['peak_close_since_d0'] = np.nan
            
            # 找到所有强势日
            strength_indices = []
            strength_types = []
            
            for i in range(len(sub)):
                # 检查是否满足强势条件
                is_strength = False
                strength_type = []
                
                # 涨停
                if sub.iloc[i]['is_limit_up'] == 1:
                    is_strength = True
                    strength_type.append('limit_up')
                
                # 5日涨幅≥8%
                if sub.iloc[i]['return_5'] >= self.config['strength_events']['return_5_min']:
                    is_strength = True
                    strength_type.append('return_5')
                
                # 10日涨幅≥12%
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
                    
                    # 强势次日收益率
                    if last_idx + 1 < len(sub):
                        sub.loc[i, 'ret_d0_next'] = (
                            sub.loc[last_idx + 1, 'close'] / sub.loc[last_idx, 'close'] - 1
                        )
                    
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
    
    def apply_basic_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        """应用基础过滤"""
        logger.info("应用基础过滤...")
        cfg = self.config['basic_filter']
        
        cond = (
            df['is_main_board'] &
            (df['is_st'] == 0) &
            (df['is_suspended'] == 0) &
            (df['listed_days'] >= cfg['min_listing_days']) &
            (df['close'] >= cfg['min_price']) &
            (df['ma_amount_20'].between(cfg['min_avg_amount_20'], cfg['max_avg_amount_20'])) &
            (df['count_limit_down_20'] <= cfg['max_limit_down_20'])
        )
        
        df['basic_filter_pass'] = cond.astype(int)
        logger.info(f"基础过滤通过: {cond.sum()}/{len(df)} ({cond.sum()/len(df):.2%})")
        
        return df
    
    def apply_strength_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        """应用强势宽入口过滤"""
        logger.info("应用强势宽入口过滤...")
        cfg = self.config['strength_events']
        
        # OR逻辑: 满足任一条件即可
        cond = (
            (df['count_limit_up_10'] >= cfg['limit_up_count_10_min']) |  # 有涨停
            (df['return_5'] >= cfg['return_5_min']) |                    # 5日涨幅≥8%
            (df['return_10'] >= cfg['return_10_min']) |                  # 10日涨幅≥12%
            ((df['is_near_high'] == 1) &                                 # 放量突破
             (df['volume_ratio'] >= cfg['breakout_volume_ratio']))
        )
        
        df['strength_filter_pass'] = cond.astype(int)
        logger.info(f"强势过滤通过: {cond.sum()}/{len(df)} ({cond.sum()/len(df):.2%})")
        
        return df
    
    def apply_pullback_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        """应用回调结构过滤"""
        logger.info("应用回调结构过滤...")
        cfg = self.config['pullback_structure']
        
        # 必须有强势事件
        has_strength = df['last_strength_idx'].notna()
        
        # 回调时间
        cond_days = df['days_since_last_strength'].between(
            cfg['days_range'][0], cfg['days_range'][1]
        )
        
        # 回撤幅度
        cond_drawdown = df['drawdown'].between(
            cfg['drawdown_range'][0], cfg['drawdown_range'][1]
        )
        
        # 回调速度
        cond_decay = df['decay_ratio'] <= cfg['decay_ratio_max']
        
        # 下跌天数比例
        cond_down_days = df['down_days_ratio'] <= cfg['down_days_ratio_max']
        
        cond = has_strength & cond_days & cond_drawdown & cond_decay & cond_down_days
        
        df['pullback_filter_pass'] = cond.astype(int)
        logger.info(f"回调过滤通过: {cond.sum()}/{len(df)} ({cond.sum()/len(df):.2%})")
        
        return df
    
    def apply_volume_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        """应用缩量过滤"""
        logger.info("应用缩量过滤...")
        cfg = self.config['volume_condition']
        
        cond = df['volume_ratio'] <= cfg['volume_shrink_ratio']
        
        df['volume_filter_pass'] = cond.astype(int)
        logger.info(f"缩量过滤通过: {cond.sum()}/{len(df)} ({cond.sum()/len(df):.2%})")
        
        return df
    
    def apply_trend_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        """应用趋势结构过滤"""
        logger.info("应用趋势结构过滤...")
        cfg = self.config['trend_structure']
        
        cond = (
            (df['ma5'] > df['ma10']) &  # MA5>MA10
            (df['close'] >= df['ma10'] * cfg['close_above_ma10_ratio']) &  # 收盘≥MA10*0.99
            ((df['close'] / df['ma5'] - 1).abs() <= cfg['close_near_ma5_pct']) &  # 收盘接近MA5
            (df['ma10_slope'] >= cfg['ma10_slope_min']) &  # MA10斜率≥0
            (df['ma5_slope'] >= cfg['ma5_slope_min'])      # MA5斜率≥0
        )
        
        df['trend_filter_pass'] = cond.astype(int)
        logger.info(f"趋势过滤通过: {cond.sum()}/{len(df)} ({cond.sum()/len(df):.2%})")
        
        return df
    
    def apply_volatility_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        """应用波动过滤"""
        logger.info("应用波动过滤...")
        cfg = self.config['volatility_filter']
        
        cond = (
            (df['atr_ratio'] <= cfg['atr10_ratio_max']) &
            (df['avg_range_10'] <= cfg['avg_range_10_max'])
        )
        
        df['volatility_filter_pass'] = cond.astype(int)
        logger.info(f"波动过滤通过: {cond.sum()}/{len(df)} ({cond.sum()/len(df):.2%})")
        
        return df
    
    def calculate_scores(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算综合评分"""
        logger.info("计算综合评分...")
        cfg = self.config['scoring']
        
        # 1. 强势分
        df['strength_score'] = np.clip(df['return_5'] / 0.15, 0, 1) * 100
        
        # 2. 回调分
        ideal_drawdown = 0.05
        df['pullback_score'] = (1 - abs(df['drawdown'] - ideal_drawdown) / ideal_drawdown) * 100
        df['pullback_score'] = np.clip(df['pullback_score'], 0, 100)
        
        # 3. 趋势分
        df['trend_score'] = ((df['ma5'] - df['ma10']) / df['ma10'] * 100).clip(lower=0, upper=100)
        
        # 4. 成交量分
        df['volume_score'] = (1 - df['volume_ratio']) * 100
        df['volume_score'] = np.clip(df['volume_score'], 0, 100)
        
        # 5. 综合评分
        df['total_score'] = (
            cfg['strength_weight'] * df['strength_score'] +
            cfg['pullback_weight'] * df['pullback_score'] +
            cfg['trend_weight'] * df['trend_score'] +
            cfg['volume_weight'] * df['volume_score']
        )
        
        logger.info(f"评分计算完成, 平均分: {df['total_score'].mean():.1f}")
        return df
    
    def run_strategy(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        运行完整策略流程
        
        Args:
            df: 原始数据DataFrame
            
        Returns:
            包含信号和评分的DataFrame
        """
        logger.info("开始运行宽进严选策略...")
        
        # 1. 准备特征
        df_features = self.prepare_features(df)
        
        # 2. 应用各层过滤
        df_filtered = df_features.copy()
        
        # 调试输出
        print("\n" + "=" * 80)
        print("宽进严选策略 - 过滤层统计")
        print("=" * 80)
        print(f"初始股票数: {len(df_filtered)}")
        
        # 基础过滤
        df_filtered = self.apply_basic_filter(df_filtered)
        df_basic = df_filtered[df_filtered['basic_filter_pass'] == 1].copy()
        print(f"基础过滤后: {len(df_basic)}")
        
        # 强势过滤
        df_basic = self.apply_strength_filter(df_basic)
        df_strength = df_basic[df_basic['strength_filter_pass'] == 1].copy()
        print(f"强势过滤后: {len(df_strength)}")
        
        # 回调过滤
        df_strength = self.apply_pullback_filter(df_strength)
        df_pullback = df_strength[df_strength['pullback_filter_pass'] == 1].copy()
        print(f"回调过滤后: {len(df_pullback)}")
        
        # 缩量过滤
        df_pullback = self.apply_volume_filter(df_pullback)
        df_volume = df_pullback[df_pullback['volume_filter_pass'] == 1].copy()
        print(f"缩量过滤后: {len(df_volume)}")
        
        # 趋势过滤
        df_volume = self.apply_trend_filter(df_volume)
        df_trend = df_volume[df_volume['trend_filter_pass'] == 1].copy()
        print(f"趋势过滤后: {len(df_trend)}")
        
        # 波动过滤
        df_trend = self.apply_volatility_filter(df_trend)
        df_final = df_trend[df_trend['volatility_filter_pass'] == 1].copy()
        print(f"波动过滤后: {len(df_final)}")
        
        # 3. 计算评分
        if len(df_final) > 0:
            df_final = self.calculate_scores(df_final)
            
            # 最低分过滤
            min_score = self.config['scoring']['min_total_score']
            df_final = df_final[df_final['total_score'] >= min_score].copy()
            print(f"最低分({min_score})过滤后: {len(df_final)}")
            
            # 生成信号
            df_final['signal'] = 1
            
            # 按评分排序
            sort_by = self.config['selection']['sort_by']
            max_candidates = self.config['selection']['max_candidates']
            
            if sort_by == 'total_score':
                df_final = df_final.sort_values('total_score', ascending=False)
            else:
                df_final = df_final.sort_values(['trade_date', 'ts_code'])
            
            if len(df_final) > max_candidates:
                df_final = df_final.head(max_candidates)
            
            print(f"最终候选: {len(df_final)}")
            
            # 合并回原始数据
            df_filtered['signal'] = 0
            df_filtered.loc[df_final.index, 'signal'] = 1
            df_filtered['total_score'] = 0
            df_filtered.loc[df_final.index, 'total_score'] = df_final['total_score']
            
        else:
            df_filtered['signal'] = 0
            df_filtered['total_score'] = 0
            print("最终候选: 0")
        
        print("=" * 80)
        logger.info("策略运行完成")
        
        return df_filtered
    
    def analyze_results(self, df: pd.DataFrame) -> Dict:
        """
        分析策略结果
        
        Args:
            df: 包含信号的DataFrame
            
        Returns:
            分析结果字典
        """
        if len(df) == 0:
            return {}
        
        # 按日期统计
        signals_by_date = df.groupby('trade_date')['signal'].sum()
        dates_with_signals = signals_by_date[signals_by_date > 0]
        
        # 按股票统计
        signals_by_stock = df.groupby('ts_code')['signal'].sum()
        stocks_with_signals = signals_by_stock[signals_by_stock > 0]
        
        # 分析过滤层通过率
        filter_stats = {}
        for filter_name in ['basic_filter_pass', 'strength_filter_pass', 
                          'pullback_filter_pass', 'volume_filter_pass',
                          'trend_filter_pass', 'volatility_filter_pass']:
            if filter_name in df.columns:
                pass_rate = df[filter_name].mean()
                filter_stats[filter_name] = {
                    '通过数': int(df[filter_name].sum()),
                    '通过率': float(pass_rate)
                }
        
        return {
            'total_signals': int(df['signal'].sum()),
            'dates_with_signals': len(dates_with_signals),
            'avg_signals_per_day': float(signals_by_date.mean()) if len(signals_by_date) > 0 else 0,
            'max_signals_per_day': int(signals_by_date.max()) if len(signals_by_date) > 0 else 0,
            'stocks_with_signals': len(stocks_with_signals),
            'avg_signals_per_stock': float(signals_by_stock.mean()) if len(signals_by_stock) > 0 else 0,
            'filter_stats': filter_stats
        }


# 使用示例
if __name__ == "__main__":
    # 创建策略引擎
    strategy = WideEntryStrictSelection()
    
    print("=" * 80)
    print("宽进严选策略框架")
    print("=" * 80)
    print("\n策略特点:")
    print("1. 宽进: 使用'强势事件集合'扩大样本入口")
    print("   - 涨停股")
    print("   - 5日涨幅≥8%")
    print("   - 10日涨幅≥12%")
    print("   - 放量突破前高")
    print("\n2. 严选: 多层质量过滤")
    print("   - 回调结构(2-7天,回撤1-10%)")
    print("   - 缩量确认(量比≤0.9)")
    print("   - 趋势结构(MA5>MA10,斜率向上)")
    print("   - 波动控制(ATR≤10%,振幅≤15%)")
    print("\n3. 评分排序: 综合评分选出最优候选")
    print("   - 强势分(30%): 基于5日涨幅")
    print("   - 回调分(30%): 基于回撤接近5%")
    print("   - 趋势分(20%): 基于均线多头排列")
    print("   - 量能分(20%): 基于缩量程度")
    print("=" * 80)
