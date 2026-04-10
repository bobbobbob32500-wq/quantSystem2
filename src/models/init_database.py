"""
数据库初始化脚本

创建所有必要的数据表
"""

import sqlite3
import os
from pathlib import Path


def init_database(db_path: str = "data/quant_system.db"):
    """
    初始化数据库，创建所有表

    Args:
        db_path: 数据库文件路径
    """
    # 确保数据目录存在
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir)

    # 连接数据库
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 1. 创建信号表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id VARCHAR(50) UNIQUE NOT NULL,
            ts_code VARCHAR(20) NOT NULL,
            name VARCHAR(50) NOT NULL,
            signal_type VARCHAR(20) NOT NULL,
            signal_category VARCHAR(20),
            strategy_type VARCHAR(20),
            trigger_time DATETIME NOT NULL,
            trigger_conditions TEXT,
            reason TEXT NOT NULL,
            suggestion TEXT,
            suggested_price REAL,
            suggested_position REAL,
            reduce_ratio REAL,
            priority_score REAL,
            priority_level VARCHAR(20),
            current_profit REAL,
            status VARCHAR(20) DEFAULT 'pending',
            confirm_time DATETIME,
            create_time DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 创建索引
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_signals_ts_code ON signals(ts_code)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_signals_signal_type ON signals(signal_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_signals_trigger_time ON signals(trigger_time)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status)")

    # 2. 创建交易计划表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trade_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id VARCHAR(50) UNIQUE NOT NULL,
            signal_id VARCHAR(50) NOT NULL,
            ts_code VARCHAR(20) NOT NULL,
            name VARCHAR(50) NOT NULL,
            operation_type VARCHAR(20) NOT NULL,
            suggested_price REAL NOT NULL,
            suggested_quantity INTEGER NOT NULL,
            execute_window_start DATETIME NOT NULL,
            execute_window_end DATETIME NOT NULL,
            status VARCHAR(20) DEFAULT 'pending',
            execute_status TEXT,
            execute_time DATETIME,
            create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (signal_id) REFERENCES signals(signal_id)
        )
    """)

    # 创建索引
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_trade_plans_ts_code ON trade_plans(ts_code)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_trade_plans_status ON trade_plans(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_trade_plans_execute_window ON trade_plans(execute_window_start, execute_window_end)")

    # 3. 创建市场状态历史表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS market_regime_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            regime VARCHAR(30) NOT NULL,
            trend_state VARCHAR(20) NOT NULL,
            money_state VARCHAR(20) NOT NULL,
            max_position REAL NOT NULL,
            trigger_time DATETIME NOT NULL,
            trend_details TEXT,
            money_details TEXT,
            create_time DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 创建索引
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_market_regime_trigger_time ON market_regime_history(trigger_time)")

    # 4. 创建信号冷却表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS signal_cooldown (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_code VARCHAR(20) UNIQUE NOT NULL,
            cooldown_until DATETIME NOT NULL,
            create_time DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 创建索引
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_signal_cooldown_cooldown_until ON signal_cooldown(cooldown_until)")

    # 5. 创建信号冲突日志表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS signal_conflict_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_code VARCHAR(20) NOT NULL,
            conflict_signals TEXT NOT NULL,
            resolved_signal TEXT NOT NULL,
            resolved_action VARCHAR(50) NOT NULL,
            reason TEXT,
            create_time DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 创建索引
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_signal_conflict_log_ts_code ON signal_conflict_log(ts_code)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_signal_conflict_log_create_time ON signal_conflict_log(create_time)")

    # 提交更改
    conn.commit()

    # 打印创建信息
    print(f"数据库初始化完成: {db_path}")
    print(f"已创建的表:")
    print(f"  - signals (信号表)")
    print(f"  - trade_plans (交易计划表)")
    print(f"  - market_regime_history (市场状态历史表)")
    print(f"  - signal_cooldown (信号冷却表)")
    print(f"  - signal_conflict_log (信号冲突日志表)")

    # 关闭连接
    conn.close()


if __name__ == "__main__":
    # 初始化数据库
    init_database()
