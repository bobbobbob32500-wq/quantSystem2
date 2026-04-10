# -*- coding: utf-8 -*-
"""
下载沪深主板日K数据
时间范围：2025年9月-11月
数据源：Tushare Pro
数据格式：与现有intraday_data表保持一致
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pandas as pd
import sqlite3
from datetime import datetime
import time
from src.core.logger import get_logger
from src.core.config import ConfigManager
import tushare as ts

logger = get_logger("download_daily_data_tushare")


def get_main_board_symbols():
    """获取沪深主板股票代码"""
    try:
        logger.info("正在获取沪深主板股票列表...")

        pro = ts.pro_api()

        # 获取所有股票基本信息
        df = pro.stock_basic(exchange='', list_status='L', fields='ts_code,symbol,name,market')

        # 筛选沪市主板（600xxx, 601xxx, 603xxx, 605xxx）
        sh_main_board = df[df['ts_code'].str.endswith('.SH') &
                           df['symbol'].str.match(r'^60[01235]')]
        sh_main_board['market'] = 'SH'

        # 筛选深市主板（000xxx, 001xxx）
        sz_main_board = df[df['ts_code'].str.endswith('.SZ') &
                           df['symbol'].str.match(r'^00[01]')]
        sz_main_board['market'] = 'SZ'

        # 合并
        all_symbols = pd.concat([sh_main_board, sz_main_board], ignore_index=True)

        logger.info(f"获取到沪深主板股票共 {len(all_symbols)} 只")
        logger.info(f"  - 沪市主板: {len(sh_main_board)} 只")
        logger.info(f"  - 深市主板: {len(sz_main_board)} 只")

        return all_symbols

    except Exception as e:
        logger.error(f"获取股票列表失败: {e}")
        return pd.DataFrame()


def download_daily_data_tushare(ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    使用Tushare下载单只股票的日K数据

    Args:
        ts_code: 股票代码（如 600000.SH）
        start_date: 开始日期（YYYYMMDD）
        end_date: 结束日期（YYYYMMDD）

    Returns:
        日K数据DataFrame
    """
    try:
        pro = ts.pro_api()

        # 下载日K数据
        df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)

        if df.empty:
            return pd.DataFrame()

        # 提取股票代码（去掉后缀）
        symbol = ts_code.split('.')[0]

        # 重命名列以匹配数据库格式
        df = df.rename(columns={
            'trade_date': 'trade_date',
            'open': 'open',
            'high': 'high',
            'low': 'low',
            'close': 'close',
            'vol': 'volume',
            'amount': 'amount'
        })

        # 转换时间格式
        df['trade_time'] = pd.to_datetime(df['trade_date'])
        df['symbol'] = symbol

        # 选择需要的列
        df = df[['symbol', 'trade_time', 'trade_date', 'open', 'high', 'low', 'close', 'volume', 'amount']]

        return df

    except Exception as e:
        logger.error(f"下载 {ts_code} 数据失败: {e}")
        return pd.DataFrame()


def save_to_database(df: pd.DataFrame, db_path: str):
    """保存数据到数据库"""
    if df.empty:
        return

    try:
        conn = sqlite3.connect(db_path)

        # 添加created_time字段
        df['created_time'] = datetime.now().isoformat()

        # 使用INSERT OR IGNORE避免重复
        cursor = conn.cursor()

        for _, row in df.iterrows():
            cursor.execute('''
                INSERT OR IGNORE INTO intraday_data
                (symbol, trade_time, trade_date, open, high, low, close, volume, amount, created_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                row['symbol'],
                row['trade_time'].isoformat(),
                row['trade_date'],
                row['open'],
                row['high'],
                row['low'],
                row['close'],
                row['volume'],
                row['amount'],
                row['created_time']
            ))

        conn.commit()
        conn.close()

        logger.info(f"成功保存 {len(df)} 条数据到数据库")

    except Exception as e:
        logger.error(f"保存数据到数据库失败: {e}")


def download_main_board_daily_data(start_date: str, end_date: str, db_path: str, max_stocks: int = None):
    """
    下载沪深主板日K数据

    Args:
        start_date: 开始日期（YYYY-MM-DD）
        end_date: 结束日期（YYYY-MM-DD）
        db_path: 数据库路径
        max_stocks: 最大下载数量（None表示全部下载）
    """
    logger.info("="*70)
    logger.info("开始下载沪深主板日K数据")
    logger.info(f"时间范围: {start_date} ~ {end_date}")
    logger.info("="*70)

    # 获取股票列表
    symbols_df = get_main_board_symbols()

    if symbols_df.empty:
        logger.error("未能获取股票列表，退出下载")
        return

    # 限制下载数量
    if max_stocks:
        symbols_df = symbols_df.head(max_stocks)
        logger.info(f"限制下载数量为: {max_stocks}")

    # 转换日期格式
    start_date_ymd = start_date.replace('-', '')
    end_date_ymd = end_date.replace('-', '')

    # 统计信息
    total_symbols = len(symbols_df)
    success_count = 0
    failed_count = 0
    total_records = 0

    # 逐个股票下载
    for i, row in symbols_df.iterrows():
        ts_code = row['ts_code']
        symbol = row['symbol']
        name = row['name']

        # 显示进度
        print(f"\n[{i+1}/{total_symbols}] {symbol} - {name}")
        logger.info(f"[{i+1}/{total_symbols}] {symbol} - {name}")

        try:
            # 下载数据
            df = download_daily_data_tushare(ts_code, start_date_ymd, end_date_ymd)

            if df.empty:
                print(f"  [WARN] 未获取到数据")
                logger.warning(f"未获取到数据")
                failed_count += 1
                continue

            # 保存到数据库
            save_to_database(df, db_path)

            success_count += 1
            total_records += len(df)

            print(f"  [OK] 成功下载 {len(df)} 条记录")
            logger.info(f"成功下载 {len(df)} 条记录")

            # 添加延迟避免请求过快（Tushare有限制）
            time.sleep(0.2)

        except Exception as e:
            print(f"  [ERROR] 下载失败: {e}")
            logger.error(f"下载失败: {e}")
            failed_count += 1

    # 打印统计信息
    print("\n" + "="*70)
    print("下载完成统计")
    print(f"  总股票数: {total_symbols}")
    print(f"  成功: {success_count}")
    print(f"  失败: {failed_count}")
    print(f"  总记录数: {total_records}")
    print("="*70)

    logger.info("\n" + "="*70)
    logger.info("下载完成统计")
    logger.info(f"  总股票数: {total_symbols}")
    logger.info(f"  成功: {success_count}")
    logger.info(f"  失败: {failed_count}")
    logger.info(f"  总记录数: {total_records}")
    logger.info("="*70)


def main():
    """主函数"""
    # 配置参数
    start_date = '2025-09-01'
    end_date = '2025-11-30'
    db_path = 'data/history_recommendation.db'

    # 检查Tushare是否可用
    try:
        pro = ts.pro_api()
        logger.info("Tushare Pro API连接成功")
    except Exception as e:
        logger.error("Tushare Pro API连接失败")
        return

    # 开始下载
    download_main_board_daily_data(start_date, end_date, db_path)

    logger.info("\n所有任务完成！")


if __name__ == "__main__":
    main()