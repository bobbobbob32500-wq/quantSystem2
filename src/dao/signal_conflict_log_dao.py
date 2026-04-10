"""
信号冲突日志数据访问对象

提供信号冲突日志的增删改查操作
"""

import json
import sqlite3
import logging
from typing import List, Dict
from datetime import datetime

logger = logging.getLogger(__name__)


class SignalConflictLogDAO:
    """信号冲突日志数据访问对象"""

    def __init__(self, db_path: str = "data/quant_system.db"):
        """
        初始化SignalConflictLogDAO

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path

    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
        return sqlite3.connect(self.db_path)

    def log_conflict(self, ts_code: str, conflict_signals: list,
                    resolved_signal: dict, resolved_action: str, reason: str = None) -> bool:
        """
        记录信号冲突

        Args:
            ts_code: 股票代码
            conflict_signals: 冲突信号列表
            resolved_signal: 解决的信号
            resolved_action: 解决动作
            reason: 忽略原因

        Returns:
            是否记录成功
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            sql = """
                INSERT INTO signal_conflict_log
                (ts_code, conflict_signals, resolved_signal, resolved_action, reason)
                VALUES (?, ?, ?, ?, ?)
            """

            cursor.execute(sql, (
                ts_code,
                json.dumps(conflict_signals, ensure_ascii=False),
                json.dumps(resolved_signal, ensure_ascii=False),
                resolved_action,
                reason
            ))

            conn.commit()
            logger.info(f"信号冲突已记录: {ts_code} -> {resolved_action}")
            return True

        except Exception as e:
            logger.error(f"记录信号冲突失败: {e}")
            return False

        finally:
            conn.close()

    def get_conflict_logs(self, ts_code: str = None, limit: int = 100) -> List[Dict]:
        """
        获取信号冲突日志

        Args:
            ts_code: 股票代码（可选）
            limit: 返回数量限制

        Returns:
            冲突日志列表
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            if ts_code:
                sql = """
                    SELECT * FROM signal_conflict_log
                    WHERE ts_code = ?
                    ORDER BY create_time DESC
                    LIMIT ?
                """
                cursor.execute(sql, (ts_code, limit))
            else:
                sql = """
                    SELECT * FROM signal_conflict_log
                    ORDER BY create_time DESC
                    LIMIT ?
                """
                cursor.execute(sql, (limit,))

            rows = cursor.fetchall()

            columns = [description[0] for description in cursor.description]
            logs = [dict(zip(columns, row)) for row in rows]

            return logs

        except Exception as e:
            logger.error(f"获取信号冲突日志失败: {e}")
            return []

        finally:
            conn.close()

    def get_conflict_statistics(self, start_date: str = None, end_date: str = None) -> Dict:
        """
        获取信号冲突统计

        Args:
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            统计数据
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # 总数统计
            sql_total = "SELECT COUNT(*) FROM signal_conflict_log WHERE 1=1"
            params = []

            if start_date:
                sql_total += " AND create_time >= ?"
                params.append(start_date)

            if end_date:
                sql_total += " AND create_time <= ?"
                params.append(end_date)

            cursor.execute(sql_total, params)
            total = cursor.fetchone()[0]

            # 按解决动作统计
            sql_by_action = """
                SELECT resolved_action, COUNT(*) as count
                FROM signal_conflict_log WHERE 1=1
            """
            if start_date:
                sql_by_action += " AND create_time >= ?"
            if end_date:
                sql_by_action += " AND create_time <= ?"
            sql_by_action += " GROUP BY resolved_action"

            cursor.execute(sql_by_action, params)
            by_action = {row[0]: row[1] for row in cursor.fetchall()}

            return {
                'total': total,
                'by_action': by_action
            }

        except Exception as e:
            logger.error(f"获取信号冲突统计失败: {e}")
            return {}

        finally:
            conn.close()
