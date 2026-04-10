# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.core.config import ConfigManager
from src.core.database import DatabaseManager

config = ConfigManager()
db = DatabaseManager(config)

# 看20260401的amount分布
rows = db.query(
    "SELECT AVG(amount) as avg_amt, MIN(amount) as min_amt, MAX(amount) as max_amt, "
    "COUNT(*) as cnt FROM stock_daily WHERE trade_date='20260401'"
)
print("20260401 amount统计:", dict(rows[0]))

# 看几个典型值
rows2 = db.query(
    "SELECT ts_code, amount FROM stock_daily WHERE trade_date='20260401' "
    "ORDER BY amount DESC LIMIT 5"
)
print("TOP5 amount:")
for r in rows2:
    print(f"  {r['ts_code']}: {r['amount']}")

rows3 = db.query(
    "SELECT ts_code, amount FROM stock_daily WHERE trade_date='20260401' "
    "AND ts_code='600519.SH'"
)
if rows3:
    print(f"茅台amount: {rows3[0]['amount']}")
