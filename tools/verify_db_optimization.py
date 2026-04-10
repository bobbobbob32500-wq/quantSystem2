import sqlite3
import os
import time

QUANT_DB = 'data/database/quant_system.db'
HIST_DB = 'data/history_recommendation.db'

print("=" * 60)
print("优化后数据库状态报告")
print("=" * 60)

# 1. 文件大小
for path, label in [(QUANT_DB, 'quant_system'), (HIST_DB, 'history_recommendation')]:
    sz = os.path.getsize(path) / 1024 / 1024
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("PRAGMA page_count")
    pc = c.fetchone()[0]
    c.execute("PRAGMA freelist_count")
    fl = c.fetchone()[0]
    free_pct = fl / pc * 100 if pc else 0
    conn.close()
    print(f"{label}: {sz:.2f} MB | pages={pc} | freelist={fl} ({free_pct:.1f}% waste)")

print()
print("=" * 60)
print("关键查询执行计划验证")
print("=" * 60)

conn = sqlite3.connect(QUANT_DB)
c = conn.cursor()

# 2. FeedbackGuard 高频查询
print("\n[1] FeedbackGuard signal_feedback_detail 查询:")
c.execute(
    "EXPLAIN QUERY PLAN "
    "SELECT COUNT(*), AVG(net_return) FROM signal_feedback_detail "
    "WHERE source_type='pre_market_recommendation' AND direction='buy' "
    "AND horizon=2 AND signal_date>='20260101' AND signal_date<='20260327'"
)
for row in c.fetchall():
    print(f"  {row[3]}")

# 3. stock_daily 按股票+日期查询
print("\n[2] stock_daily 股票+日期范围查询:")
c.execute(
    "EXPLAIN QUERY PLAN SELECT * FROM stock_daily "
    "WHERE ts_code='000001.SZ' AND trade_date>='20260101' ORDER BY trade_date DESC LIMIT 60"
)
for row in c.fetchall():
    print(f"  {row[3]}")

# 4. factor_values 按日期+因子批量查询
print("\n[3] factor_values 按日期+因子批量读取（选股核心路径）:")
c.execute(
    "EXPLAIN QUERY PLAN "
    "SELECT ts_code, factor_name, factor_value FROM factor_values "
    "WHERE trade_date='20260327' AND factor_name IN ('trend_score','momentum_score')"
)
for row in c.fetchall():
    print(f"  {row[3]}")

# 5. get_latest_trade_date
print("\n[4] get_latest_trade_date (MAX trade_date):")
c.execute("EXPLAIN QUERY PLAN SELECT MAX(trade_date) FROM stock_daily")
for row in c.fetchall():
    print(f"  {row[3]}")

# 6. 选股按个股+日期查询 factor_values
print("\n[5] factor_values 按股票+日期+因子精确查询:")
c.execute(
    "EXPLAIN QUERY PLAN "
    "SELECT factor_value FROM factor_values "
    "WHERE ts_code='000001.SZ' AND trade_date='20260327' AND factor_name='trend_score'"
)
for row in c.fetchall():
    print(f"  {row[3]}")

conn.close()

# 7. 实际查询耗时对比
print()
print("=" * 60)
print("关键查询实际耗时")
print("=" * 60)

conn = sqlite3.connect(QUANT_DB)
c = conn.cursor()

benchmarks = [
    (
        "stock_daily 单股60日数据",
        "SELECT * FROM stock_daily WHERE ts_code='000001.SZ' "
        "AND trade_date>='20260101' ORDER BY trade_date DESC LIMIT 60"
    ),
    (
        "stock_daily 全市场最新交易日",
        "SELECT MAX(trade_date) FROM stock_daily"
    ),
    (
        "factor_values 单日全因子批量读取",
        "SELECT ts_code, factor_name, factor_value FROM factor_values "
        "WHERE trade_date='20260327' AND factor_name IN ('trend_score','momentum_score','pullback_score','volume_score')"
    ),
    (
        "signal_feedback_detail FeedbackGuard查询",
        "SELECT COUNT(*), AVG(net_return), AVG(CASE WHEN net_return>0 THEN 1.0 ELSE 0.0 END) "
        "FROM signal_feedback_detail WHERE source_type='pre_market_recommendation' "
        "AND direction='buy' AND horizon=2 AND signal_date>='20251001' AND signal_date<='20260327'"
    ),
]

for desc, sql in benchmarks:
    t0 = time.perf_counter()
    c.execute(sql)
    rows = c.fetchall()
    elapsed_ms = (time.perf_counter() - t0) * 1000
    print(f"  {desc}: {elapsed_ms:.2f}ms ({len(rows)} rows)")

conn.close()

# 8. intraday_data 行数确认
conn2 = sqlite3.connect(HIST_DB)
c2 = conn2.cursor()
c2.execute("SELECT COUNT(*) FROM intraday_data")
cnt = c2.fetchone()[0]
c2.execute("SELECT MIN(trade_date), MAX(trade_date) FROM intraday_data")
r = c2.fetchone()
print(f"\n  intraday_data: {cnt:,} rows | 日期范围: {r[0]} ~ {r[1]}")
conn2.close()

print()
print("[完成] 验证报告输出完毕")
