# -*- coding: utf-8 -*-
"""
增强特征计算模块
基于现有数据构建行业动量、市场宽度等更强特征
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple
from datetime import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.database import DatabaseManager
from src.core.config import ConfigManager
from src.core.logger import get_logger

logger = get_logger("enhanced_features")


def compute_industry_momentum_features(
    db: DatabaseManager,
    trade_dates: List[str],
    lookback: int = 20
) -> Dict[str, pd.DataFrame]:
    """
    计算行业动量特征
    
    特征包括：
    1. industry_rs_rank: 个股RS在行业内的排名百分位
    2. industry_rs_gap: 个股RS - 行业平均RS
    3. industry_momentum: 行业整体动量（行业指数RS）
    4. industry_strength: 行业内上涨股占比
    
    Returns:
        Dict[trade_date, DataFrame]: 每日特征数据
    """
    logger.info(f"计算行业动量特征，日期数: {len(trade_dates)}")
    
    # 1. 获取所有股票的行业分类
    industry_map = {}
    rows = db.query("SELECT ts_code, industry FROM stock_basic WHERE industry IS NOT NULL")
    for r in rows:
        industry_map[r["ts_code"]] = r["industry"]
    
    logger.info(f"行业分类股票数: {len(industry_map)}")
    
    # 2. 获取日线数据计算RS
    all_codes = list(industry_map.keys())
    
    # 批量获取日线数据
    date_min = min(trade_dates)
    date_max = max(trade_dates)
    
    sql = f"""
        SELECT ts_code, trade_date, close, pct_chg
        FROM stock_daily
        WHERE trade_date >= '{date_min}' 
          AND trade_date <= '{date_max}'
          AND ts_code IN ({','.join([f"'{c}'" for c in all_codes[:5000]])})
        ORDER BY ts_code, trade_date
    """
    df_daily = pd.DataFrame(db.query(sql))
    
    if df_daily.empty:
        logger.warning("日线数据为空")
        return {}
    
    logger.info(f"日线数据行数: {len(df_daily)}")
    
    # 3. 计算每只股票的RS（相对强度）
    # RS = 过去N日收益率
    df_daily = df_daily.sort_values(["ts_code", "trade_date"])
    
    # 计算lookback日收益率
    df_daily["ret_lookback"] = df_daily.groupby("ts_code")["close"].transform(
        lambda x: x.pct_change(lookback)
    )
    
    # 4. 按日期分组计算行业特征
    result = {}
    
    for td in trade_dates:
        df_td = df_daily[df_daily["trade_date"] == td].copy()
        if df_td.empty:
            continue
        
        # 添加行业信息
        df_td["industry"] = df_td["ts_code"].map(industry_map)
        df_td = df_td[df_td["industry"].notna()]
        
        if df_td.empty:
            continue
        
        # 计算行业统计
        industry_stats = df_td.groupby("industry").agg({
            "ret_lookback": ["mean", "std", "count"],
            "pct_chg": lambda x: (x > 0).mean()  # 上涨股占比
        }).reset_index()
        
        industry_stats.columns = ["industry", "ind_ret_mean", "ind_ret_std", "ind_count", "ind_up_ratio"]
        
        # 合并回个股数据
        df_td = df_td.merge(industry_stats, on="industry", how="left")
        
        # 计算特征
        # 1. 行业内RS排名
        df_td["industry_rs_rank"] = df_td.groupby("industry")["ret_lookback"].rank(
            pct=True, ascending=True
        )
        
        # 2. 个股RS - 行业平均RS
        df_td["industry_rs_gap"] = df_td["ret_lookback"] - df_td["ind_ret_mean"]
        
        # 3. 行业动量（用行业平均RS代表）
        df_td["industry_momentum"] = df_td["ind_ret_mean"]
        
        # 4. 行业强度（上涨股占比）
        df_td["industry_strength"] = df_td["ind_up_ratio"]
        
        # 5. 行业内RS离散度（标准差）
        df_td["industry_rs_dispersion"] = df_td["ind_ret_std"]
        
        result[td] = df_td[[
            "ts_code", "trade_date",
            "industry_rs_rank", "industry_rs_gap", 
            "industry_momentum", "industry_strength",
            "industry_rs_dispersion"
        ]].copy()
    
    logger.info(f"行业动量特征计算完成，有效日期数: {len(result)}")
    return result


def compute_market_breadth_features(
    db: DatabaseManager,
    trade_dates: List[str],
    lookback: int = 20
) -> Dict[str, Dict]:
    """
    计算市场宽度特征
    
    特征包括：
    1. advance_decline_ratio: 涨跌家数比
    2. new_high_ratio: 创新高股占比
    3. new_low_ratio: 创新低股占比
    4. strong_stock_ratio: 强势股占比（RS>80%分位）
    5. weak_stock_ratio: 弱势股占比（RS<20%分位）
    6. market_breadth_thrust: 市场宽度推力（涨跌比 * 成交量比）
    
    Returns:
        Dict[trade_date, Dict]: 每日市场宽度指标
    """
    logger.info(f"计算市场宽度特征，日期数: {len(trade_dates)}")
    
    date_min = min(trade_dates)
    date_max = max(trade_dates)
    
    # 获取日线数据
    sql = f"""
        SELECT ts_code, trade_date, close, pct_chg, vol, amount
        FROM stock_daily
        WHERE trade_date >= '{date_min}' 
          AND trade_date <= '{date_max}'
        ORDER BY trade_date, ts_code
    """
    df_daily = pd.DataFrame(db.query(sql))
    
    if df_daily.empty:
        logger.warning("日线数据为空")
        return {}
    
    logger.info(f"日线数据行数: {len(df_daily)}")
    
    # 计算每只股票的lookback日最高/最低价
    df_daily = df_daily.sort_values(["ts_code", "trade_date"])
    
    df_daily["high_lookback"] = df_daily.groupby("ts_code")["close"].transform(
        lambda x: x.rolling(lookback, min_periods=1).max()
    )
    df_daily["low_lookback"] = df_daily.groupby("ts_code")["close"].transform(
        lambda x: x.rolling(lookback, min_periods=1).min()
    )
    
    # 计算lookback日收益率作为RS
    df_daily["ret_lookback"] = df_daily.groupby("ts_code")["close"].transform(
        lambda x: x.pct_change(lookback)
    )
    
    result = {}
    
    for td in trade_dates:
        df_td = df_daily[df_daily["trade_date"] == td].copy()
        if df_td.empty:
            continue
        
        n_total = len(df_td)
        
        # 1. 涨跌家数比
        n_up = (df_td["pct_chg"] > 0).sum()
        n_down = (df_td["pct_chg"] < 0).sum()
        ad_ratio = n_up / n_down if n_down > 0 else 10.0
        
        # 2. 创新高/新低股占比
        is_new_high = df_td["close"] >= df_td["high_lookback"]
        is_new_low = df_td["close"] <= df_td["low_lookback"]
        new_high_ratio = is_new_high.sum() / n_total
        new_low_ratio = is_new_low.sum() / n_total
        
        # 3. 强势/弱势股占比（基于RS分位数）
        rs_q80 = df_td["ret_lookback"].quantile(0.8)
        rs_q20 = df_td["ret_lookback"].quantile(0.2)
        strong_ratio = (df_td["ret_lookback"] > rs_q80).sum() / n_total
        weak_ratio = (df_td["ret_lookback"] < rs_q20).sum() / n_total
        
        # 4. 市场宽度推力
        # 用上涨股成交量 / 下跌股成交量
        vol_up = df_td.loc[df_td["pct_chg"] > 0, "vol"].sum()
        vol_down = df_td.loc[df_td["pct_chg"] < 0, "vol"].sum()
        vol_ratio = vol_up / vol_down if vol_down > 0 else 10.0
        breadth_thrust = ad_ratio * vol_ratio
        
        # 5. 市场平均涨跌幅
        avg_pct_chg = df_td["pct_chg"].mean()
        
        # 6. 成交额变化
        avg_amount = df_td["amount"].mean()
        
        result[td] = {
            "trade_date": td,
            "advance_decline_ratio": ad_ratio,
            "new_high_ratio": new_high_ratio,
            "new_low_ratio": new_low_ratio,
            "strong_stock_ratio": strong_ratio,
            "weak_stock_ratio": weak_ratio,
            "market_breadth_thrust": breadth_thrust,
            "avg_pct_chg": avg_pct_chg,
            "avg_amount": avg_amount,
            "up_count": int(n_up),
            "down_count": int(n_down),
            "total_count": int(n_total),
        }
    
    logger.info(f"市场宽度特征计算完成，有效日期数: {len(result)}")
    return result


def compute_volume_price_divergence(
    db: DatabaseManager,
    trade_dates: List[str],
    lookback: int = 20
) -> Dict[str, pd.DataFrame]:
    """
    计算量价背离特征
    
    特征包括：
    1. price_volume_divergence: 价格新高但成交量萎缩
    2. volume_surge_no_move: 成交量突增但价格不动
    3. turnover_rate: 换手率
    4. volume_ratio: 量比（当日成交量 / 5日均量）
    
    Returns:
        Dict[trade_date, DataFrame]: 每日特征数据
    """
    logger.info(f"计算量价背离特征，日期数: {len(trade_dates)}")
    
    date_min = min(trade_dates)
    date_max = max(trade_dates)
    
    # 获取日线数据
    sql = f"""
        SELECT ts_code, trade_date, open, close, high, low, vol, amount, pct_chg
        FROM stock_daily
        WHERE trade_date >= '{date_min}' 
          AND trade_date <= '{date_max}'
        ORDER BY ts_code, trade_date
    """
    df_daily = pd.DataFrame(db.query(sql))
    
    if df_daily.empty:
        logger.warning("日线数据为空")
        return {}
    
    logger.info(f"日线数据行数: {len(df_daily)}")
    
    # 计算滚动统计
    df_daily = df_daily.sort_values(["ts_code", "trade_date"])
    
    # 5日均量
    df_daily["vol_ma5"] = df_daily.groupby("ts_code")["vol"].transform(
        lambda x: x.rolling(5, min_periods=1).mean()
    )
    
    # 20日最高价
    df_daily["high_20"] = df_daily.groupby("ts_code")["high"].transform(
        lambda x: x.rolling(lookback, min_periods=1).max()
    )
    
    # 20日最大成交量
    df_daily["vol_max_20"] = df_daily.groupby("ts_code")["vol"].transform(
        lambda x: x.rolling(lookback, min_periods=1).max()
    )
    
    # 计算特征
    # 1. 量比
    df_daily["volume_ratio"] = df_daily["vol"] / df_daily["vol_ma5"].replace(0, np.nan)
    
    # 2. 价格是否创新高
    df_daily["is_new_high"] = (df_daily["close"] >= df_daily["high_20"] * 0.99).astype(int)
    
    # 3. 成交量是否萎缩（低于5日均量的80%）
    df_daily["is_vol_shrink"] = (df_daily["vol"] < df_daily["vol_ma5"] * 0.8).astype(int)
    
    # 4. 量价背离：价格新高 + 成交量萎缩
    df_daily["price_volume_divergence"] = df_daily["is_new_high"] * df_daily["is_vol_shrink"]
    
    # 5. 成交量突增（量比>2）但价格不动（涨跌幅<1%）
    df_daily["volume_surge_no_move"] = (
        (df_daily["volume_ratio"] > 2) & (df_daily["pct_chg"].abs() < 1)
    ).astype(int)
    
    # 6. 振幅
    df_daily["amplitude"] = (df_daily["high"] - df_daily["low"]) / df_daily["open"].replace(0, np.nan)
    
    result = {}
    
    for td in trade_dates:
        df_td = df_daily[df_daily["trade_date"] == td].copy()
        if df_td.empty:
            continue
        
        result[td] = df_td[[
            "ts_code", "trade_date",
            "volume_ratio", "price_volume_divergence",
            "volume_surge_no_move", "amplitude"
        ]].copy()
    
    logger.info(f"量价背离特征计算完成，有效日期数: {len(result)}")
    return result


def merge_enhanced_features(
    industry_features: Dict[str, pd.DataFrame],
    market_features: Dict[str, Dict],
    volume_features: Dict[str, pd.DataFrame],
    trade_dates: List[str]
) -> Dict[str, pd.DataFrame]:
    """
    合并所有增强特征
    """
    logger.info("合并增强特征...")
    
    result = {}
    
    for td in trade_dates:
        # 行业特征
        ind_df = industry_features.get(td)
        if ind_df is None or ind_df.empty:
            continue
        
        # 量价特征
        vol_df = volume_features.get(td)
        
        # 市场宽度特征
        mkt = market_features.get(td)
        
        # 合并
        merged = ind_df.copy()
        
        if vol_df is not None and not vol_df.empty:
            merged = merged.merge(
                vol_df[["ts_code", "volume_ratio", "price_volume_divergence", 
                        "volume_surge_no_move", "amplitude"]],
                on="ts_code",
                how="left"
            )
        
        # 添加市场宽度特征（所有股票相同）
        if mkt:
            merged["market_ad_ratio"] = mkt["advance_decline_ratio"]
            merged["market_new_high_ratio"] = mkt["new_high_ratio"]
            merged["market_strong_ratio"] = mkt["strong_stock_ratio"]
            merged["market_breadth_thrust"] = mkt["market_breadth_thrust"]
        
        result[td] = merged
    
    logger.info(f"特征合并完成，有效日期数: {len(result)}")
    return result


def save_enhanced_features_to_db(
    db: DatabaseManager,
    features: Dict[str, pd.DataFrame]
) -> int:
    """
    保存增强特征到数据库
    """
    logger.info("保存增强特征到数据库...")
    
    saved_count = 0
    
    for td, df in features.items():
        if df.empty:
            continue
        
        for _, row in df.iterrows():
            ts_code = row["ts_code"]
            
            # 保存每个特征
            feature_cols = [c for c in df.columns if c not in ["ts_code", "trade_date"]]
            
            for feat_name in feature_cols:
                feat_value = row.get(feat_name)
                if pd.isna(feat_value):
                    continue
                
                db.execute(
                    """
                    INSERT OR REPLACE INTO factor_values
                    (ts_code, trade_date, factor_name, factor_value, create_time)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        ts_code,
                        td,
                        f"enh_{feat_name}",
                        float(feat_value),
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    )
                )
                saved_count += 1
    
    logger.info(f"保存完成，共 {saved_count} 条记录")
    return saved_count


