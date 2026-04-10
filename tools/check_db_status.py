# -*- coding: utf-8 -*-
import sqlite3, os, sys

def check_db(db_path, label):
    if not os.path.exists(db_path):
        print(f"{label}: NOT FOUND ({db_path})")
        return
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cur.fetchall()]
    print(f"\n=== {label} ({db_path}) ===")
    print(f"Tables: {tables}")
    key_tables = ['stock_daily', 'stock_basic', 'factor_values', 'index_daily',
                  'recommendations', 'intraday_data', 'signal_feedback_detail']
    for t in key_tables:
        if t not in tables:
            print(f"  {t:<30} NOT FOUND")
            continue
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        cnt = cur.fetchone()[0]
        if cnt == 0:
            print(f"  {t:<30} EMPTY")
            continue
        # date range
        try:
            cur.execute(f"SELECT MIN(trade_date), MAX(trade_date) FROM {t}")
            mn, mx = cur.fetchone()
            print(f"  {t:<30} {cnt:>10} rows  date: {mn} ~ {mx}")
        except Exception:
            try:
                cur.execute(f"SELECT MIN(recommendation_date), MAX(recommendation_date) FROM {t}")
                mn, mx = cur.fetchone()
                print(f"  {t:<30} {cnt:>10} rows  date: {mn} ~ {mx}")
            except Exception:
                print(f"  {t:<30} {cnt:>10} rows")
    # stock_daily distinct stocks
    if 'stock_daily' in tables:
        cur.execute("SELECT COUNT(DISTINCT ts_code) FROM stock_daily")
        n = cur.fetchone()[0]
        print(f"  stock_daily distinct stocks: {n}")
    # factor_values distinct factors
    if 'factor_values' in tables:
        cur.execute("SELECT DISTINCT factor_name FROM factor_values")
        factors = [r[0] for r in cur.fetchall()]
        print(f"  factor_values factors: {factors}")
    conn.close()

check_db('data/database/quant_system.db', 'quant_system')
check_db('data/history_recommendation.db', 'history_recommendation')
