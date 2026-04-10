"""
调试最终策略的基础过滤问题
"""

import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
import sys
import os

# 添加项目路径
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from src.modules.final_strategy import FinalStrategy

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def debug_base_filter():
    """调试基础过滤"""
    print("=" * 80)
    print("调试基础过滤问题")
    print("=" * 80)
    
    # 连接数据库
    db_path = 'data/database/quant_system.db'
    conn = sqlite3.connect(db_path)
    
    try:
        # 加载最新数据
        query = """
        SELECT 
            d.ts_code,
            d.trade_date,
            d.open,
            d.high,
            d.low,
            d.close,
            d.vol,
            d.amount,
            d.pct_chg,
            b.name,
            b.list_date
        FROM stock_daily d
        LEFT JOIN stock_basic b ON d.ts_code = b.ts_code
        WHERE d.trade_date = '20260327'
        ORDER BY d.ts_code
        """
        
        df = pd.read_sql_query(query, conn)
        print(f"加载数据: {df.shape}")
        
        if len(df) == 0:
            print("没有数据")
            return
        
        # 创建策略实例
        strategy = FinalStrategy()
        
        # 准备特征
        print("\n准备特征数据...")
        df_features = strategy.prepare_features(df)
        
        # 检查基础过滤条件
        cfg = strategy.config['base_filter']
        
        print(f"\n基础过滤条件:")
        print(f"1. 主板股票: {cfg['sh_prefixes']} 或 {cfg['sz_prefixes']}")
        print(f"2. 非ST")
        print(f"3. 非停牌")
        print(f"4. 上市≥{cfg['min_listing_days']}天")
        print(f"5. 股价≥{cfg['min_price']}元")
        print(f"6. 20日均额: {cfg['min_avg_amount_20']/1e7:.0f}万-{cfg['max_avg_amount_20']/1e8:.0f}亿")
        print(f"7. 20日内跌停≤{cfg['max_limit_down_20']}次")
        
        # 逐个检查条件
        total = len(df_features)
        print(f"\n总股票数: {total}")
        
        # 1. 主板股票
        code_str = df_features['ts_code'].astype(str)
        is_main_board = (
            code_str.str.startswith(tuple(cfg['sh_prefixes'])) |
            code_str.str.startswith(tuple(cfg['sz_prefixes']))
        )
        main_board_count = is_main_board.sum()
        print(f"主板股票: {main_board_count}/{total} ({main_board_count/total:.2%})")
        
        # 2. 非ST
        if 'is_st' in df_features.columns:
            non_st_count = (df_features['is_st'] == 0).sum()
            print(f"非ST: {non_st_count}/{total} ({non_st_count/total:.2%})")
        else:
            print("非ST: 数据缺失")
        
        # 3. 非停牌
        if 'is_suspended' in df_features.columns:
            non_suspended_count = (df_features['is_suspended'] == 0).sum()
            print(f"非停牌: {non_suspended_count}/{total} ({non_suspended_count/total:.2%})")
        else:
            print("非停牌: 数据缺失")
        
        # 4. 上市天数
        if 'listed_days' in df_features.columns:
            listed_ok_count = (df_features['listed_days'] >= cfg['min_listing_days']).sum()
            print(f"上市≥{cfg['min_listing_days']}天: {listed_ok_count}/{total} ({listed_ok_count/total:.2%})")
            print(f"上市天数范围: {df_features['listed_days'].min()} - {df_features['listed_days'].max()}")
        else:
            print("上市天数: 数据缺失")
        
        # 5. 股价
        price_ok_count = (df_features['close'] >= cfg['min_price']).sum()
        print(f"股价≥{cfg['min_price']}元: {price_ok_count}/{total} ({price_ok_count/total:.2%})")
        print(f"股价范围: {df_features['close'].min():.2f} - {df_features['close'].max():.2f}")
        
        # 6. 20日均额
        if 'ma_amount_20' in df_features.columns:
            amount_ok_count = df_features['ma_amount_20'].between(
                cfg['min_avg_amount_20'], cfg['max_avg_amount_20']
            ).sum()
            print(f"20日均额合格: {amount_ok_count}/{total} ({amount_ok_count/total:.2%})")
            print(f"20日均额范围: {df_features['ma_amount_20'].min()/1e4:.0f}万 - {df_features['ma_amount_20'].max()/1e8:.2f}亿")
        else:
            print("20日均额: 数据缺失")
        
        # 7. 跌停次数
        if 'count_limit_down_20' in df_features.columns:
            limit_down_ok_count = (df_features['count_limit_down_20'] <= cfg['max_limit_down_20']).sum()
            print(f"20日内跌停≤{cfg['max_limit_down_20']}次: {limit_down_ok_count}/{total} ({limit_down_ok_count/total:.2%})")
            print(f"跌停次数范围: {df_features['count_limit_down_20'].min()} - {df_features['count_limit_down_20'].max()}")
        else:
            print("跌停次数: 数据缺失")
        
        # 综合条件
        cond = (
            is_main_board &
            (df_features['is_st'] == 0) &
            (df_features['is_suspended'] == 0) &
            (df_features['listed_days'] >= cfg['min_listing_days']) &
            (df_features['close'] >= cfg['min_price']) &
            df_features['ma_amount_20'].between(cfg['min_avg_amount_20'], cfg['max_avg_amount_20']) &
            (df_features['count_limit_down_20'] <= cfg['max_limit_down_20'])
        )
        
        print(f"\n综合通过: {cond.sum()}/{total} ({cond.sum()/total:.2%})")
        
        if cond.sum() == 0:
            print("\n问题分析:")
            
            # 找出失败的条件
            failed_conditions = []
            
            if not is_main_board.any():
                failed_conditions.append("主板股票条件")
            
            if (df_features['is_st'] == 1).any():
                failed_conditions.append("ST股票")
            
            if (df_features['is_suspended'] == 1).any():
                failed_conditions.append("停牌股票")
            
            if (df_features['listed_days'] < cfg['min_listing_days']).all():
                failed_conditions.append(f"上市天数<{cfg['min_listing_days']}")
            
            if (df_features['close'] < cfg['min_price']).all():
                failed_conditions.append(f"股价<{cfg['min_price']}")
            
            if not df_features['ma_amount_20'].between(cfg['min_avg_amount_20'], cfg['max_avg_amount_20']).any():
                failed_conditions.append("20日均额范围")
            
            if (df_features['count_limit_down_20'] > cfg['max_limit_down_20']).all():
                failed_conditions.append(f"跌停次数>{cfg['max_limit_down_20']}")
            
            print(f"失败的条件: {', '.join(failed_conditions)}")
            
            # 建议调整
            print("\n建议调整:")
            print("1. 检查数据质量(特别是ST、停牌、上市天数)")
            print("2. 适当放宽条件:")
            print(f"   - 降低股价要求: {cfg['min_price']} → 2.0")
            print(f"   - 降低成交额下限: {cfg['min_avg_amount_20']/1e7:.0f}万 → 3000万")
            print(f"   - 增加跌停容忍: {cfg['max_limit_down_20']} → 5")
        
        # 查看具体股票
        print(f"\n前10只股票信息:")
        sample = df_features.head(10)
        for i, (_, row) in enumerate(sample.iterrows(), 1):
            print(f"\n{i}. {row['ts_code']} - {row.get('name', 'N/A')}")
            print(f"   收盘价: {row['close']:.2f}")
            print(f"   20日均额: {row.get('ma_amount_20', 0)/1e8:.2f}亿")
            print(f"   上市天数: {row.get('listed_days', 0)}")
            print(f"   是否ST: {row.get('is_st', 0)}")
            print(f"   是否停牌: {row.get('is_suspended', 0)}")
            print(f"   20日跌停: {row.get('count_limit_down_20', 0)}次")
            
    finally:
        conn.close()