def main():
    """主函数"""
    print("=" * 72)
    print("  增强特征计算")
    print("=" * 72)
    
    config = ConfigManager()
    db = DatabaseManager(config)
    
    # 获取交易日
    all_dates = [
        r["trade_date"]
        for r in db.query(
            "SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date ASC"
        )
    ]
    
    # 使用最近60个交易日
    trade_dates = all_dates[-60:]
    
    print(f"交易日范围: {trade_dates[0]} ~ {trade_dates[-1]}")
    print(f"交易日数: {len(trade_dates)}")
    
    # 1. 计算行业动量特征
    print("\n[1/3] 计算行业动量特征...")
    industry_features = compute_industry_momentum_features(db, trade_dates)
    
    # 2. 计算市场宽度特征
    print("\n[2/3] 计算市场宽度特征...")
    market_features = compute_market_breadth_features(db, trade_dates)
    
    # 3. 计算量价背离特征
    print("\n[3/3] 计算量价背离特征...")
    volume_features = compute_volume_price_divergence(db, trade_dates)
    
    # 4. 合并特征
    print("\n[4/4] 合并特征...")
    merged_features = merge_enhanced_features(
        industry_features, market_features, volume_features, trade_dates
    )
    
    # 5. 保存到数据库
    print("\n保存到数据库...")
    saved = save_enhanced_features_to_db(db, merged_features)
    
    print(f"\n完成！保存了 {saved} 条特征记录")
    
    # 打印示例
    if merged_features:
        sample_date = list(merged_features.keys())[-1]
        sample_df = merged_features[sample_date]
        print(f"\n示例 ({sample_date}):")
        print(sample_df.head(3).to_string())
    
    print("\n" + "=" * 72)


if __name__ == "__main__":
    main()
