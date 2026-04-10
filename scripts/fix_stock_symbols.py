# -*- coding: utf-8 -*-
"""
修复股票代码格式
为缺少市场后缀的股票代码添加.SH或.SZ后缀
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import sqlite3
from src.modules.backtest.data_validator import StockCodeValidator

def fix_stock_symbols():
    """修复股票代码"""
    db_path = "data/history_recommendation.db"
    
    if not os.path.exists(db_path):
        print(f"✗ 数据库文件不存在: {db_path}")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 检查表是否存在
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='recommendations'")
    if not cursor.fetchone():
        print("✗ recommendations 表不存在")
        conn.close()
        return
    
    # 获取所有股票代码
    cursor.execute("SELECT DISTINCT symbol FROM recommendations")
    symbols = [row[0] for row in cursor.fetchall()]
    
    print(f"发现 {len(symbols)} 个股票代码")
    print("\n修复前的股票代码:")
    for symbol in symbols[:10]:
        print(f"  {symbol}")
    
    # 修复股票代码
    fixed_count = 0
    for symbol in symbols:
        if '.' not in symbol:
            # 根据前缀判断市场
            if symbol.startswith('6') or symbol.startswith('8'):
                new_symbol = f"{symbol}.SH"
            elif symbol.startswith('0') or symbol.startswith('3'):
                new_symbol = f"{symbol}.SZ"
            else:
                continue
            
            # 更新recommendations表
            cursor.execute(
                "UPDATE recommendations SET symbol = ? WHERE symbol = ?",
                (new_symbol, symbol)
            )
            
            # 更新intraday_data表
            cursor.execute(
                "UPDATE intraday_data SET symbol = ? WHERE symbol = ?",
                (new_symbol, symbol)
            )
            
            fixed_count += 1
            print(f"  修复: {symbol} -> {new_symbol}")
    
    conn.commit()
    conn.close()
    
    print(f"\n✓ 修复完成，共修复 {fixed_count} 个股票代码")

if __name__ == "__main__":
    fix_stock_symbols()
