# -*- coding: utf-8 -*-
"""
下载沪深主板日K数据
时间范围：2026年9月-11月
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

logger = get_logger("download_daily_data")


def get_main_board_symbols():
    """获取沪深主板股票代码"""
    try:
        import akshare as ak

        logger.info("正在获取沪深主板股票列表...")

        # 获取沪市主板股票（600xxx, 601xxx, 603xxx, 605xxx）
        sh_main_board = ak.stock_info_a_code_name()
        sh_main_board = sh_main_board[sh_main_board['code'].str.startswith(('600', '601', '603', '605'))]
        sh_main_board['market'] = 'SH'
        sh_main_board['ts_code'] = sh_main_board['code'] + '.SH'

        # 获取深市主板股票（000xxx, 001xxx）
        sz_main_board = ak.stock_info_a_code_name()
        sz_main_board = sz_main_board[sz_main_board['code'].str.startswith(('000', '001'))]
        sz_main_board['market'] = 'SZ'
        sz_main_board['ts_code'] = sz_main_board['code'] + '.SZ'

        # 合并
        all_symbols = pd.concat([sh_main_board, sz_main_board], ignore_index=True)

        logger.info(f"获取到沪深主板股票共 {len(all_symbols)} 只")
        logger.info(f"  - 沪市主板: {len(sh_main_board)} 只")
        logger.info(f"  - 深市主板: {len(sz_main_board)} 只")

        return all_symbols

    except Exception as e:
        logger.error(f"获取股票列表失败: {e}")
        return pd.DataFrame()


def download_daily_data_akshare(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    使用AKShare下载单只股票的日K数据

    Args:
        symbol: 股票代码（如 000001）
        start_date: 开始日期（YYYYMMDD）
        end_date: 结束日期（YYYYMMDD）

    Returns:
        日K数据DataFrame
    """
    try:
        import akshare as ak

        # 转换股票代码格式
        if symbol.startswith('6'):
            ak_symbol = f"sh{symbol}"
        else:
            ak_symbol = f"sz{symbol}"

        # 下载日K数据
        df = ak.stock_zh_a_hist(symbol=ak_symbol, period="daily",
                                start_date=start_date, end_date=end_date,
                                adjust="qfq")  # 前复权

        if df.empty:
            return pd.DataFrame()

        # 重命名列以匹配数据库格式
        df = df.rename(columns={
            '日期': 'trade_time',
            '开盘': 'open',
            '最高': 'high',
            '最低': 'low',
            '收盘': 'close',
            '成交量': 'volume',
            '成交额': 'amount'
        })

        # 转换时间格式
        df['trade_time'] = pd.to_datetime(df['trade_time'])
        df['trade_date'] = df['trade_time'].dt.strftime('%Y-%m-%d')
        df['symbol'] = symbol

        # 选择需要的列
        df = df[['symbol', 'trade_time', 'trade_date', 'open', 'high', 'low', 'close', 'volume', 'amount']]

        return df

    except Exception as e:
        logger.error(f"下载 {symbol} 数据失败: {e}")
        return pd.DataFrame()


def save_to_database(df: pd.DataFrame, db_path: str):
    """保存数据到数据库"""
    if df.empty:
        return

    try:
        conn = sqlite3.connect(db_path)

        # 添加created_time字段
        df['created_time'] = datetime.now().isoformat()

        # 保存数据
        df.to_sql('intraday_data', conn, if_exists='append', index=False)

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
        symbol = row['code']
        name = row['name']

        # 显示进度
        print(f"\n[{i+1}/{total_symbols}] {symbol} - {name}")
        logger.info(f"[{i+1}/{total_symbols}] {symbol} - {name}")

        try:
            # 下载数据
            df = download_daily_data_akshare(symbol, start_date_ymd, end_date_ymd)

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

            # 添加延迟避免请求过快
            time.sleep(0.5)

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

    # 检查AKShare是否安装
    try:
        import akshare as ak
        logger.info("AKShare已安装")
    except ImportError:
        logger.error("AKShare未安装，请运行: pip install akshare")
        return

    # 开始下载
    download_main_board_daily_data(start_date, end_date, db_path)

    logger.info("\n所有任务完成！")


if __name__ == "__main__":
    main()