def debug_strength_filter():
    """调试强势过滤"""
    print("\n" + "=" * 80)
    print("调试强势过滤")
    print("=" * 80)
    
    # 连接数据库
    db_path = 'data/database/quant_system.db'
    conn = sqlite3.connect(db_path)
    
    try:
        # 加载数据
        query = """
        SELECT 
            d.ts_code,
            d.trade_date,
            d.open,
            d.high,
            d.low,
            d.close,
            d.vol,
            d.amount,
            d.pct_chg,
            b.name
        FROM stock_daily d
        LEFT JOIN stock_basic b ON d.ts_code = b.ts_code
        WHERE d.trade_date = '20260327'
        AND (d.ts_code LIKE '600%' OR d.ts_code LIKE '601%' OR 
             d.ts_code LIKE '603%' OR d.ts_code LIKE '605%' OR
             d.ts_code LIKE '000%' OR d.ts_code LIKE '001%' OR 
             d.ts_code LIKE '002%')
        ORDER BY d.ts_code
        """
        
        df = pd.read_sql_query(query, conn)
        print(f"加载数据: {df.shape}")
        
        if len(df) == 0:
            print("没有数据")
            return
        
        # 创建策略实例
        strategy = FinalStrategy()
        
        # 准备特征
        df_features = strategy.prepare_features(df)
        
        # 检查强势条件
        cfg = strategy.config['strength_events']
        
        print(f"\n强势过滤条件:")
        print(f"1. 10日内涨停次数≥{cfg['limit_up_count_10_min']}")
        print(f"2. 5日涨幅≥{cfg['return_5_min']:.1%}")
        print(f"3. 10日涨幅≥{cfg['return_10_min']:.1%}")
        print(f"4. 接近前高{cfg['breakout_price_ratio']:.0%}且放量{cfg['breakout_volume_ratio']}倍")
        
        # 逐个检查条件
        total = len(df_features)
        print(f"\n总股票数: {total}")
        
        # 1. 涨停次数
        if 'count_limit_up_10' in df_features.columns:
            limit_up_count = (df_features['count_limit_up_10'] >= cfg['limit_up_count_10_min']).sum()
            print(f"10日内涨停≥{cfg['limit_up_count_10_min']}次: {limit_up_count}/{total} ({limit_up_count/total:.2%})")
            print(f"涨停次数范围: {df_features['count_limit_up_10'].min()} - {df_features['count_limit_up_10'].max()}")
        else:
            print("涨停次数: 数据缺失")
        
        # 2. 5日涨幅
        if 'return_5' in df_features.columns:
            return_5_count = (df_features['return_5'] >= cfg['return_5_min']).sum()
            print(f"5日涨幅≥{cfg['return_5_min']:.1%}: {return_5_count}/{total} ({return_5_count/total:.2%})")
            print(f"5日涨幅范围: {df_features['return_5'].min():.2%} - {df_features['return_5'].max():.2%}")
        else:
            print("5日涨幅: 数据缺失")
        
        # 3. 10日涨幅
        if 'return_10' in df_features.columns:
            return_10_count = (df_features['return_10'] >= cfg['return_10_min']).sum()
            print(f"10日涨幅≥{cfg['return_10_min']:.1%}: {return_10_count}/{total} ({return_10_count/total:.2%})")
            print(f"10日涨幅范围: {df_features['return_10'].min():.2%} - {df_features['return_10'].max():.2%}")
        else:
            print("10日涨幅: 数据缺失")
        
        # 4. 放量突破
        if 'is_near_high' in df_features.columns and 'volume_ratio' in df_features.columns:
            breakout_count = ((df_features['is_near_high'] == 1) & 
                            (df_features['volume_ratio'] >= cfg['breakout_volume_ratio'])).sum()
            print(f"放量突破: {breakout_count}/{total} ({breakout_count/total:.2%})")
        else:
            print("放量突破: 数据缺失")
        
        # OR条件
        cond = (
            (df_features['count_limit_up_10'] >= cfg['limit_up_count_10_min']) |
            (df_features['return_5'] >= cfg['return_5_min']) |
            (df_features['return_10'] >= cfg['return_10_min']) |
            ((df_features['is_near_high'] == 1) & 
             (df_features['volume_ratio'] >= cfg['breakout_volume_ratio']))
        )
        
        print(f"\n强势过滤通过: {cond.sum()}/{total} ({cond.sum()/total:.2%})")
        
        if cond.sum() > 0:
            print("\n满足条件的股票示例:")
            strong_stocks = df_features[cond].head(5)
            for i, (_, row) in enumerate(strong_stocks.iterrows(), 1):
                reasons = []
                if row['count_limit_up_10'] >= cfg['limit_up_count_10_min']:
                    reasons.append(f"涨停{row['count_limit_up_10']}次")
                if row['return_5'] >= cfg['return_5_min']:
                    reasons.append(f"5日涨{row['return_5']:.1%}")
                if row['return_10'] >= cfg['return_10_min']:
                    reasons.append(f"10日涨{row['return_10']:.1%}")
                if row['is_near_high'] == 1 and row['volume_ratio'] >= cfg['breakout_volume_ratio']:
                    reasons.append(f"放量突破(量比{row['volume_ratio']:.1f}x)")
                
                print(f"{i}. {row['ts_code']} - {row.get('name', 'N/A')}: {', '.join(reasons)}")
        
    finally:
        conn.close()


def main():
    """主函数"""
    print("最终策略调试")
    print("=" * 80)
    
    # 调试基础过滤
    debug_base_filter()
    
    # 调试强势过滤
    debug_strength_filter()
    
    print("\n" + "=" * 80)
    print("调试完成!")
    print("=" * 80)
    
    print("\n问题分析:")
    print("1. 基础过滤可能过于严格(股价、成交额、跌停次数)")
    print("2. 强势过滤条件可能不满足(市场环境)")
    print("3. 数据质量问题(特征计算)")
    
    print("\n建议调整:")
    print("1. 放宽基础过滤条件:")
    print("   - 股价要求: 3.0 → 2.0")
    print("   - 成交额下限: 5000万 → 3000万")
    print("   - 跌停容忍: 2次 → 5次")
    
    print("\n2. 调整强势过滤:")
    print("   - 5日涨幅: 8% → 5%")
    print("   - 10日涨幅: 12% → 8%")
    print("   - 放量倍数: 1.5倍 → 1.2倍")
    
    print("\n3. 检查数据:")
    print("   - 确认数据完整性")
    print("   - 检查特征计算正确性")
    print("   - 验证日期范围")


if __name__ == "__main__":
    main()
