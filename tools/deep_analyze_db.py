import sqlite3
import os

def deep_analyze(db_path, label):
    if not os.path.exists(db_path):
        print(f"{label}: not found")
        return
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    print(f"\n{'='*60}")
    print(f"[{label}] 深度数据质量检查")
    print(f"{'='*60}")

    c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in c.fetchall() if not r[0].startswith('sqlite_')]

    for t in tables:
        print(f"\n--- 表: {t} ---")
        c.execute(f"SELECT COUNT(*) FROM '{t}'")
        total = c.fetchone()[0]
        print(f"  总行数: {total:,}")

        c.execute(f"PRAGMA table_info('{t}')")
        cols_info = c.fetchall()
        cols = [ci[1] for ci in cols_info]

        # 检查重复行（基于主要业务字段）
        if t == 'stock_daily':
            c.execute("SELECT ts_code, trade_date, COUNT(*) as cnt FROM stock_daily GROUP BY ts_code, trade_date HAVING cnt > 1 LIMIT 10")
            dups = c.fetchall()
            print(f"  重复(ts_code+trade_date): {len(dups)} 组")
            if dups:
                for d in dups[:5]:
                    print(f"    {dict(d)}")

            c.execute("SELECT MIN(trade_date), MAX(trade_date) FROM stock_daily")
            r = c.fetchone()
            print(f"  日期范围: {r[0]} ~ {r[1]}")

            c.execute("SELECT trade_date, COUNT(*) as cnt FROM stock_daily GROUP BY trade_date ORDER BY trade_date DESC LIMIT 5")
            for r in c.fetchall():
                print(f"  最近交易日数据量: {dict(r)}")

        elif t == 'factor_values':
            c.execute("SELECT ts_code, trade_date, factor_name, COUNT(*) as cnt FROM factor_values GROUP BY ts_code, trade_date, factor_name HAVING cnt > 1 LIMIT 10")
            dups = c.fetchall()
            print(f"  重复(ts_code+trade_date+factor_name): {len(dups)} 组")
            c.execute("SELECT factor_name, COUNT(*) as cnt FROM factor_values GROUP BY factor_name ORDER BY cnt DESC")
            fns = c.fetchall()
            print(f"  因子类型 ({len(fns)}个):")
            for fn in fns:
                print(f"    {fn[0]}: {fn[1]:,} rows")
            c.execute("SELECT MIN(trade_date), MAX(trade_date) FROM factor_values")
            r = c.fetchone()
            print(f"  日期范围: {r[0]} ~ {r[1]}")

        elif t == 'intraday_data':
            c.execute("SELECT symbol, trade_time, COUNT(*) as cnt FROM intraday_data GROUP BY symbol, trade_time HAVING cnt > 1 LIMIT 10")
            dups = c.fetchall()
            print(f"  重复(symbol+trade_time): {len(dups)} 组")
            c.execute("SELECT MIN(trade_date), MAX(trade_date) FROM intraday_data")
            r = c.fetchone()
            print(f"  日期范围: {r[0]} ~ {r[1]}")
            c.execute("SELECT trade_date, COUNT(*) as cnt FROM intraday_data GROUP BY trade_date ORDER BY trade_date DESC LIMIT 10")
            for r in c.fetchall():
                print(f"  {dict(r)}")
            c.execute("SELECT COUNT(DISTINCT symbol) FROM intraday_data")
            print(f"  唯一股票数: {c.fetchone()[0]}")

        elif t == 'recommendations':
            c.execute("SELECT MIN(recommendation_date), MAX(recommendation_date) FROM recommendations")
            r = c.fetchone()
            print(f"  日期范围: {r[0]} ~ {r[1]}")
            c.execute("SELECT status, COUNT(*) FROM recommendations GROUP BY status")
            for r in c.fetchall():
                print(f"  状态分布: {dict(r)}")

        # NULL值检查（每列）
        null_summary = []
        for col in cols:
            try:
                c.execute(f"SELECT COUNT(*) FROM '{t}' WHERE '{col}' IS NULL")
                null_cnt = c.fetchone()[0]
                if null_cnt > 0:
                    null_summary.append(f"{col}:{null_cnt}")
            except Exception:
                pass
        if null_summary:
            print(f"  NULL值列: {', '.join(null_summary)}")

    conn.close()

deep_analyze('data/database/quant_system.db', 'quant_system')
deep_analyze('data/history_recommendation.db', 'history_recommendation')
