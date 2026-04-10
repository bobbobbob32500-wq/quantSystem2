"""
强势回调二次启动策略 - 修正版
基于ChatGPT建议的关键问题修复
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional
import logging
import warnings
warnings.filterwarnings('ignore')

logger = logging.getLogger(__name__)


class StrongPullbackStrategyFixed:
    """强势回调二次启动策略 - 修正版"""
    
    def __init__(self, config: Dict = None):
        """
        初始化策略
        
        Args:
            config: 策略配置字典
        """
        self.config = config or self._get_default_config()
        logger.info("强势回调二次启动策略(修正版)初始化完成")
    
    def _get_default_config(self) -> Dict:
        """获取默认配置"""
        return {
            # Step 1: 基础过滤（硬条件）
            'base_filter': {
                'sh_prefixes': ['600', '601', '603', '605'],
                'sz_prefixes': ['000', '001', '002'],
                'min_listing_days': 60,
                'min_price': 2.0,           # 放宽到2元
                'min_avg_amount_20': 1e6,   # 100万（进一步放宽）
                'max_avg_amount_20': 1e10,  # 100亿（放宽上限）
                'max_limit_down_20': 3,      # 放宽到3次
            },
            
            # Step 2: 强势事件定义
            'strength_events': {
                'limit_up_pct': 9.5,               # 涨停阈值
                'strong_day_ret_min': 0.07,        # 单日强阳阈值7%
                'return_5_min': 0.08,              # 5日涨幅≥8%
                'return_10_min': 0.12,             # 10日涨幅≥12%
                'breakout_price_ratio': 0.98,      # 接近前高98%
                'breakout_volume_ratio': 1.2,      # 放量1.2倍
                'lookback_high': 20,               # 前高计算周期
            },
            
            # Step 3: 回调结构（核心筛选）
            'pullback_structure': {
                'days_range': [1, 10],             # 放宽到1-10天
                'drawdown_range': [0.005, 0.15],   # 放宽到0.5%-15%
                'decay_ratio_max': 1.0,            # 放宽到1.0
                'down_days_ratio_max': 0.8,        # 下跌天数比例≤80%
            },
            
            # Step 4: 缩量确认
            'volume_condition': {
                'volume_shrink_ratio': 0.9,        # 量比≤0.9
                'lookback_volume': 5,              # 5日均量
            },
            
            # Step 5: 趋势结构
            'trend_structure': {
                'close_above_ma10_ratio': 0.99,    # 收盘≥MA10的99%
                'close_near_ma5_pct': 0.05,        # 放宽到±5%
            },
            
            # Step 6: 趋势方向
            'trend_direction': {
                'ma10_slope_lookback': 3,          # MA10斜率计算周期
                'ma10_slope_min': 0.0,             # MA10斜率≥0
            },
            
            # Step 7: 评分排序
            'scoring': {
                'strength_weight': 0.30,
                'pullback_weight': 0.30,
                'trend_weight': 0.20,
                'volume_weight': 0.20,
                'min_total_score': 50,             # 最低总分
            },
            
            # 选股控制
            'selection': {
                'max_candidates': 15,              # 最多15只
                'sort_by': 'total_score',          # 按总分排序
            }
        }
    
    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        准备特征数据（修正版）
        关键修复：使用历史数据计算特征，避免单日数据问题
        """
        logger.info("开始准备特征...")
        df = df.copy()
        
        # 确保日期格式
        if 'trade_date' in df.columns:
            df['trade_date'] = pd.to_datetime(df['trade_date'], errors='coerce')
        if 'list_date' in df.columns:
            df['list_date'] = pd.to_datetime(df['list_date'], errors='coerce')
        
        # 按股票代码和日期排序
        df = df.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
        g = df.groupby('ts_code', group_keys=False)
        
        # --- 基础字段 ---
        df['prev_close'] = g['close'].shift(1)
        df['ret'] = df['close'] / df['prev_close'] - 1
        
        # 使用原始pct_chg或计算
        if 'pct_chg' not in df.columns or df['pct_chg'].isnull().all():
            df['pct_chg'] = df['ret'] * 100
        else:
            df['pct_chg'] = pd.to_numeric(df['pct_chg'], errors='coerce')
        
        # --- 涨停/跌停检测 ---
        limit_up_pct = self.config['strength_events']['limit_up_pct']
        df['is_limit_up'] = (df['pct_chg'] >= limit_up_pct).astype(int)
        df['is_limit_down'] = (df['pct_chg'] <= -limit_up_pct).astype(int)
        
        # 滚动计数（用于评分，不作为事件判断）
        df['count_limit_up_10'] = g['is_limit_up'].transform(
            lambda x: x.rolling(10, min_periods=1).sum()
        )
        df['count_limit_down_20'] = g['is_limit_down'].transform(
            lambda x: x.rolling(20, min_periods=1).sum()
        )
        
        # --- 涨幅计算 ---
        df['return_5'] = g['close'].transform(lambda x: x / x.shift(5) - 1)
        df['return_10'] = g['close'].transform(lambda x: x / x.shift(10) - 1)
        df['return_3'] = g['close'].transform(lambda x: x / x.shift(3) - 1)
        
        # --- 前高计算（关键修复：使用shift(1)避免包含当天）---
        lookback_high = self.config['strength_events']['lookback_high']
        df['high_20_prev'] = g['high'].transform(
            lambda x: x.shift(1).rolling(lookback_high, min_periods=10).max()
        )
        
        # --- 量能计算 ---
        df['ma_vol_5'] = g['vol'].transform(lambda x: x.rolling(5, min_periods=3).mean())
        df['ma_vol_20'] = g['vol'].transform(lambda x: x.rolling(20, min_periods=10).mean())
        df['volume_ratio'] = df['vol'] / df['ma_vol_5']
        
        # --- 成交额计算 ---
        df['ma_amount_20'] = g['amount'].transform(lambda x: x.rolling(20, min_periods=10).mean())
        
        # --- 均线计算 ---
        df['ma5'] = g['close'].transform(lambda x: x.rolling(5, min_periods=5).mean())
        df['ma10'] = g['close'].transform(lambda x: x.rolling(10, min_periods=10).mean())
        
        # 均线前值（用于趋势判断）
        df['ma5_prev'] = g['ma5'].shift(1)
        df['ma10_prev'] = g['ma10'].shift(1)
        
        # --- MA10斜率 ---
        slope_lb = self.config['trend_direction']['ma10_slope_lookback']
        df['ma10_slope'] = df['ma10'] - g['ma10'].shift(slope_lb)
        
        # --- 上市天数 ---
        if 'list_date' in df.columns and not df['list_date'].isnull().all():
            df['listed_days'] = (df['trade_date'] - df['list_date']).dt.days
        else:
            df['listed_days'] = g.cumcount() + 1
        
        # --- 主板识别 ---
        code_str = df['ts_code'].astype(str)
        sh_prefixes = tuple(self.config['base_filter']['sh_prefixes'])
        sz_prefixes = tuple(self.config['base_filter']['sz_prefixes'])
        df['is_main_board'] = code_str.str.startswith(sh_prefixes) | code_str.str.startswith(sz_prefixes)
        
        # --- ST识别 ---
        if 'is_st' not in df.columns:
            if 'name' in df.columns:
                df['is_st'] = df['name'].astype(str).str.contains(r'ST|\*ST|退', regex=True).astype(int)
            else:
                df['is_st'] = 0
        
        # --- 停牌判断（改进版）---
        if 'is_suspended' not in df.columns:
            df['is_suspended'] = (
                (df['vol'].fillna(0) <= 0) |
                df['open'].isna() |
                df['close'].isna()
            ).astype(int)
        
        # --- 接近前高（使用前高）---
        df['is_near_high'] = (
            df['high_20_prev'].notna() &
            (df['close'] >= df['high_20_prev'] * self.config['strength_events']['breakout_price_ratio'])
        ).astype(int)
        
        # --- 强势事件日识别（关键修复：只标记当天事件）---
        df = self._mark_strength_event(df)
        
        # --- 添加强势上下文 ---
        df = self._add_strength_context(df)
        
        # --- 回调结构辅助 ---
        df['is_down_day'] = (df['ret'] < 0).astype(int)
        df['down_days_ratio'] = df.groupby('ts_code')['is_down_day'].transform(
            lambda x: x.rolling(5, min_periods=3).mean()
        )
        
        logger.info(f"特征准备完成: {df.shape}")
        return df
    
    def _mark_strength_event(self, df: pd.DataFrame) -> pd.DataFrame:
        """标记强势事件日（关键修复：只标记当天事件）"""
        cfg = self.config['strength_events']
        df = df.copy()
        
        # 强势突破
        df['is_strong_breakout'] = (
            df['high_20_prev'].notna() &
            (df['close'] >= df['high_20_prev'] * cfg['breakout_price_ratio']) &
            (df['volume_ratio'] >= cfg['breakout_volume_ratio'])
        ).astype(int)
        
        # 强势事件日（当天发生的事件）
        df['is_strong_day'] = (
            (df['is_limit_up'] == 1) |
            (df['ret'] >= cfg['strong_day_ret_min']) |
            (df['is_strong_breakout'] == 1)
        ).astype(int)
        
        return df
    
    def _add_strength_context(self, df: pd.DataFrame) -> pd.DataFrame:
        """添加强势上下文信息（关键修复：正确计算回调基准）"""
        result = []
        
        for code, sub in df.groupby('ts_code'):
            sub = sub.sort_values('trade_date').reset_index(drop=True).copy()
            
            # 初始化列
            sub['last_strength_idx'] = np.nan
            sub['strength_event_date'] = pd.NaT
            sub['days_since_last_strength'] = np.nan
            sub['close_d0'] = np.nan
            sub['peak_close_since_d0'] = np.nan
            sub['strength_type'] = ''
            
            # 找到所有强势事件日
            strength_indices = sub.index[sub['is_strong_day'] == 1].tolist()
            
            if not strength_indices:
                result.append(sub)
                continue
            
            # 为每一天找到最近的强势日
            for i in range(len(sub)):
                # 找到最近的强势日（在i之前）
                prev_strengths = [idx for idx in strength_indices if idx < i]
                if not prev_strengths:
                    continue
                
                last_idx = prev_strengths[-1]
                
                sub.loc[i, 'last_strength_idx'] = last_idx
                sub.loc[i, 'strength_event_date'] = sub.loc[last_idx, 'trade_date']
                sub.loc[i, 'days_since_last_strength'] = i - last_idx
                sub.loc[i, 'close_d0'] = sub.loc[last_idx, 'close']
                
                # 记录强势类型
                types = []
                if sub.loc[last_idx, 'is_limit_up'] == 1:
                    types.append('limit_up')
                if sub.loc[last_idx, 'ret'] >= self.config['strength_events']['strong_day_ret_min']:
                    types.append('strong_day')
                if sub.loc[last_idx, 'is_strong_breakout'] == 1:
                    types.append('breakout')
                sub.loc[i, 'strength_type'] = '|'.join(types)
                
                # 强势后最高收盘价
                if last_idx <= i:
                    sub.loc[i, 'peak_close_since_d0'] = sub.loc[last_idx:i+1, 'close'].max()
            
            result.append(sub)
        
        out = pd.concat(result, axis=0).reset_index(drop=True)
        
        # 回撤：从强势后的最高收盘往回看
        out['drawdown'] = np.where(
            out['peak_close_since_d0'].notna() & (out['peak_close_since_d0'] > 0),
            1 - out['close'] / out['peak_close_since_d0'],
            np.nan
        )
        
        # 从强势日起累计收益
        out['return_since_strength'] = np.where(
            out['close_d0'].notna() & (out['close_d0'] > 0),
            out['close'] / out['close_d0'] - 1,
            np.nan
        )
        
        # 回调速度：回撤 / 强势后最大上冲幅度
        out['peak_gain_since_d0'] = np.where(
            out['close_d0'].notna() & (out['close_d0'] > 0),
            out['peak_close_since_d0'] / out['close_d0'] - 1,
            np.nan
        )
        
        # 修复decay_ratio计算：当peak_gain_since_d0很小或为负时，设为NaN
        out['decay_ratio'] = np.where(
            out['peak_gain_since_d0'].notna() & (out['peak_gain_since_d0'] > 0.01),  # 至少1%的涨幅
            out['drawdown'] / out['peak_gain_since_d0'],
            np.nan
        )
        
        return out
    
    def apply_base_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        """Step 1: 应用基础过滤"""
        cfg = self.config['base_filter']
        
        cond = (
            df['is_main_board'] &
            (df['is_st'] == 0) &
            (df['is_suspended'] == 0) &
            (df['listed_days'] >= cfg['min_listing_days']) &
            (df['close'] >= cfg['min_price']) &
            df['ma_amount_20'].notna() &
            df['ma_amount_20'].between(cfg['min_avg_amount_20'], cfg['max_avg_amount_20']) &
            (df['count_limit_down_20'] <= cfg['max_limit_down_20'])
        )
        
        out = df[cond].copy()
        logger.info(f"基础过滤后: {len(out)}/{len(df)}")
        return out
    
    def apply_strength_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        """Step 2: 应用强势过滤"""
        cfg = self.config['strength_events']
        
        cond = (
            (df['count_limit_up_10'] >= 1) |
            (df['return_5'] >= cfg['return_5_min']) |
            (df['return_10'] >= cfg['return_10_min']) |
            (df['is_strong_breakout'] == 1)
        )
        
        out = df[cond].copy()
        logger.info(f"强势过滤后: {len(out)}/{len(df)}")
        return out
    
    def apply_pullback_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        """Step 3: 应用回调结构过滤"""
        cfg = self.config['pullback_structure']
        
        cond = (
            df['days_since_last_strength'].notna() &
            df['drawdown'].notna() &
            df['decay_ratio'].notna() &
            df['down_days_ratio'].notna() &
            df['days_since_last_strength'].between(cfg['days_range'][0], cfg['days_range'][1]) &
            df['drawdown'].between(cfg['drawdown_range'][0], cfg['drawdown_range'][1]) &
            (df['decay_ratio'] <= cfg['decay_ratio_max']) &
            (df['down_days_ratio'] <= cfg['down_days_ratio_max'])
        )
        
        out = df[cond].copy()
        logger.info(f"回调过滤后: {len(out)}/{len(df)}")
        return out
    
    def apply_volume_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        """Step 4: 应用缩量确认"""
        cfg = self.config['volume_condition']
        
        cond = (
            df['volume_ratio'].notna() &
            (df['volume_ratio'] <= cfg['volume_shrink_ratio'])
        )
        
        out = df[cond].copy()
        logger.info(f"缩量过滤后: {len(out)}/{len(df)}")
        return out
    
    def apply_trend_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        """Step 5: 应用趋势结构过滤"""
        cfg = self.config['trend_structure']
        
        cond = (
            df['ma5'].notna() &
            df['ma10'].notna() &
            (df['ma5'] > df['ma10']) &
            (df['close'] >= df['ma10'] * cfg['close_above_ma10_ratio']) &
            ((df['close'] - df['ma5']).abs() / df['ma5'] <= cfg['close_near_ma5_pct'])
        )
        
        out = df[cond].copy()
        logger.info(f"趋势过滤后: {len(out)}/{len(df)}")
        return out
    
    def apply_trend_direction_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        """Step 6: 应用趋势方向过滤"""
        cfg = self.config['trend_direction']
        
        cond = (
            df['ma10_slope'].notna() &
            (df['ma10_slope'] >= cfg['ma10_slope_min'])
        )
        
        out = df[cond].copy()
        logger.info(f"趋势方向过滤后: {len(out)}/{len(df)}")
        return out
    
    def calculate_scores(self, df: pd.DataFrame) -> pd.DataFrame:
        """Step 7: 计算综合评分"""
        cfg = self.config['scoring']
        df = df.copy()
        
        # 强势评分
        df['strength_score'] = 0.0
        df['strength_score'] += np.clip(df['count_limit_up_10'], 0, 2) * 20
        df['strength_score'] += np.clip(df['return_5'] * 100, 0, 20)
        df['strength_score'] += np.clip(df['return_10'] * 100, 0, 20)
        df['strength_score'] += (df['is_strong_breakout'] == 1).astype(int) * 20
        
        # 回调评分：以5%左右回撤最优
        df['pullback_score'] = 0.0
        df['pullback_score'] += np.clip(20 * (1 - (df['drawdown'] - 0.05).abs() / 0.05), 0, 20)
        
        df['pullback_score'] += np.where(
            df['days_since_last_strength'].between(2, 5), 20,
            np.where(df['days_since_last_strength'].between(6, 7), 12, 0)
        )
        
        # 趋势评分
        df['trend_score'] = 0.0
        df['trend_score'] += np.where(df['ma5'] > df['ma10'], 20, 0)
        df['trend_score'] += np.where(df['ma10_slope'] > 0, 15, 0)
        df['trend_score'] += np.clip(15 - ((df['close'] - df['ma5']).abs() / df['ma5']) * 100, 0, 15)
        
        # 量能评分
        df['volume_score'] = 0.0
        df['volume_score'] += np.where(df['volume_ratio'] <= 0.7, 25,
                              np.where(df['volume_ratio'] <= 0.9, 18, 8))
        df['volume_score'] += np.where(df['ma_amount_20'] >= 1e8, 15,
                              np.where(df['ma_amount_20'] >= 5e7, 10, 5))
        
        # 计算总分
        df['total_score'] = (
            df['strength_score'] * cfg['strength_weight'] +
            df['pullback_score'] * cfg['pullback_weight'] +
            df['trend_score'] * cfg['trend_weight'] +
            df['volume_score'] * cfg['volume_weight']
        )
        
        return df
    
    def select_candidates(self, df: pd.DataFrame, date: Optional[str] = None) -> pd.DataFrame:
        """
        选择候选股票
        
        Args:
            df: 历史数据DataFrame（必须包含多日数据）
            date: 选股日期（可选）
            
        Returns:
            候选股票DataFrame
        """
        logger.info("开始选股...")
        
        # 准备特征
        df_features = self.prepare_features(df)
        
        if date is not None:
            target_date = pd.to_datetime(date)
            df_features = df_features[df_features['trade_date'] == target_date].copy()
        
        if df_features.empty:
            logger.warning("目标日期无数据")
            return pd.DataFrame()
        
        print("\n" + "=" * 80)
        print("强势回调二次启动策略 - 过滤层统计")
        print("=" * 80)
        print(f"初始股票数: {len(df_features)}")
        
        # 应用过滤
        df1 = self.apply_base_filter(df_features)
        print(f"1. 基础过滤后: {len(df1)}")
        if df1.empty:
            return pd.DataFrame()
        
        df2 = self.apply_strength_filter(df1)
        print(f"2. 强势过滤后: {len(df2)}")
        if df2.empty:
            return pd.DataFrame()
        
        df3 = self.apply_pullback_filter(df2)
        print(f"3. 回调过滤后: {len(df3)}")
        if df3.empty:
            return pd.DataFrame()
        
        df4 = self.apply_volume_filter(df3)
        print(f"4. 缩量过滤后: {len(df4)}")
        if df4.empty:
            return pd.DataFrame()
        
        df5 = self.apply_trend_filter(df4)
        print(f"5. 趋势过滤后: {len(df5)}")
        if df5.empty:
            return pd.DataFrame()
        
        df6 = self.apply_trend_direction_filter(df5)
        print(f"6. 趋势方向过滤后: {len(df6)}")
        if df6.empty:
            return pd.DataFrame()
        
        # 评分排序
        df_scored = self.calculate_scores(df6)
        
        min_score = self.config['scoring']['min_total_score']
        df_scored = df_scored[df_scored['total_score'] >= min_score].copy()
        print(f"7. 评分过滤后(≥{min_score}): {len(df_scored)}")
        if df_scored.empty:
            return pd.DataFrame()
        
        # 排序和限制数量
        sort_by = self.config['selection']['sort_by']
        max_candidates = self.config['selection']['max_candidates']
        
        candidates = (
            df_scored
            .sort_values(sort_by, ascending=False)
            .head(max_candidates)
            .copy()
        )
        
        print(f"最终候选: {len(candidates)}")
        print("=" * 80)
        
        return candidates
    
    def get_watchlist_notes(self, candidates: pd.DataFrame) -> pd.DataFrame:
        """
        生成观察建议（替代原来的买点建议）
        
        Args:
            candidates: 候选股票DataFrame
            
        Returns:
            观察建议DataFrame
        """
        if candidates.empty:
            return pd.DataFrame()
        
        notes = []
        
        for _, row in candidates.iterrows():
            focus = []
            
            # 回踩MA5
            if abs(row['close'] - row['ma5']) / row['ma5'] <= 0.02:
                focus.append("关注回踩MA5后的承接")
            
            # 突破前高
            if row['is_near_high'] == 1:
                focus.append("关注是否放量突破前高")
            
            # 缩量企稳
            if row['volume_ratio'] <= 0.8 and row['close'] > row['ma10']:
                focus.append("关注缩量企稳后转强")
            
            # 默认建议
            if not focus:
                focus.append("关注T+1分时是否出现二次启动")
            
            notes.append({
                'ts_code': row['ts_code'],
                'name': row.get('name', ''),
                'close': row['close'],
                'strength_type': row.get('strength_type', ''),
                'strength_event_date': row.get('strength_event_date', pd.NaT),
                'days_since_strength': row.get('days_since_last_strength', np.nan),
                'drawdown': row.get('drawdown', np.nan),
                'volume_ratio': row.get('volume_ratio', np.nan),
                'ma5': row.get('ma5', np.nan),
                'ma10': row.get('ma10', np.nan),
                'total_score': row.get('total_score', np.nan),
                'watch_notes': "；".join(focus)
            })
        
        return pd.DataFrame(notes)