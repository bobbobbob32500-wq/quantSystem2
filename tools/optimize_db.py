# -*- coding: utf-8 -*-
"""
数据库优化脚本

执行内容：
1. 删除 stock_daily 重复索引 idx_stock_daily_code_date
2. 删除 factor_values 冗余索引 idx_factor_values_code_date
3. 删除 factor_values 低选择性单列索引 idx_factor_values_code / idx_factor_values_date / idx_factor_values_name
4. 为 signal_feedback_detail 补充高频查询索引
5. 为 factor_values 补充 (trade_date, factor_name) 复合索引（盘前按日期批量读取场景）
6. 对 quant_system.db 执行 ANALYZE 更新统计信息
7. 对 history_recommendation.db 执行 VACUUM 回收 98.6% 空闲空间
8. 删除 intraday_data 超过 90 天的历史分钟数据（只保留近期）
"""

import sqlite3
import os
import time

QUANT_DB = 'data/database/quant_system.db'
HIST_DB = 'data/history_recommendation.db'


def run_sql(conn, sql, desc):
    try:
        t0 = time.time()
        conn.execute(sql)
        conn.commit()
        elapsed = time.time() - t0
        print(f"  [OK] {desc} ({elapsed:.2f}s)")
        return True
    except Exception as e:
        print(f"  [SKIP] {desc}: {e}")
        return False


def optimize_quant_system():
    print("\n" + "="*60)
    print("优化 quant_system.db")
    print("="*60)
    if not os.path.exists(QUANT_DB):
        print("  数据库不存在，跳过")
        return

    conn = sqlite3.connect(QUANT_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    # 1. 删除 stock_daily 重复索引（两个索引列完全相同）
    run_sql(conn, "DROP INDEX IF EXISTS idx_stock_daily_code_date",
            "删除 stock_daily 重复索引 idx_stock_daily_code_date")

    # 2. 删除 factor_values 冗余索引
    # idx_factor_values_code_date 被 idx_factor_values_code_date_name 完全覆盖
    run_sql(conn, "DROP INDEX IF EXISTS idx_factor_values_code_date",
            "删除 factor_values 冗余索引 idx_factor_values_code_date")
    # 单列低选择性索引（ts_code 重复率高，单列索引价值低）
    run_sql(conn, "DROP INDEX IF EXISTS idx_factor_values_code",
            "删除 factor_values 低效单列索引 idx_factor_values_code")
    # trade_date 单列索引（被复合索引覆盖）
    run_sql(conn, "DROP INDEX IF EXISTS idx_factor_values_date",
            "删除 factor_values 冗余索引 idx_factor_values_date")
    # factor_name 单列索引（低选择性，8个值，全表扫描更快）
    run_sql(conn, "DROP INDEX IF EXISTS idx_factor_values_name",
            "删除 factor_values 低效单列索引 idx_factor_values_name")

    # 3. 为 factor_values 补充 (trade_date, factor_name) 复合索引
    # 盘前选股按日期批量读取所有因子时使用
    run_sql(conn,
            "CREATE INDEX IF NOT EXISTS idx_factor_values_date_name ON factor_values (trade_date, factor_name)",
            "新增 factor_values (trade_date, factor_name) 复合索引")

    # 4. 为 signal_feedback_detail 补充 (source_type, direction, horizon, signal_date) 复合索引
    # FeedbackGuard._query_window_stat 高频查询此字段组合
    run_sql(conn,
            "CREATE INDEX IF NOT EXISTS idx_feedback_detail_query ON signal_feedback_detail "
            "(source_type, direction, horizon, signal_date)",
            "新增 signal_feedback_detail 查询复合索引")

    # 5. 为 stock_daily 补充 trade_date DESC 索引，加速 get_latest_trade_date
    run_sql(conn,
            "CREATE INDEX IF NOT EXISTS idx_stock_daily_date_desc ON stock_daily (trade_date DESC)",
            "新增 stock_daily trade_date DESC 索引")

    # 6. 更新统计信息（让查询优化器选择正确执行计划）
    run_sql(conn, "ANALYZE", "ANALYZE 更新统计信息")

    conn.close()
    new_size = os.path.getsize(QUANT_DB) / 1024 / 1024
    print(f"  quant_system.db 当前大小: {new_size:.2f} MB")


def optimize_history_recommendation():
    print("\n" + "="*60)
    print("优化 history_recommendation.db")
    print("="*60)
    if not os.path.exists(HIST_DB):
        print("  数据库不存在，跳过")
        return

    old_size = os.path.getsize(HIST_DB) / 1024 / 1024
    print(f"  优化前大小: {old_size:.2f} MB")

    conn = sqlite3.connect(HIST_DB)
    conn.execute("PRAGMA journal_mode=DELETE")  # VACUUM 需要 non-WAL 模式
    conn.commit()

    # 1. 删除 90 天以前的 intraday_data（分钟数据无需长期保留）
    conn.execute("PRAGMA table_info('intraday_data')")
    run_sql(conn,
            "DELETE FROM intraday_data WHERE trade_date < date('now', '-90 days')",
            "清理 intraday_data 90天前历史分钟数据")

    # 查看清理后行数
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM intraday_data")
    remaining = cur.fetchone()[0]
    print(f"  intraday_data 清理后剩余: {remaining:,} 行")

    # 2. 补充 (trade_date) 索引加速按日期范围删除/查询
    run_sql(conn,
            "CREATE INDEX IF NOT EXISTS idx_intraday_date ON intraday_data (trade_date)",
            "新增 intraday_data trade_date 索引")

    # 3. ANALYZE
    run_sql(conn, "ANALYZE", "ANALYZE 更新统计信息")
    conn.close()

    # 4. VACUUM 回收空闲空间（需要独立连接）
    print("  执行 VACUUM（回收空闲空间，可能需要几分钟）...")
    t0 = time.time()
    conn = sqlite3.connect(HIST_DB)
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.commit()
    conn.isolation_level = None  # autocommit for VACUUM
    try:
        conn.execute("VACUUM")
        elapsed = time.time() - t0
        print(f"  [OK] VACUUM 完成 ({elapsed:.1f}s)")
    except Exception as e:
        print(f"  [FAIL] VACUUM: {e}")
    finally:
        conn.close()

    new_size = os.path.getsize(HIST_DB) / 1024 / 1024
    print(f"  优化后大小: {new_size:.2f} MB (节省 {old_size - new_size:.2f} MB)")


def print_final_index_status():
    print("\n" + "="*60)
    print("优化后索引状态")
    print("="*60)
    for db_path, label in [(QUANT_DB, 'quant_system'), (HIST_DB, 'history_recommendation')]:
        if not os.path.exists(db_path):
            continue
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
        tables = [r[0] for r in c.fetchall()]
        print(f"\n[{label}]")
        for t in tables:
            c.execute(f"PRAGMA index_list('{t}')")
            indexes = c.fetchall()
            c.execute(f"SELECT COUNT(*) FROM '{t}'")
            cnt = c.fetchone()[0]
            idx_names = [i[1] for i in indexes]
            print(f"  {t}: {cnt:,} rows, {len(indexes)} indexes: {idx_names}")
        conn.close()


if __name__ == '__main__':
    optimize_quant_system()
    optimize_history_recommendation()
    print_final_index_status()
    print("\n[完成] 数据库优化结束")
