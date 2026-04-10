"""
信号数据访问对象

提供信号的增删改查操作
"""

import json
import sqlite3
import logging
from typing import List, Dict, Optional
from datetime import datetime

from src.models.signal import Signal, SignalType, SignalStatus

logger = logging.getLogger(__name__)


class SignalDAO:
    """信号数据访问对象"""

    def __init__(self, db_path: str = "data/quant_system.db"):
        """
        初始化SignalDAO

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path

    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
        return sqlite3.connect(self.db_path)

    def save_signal(self, signal: Signal) -> bool:
        """
        保存信号

        Args:
            signal: 信号对象

        Returns:
            是否保存成功
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            sql = """
                INSERT INTO signals (
                    signal_id, ts_code, name, signal_type, signal_category,
                    strategy_type, trigger_time, trigger_conditions, reason,
                    suggestion, suggested_price, suggested_position, reduce_ratio,
                    priority_score, priority_level, current_profit, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """

            cursor.execute(sql, (
                signal.signal_id,
                signal.ts_code,
                signal.name,
                signal.signal_type.value,
                signal.signal_category.value if signal.signal_category else None,
                signal.strategy_type.value if signal.strategy_type else None,
                signal.trigger_time.isoformat() if signal.trigger_time else None,
                json.dumps(signal.trigger_conditions, ensure_ascii=False),
                signal.reason,
                signal.suggestion,
                signal.suggested_price,
                signal.suggested_position,
                signal.reduce_ratio,
                signal.priority_score,
                signal.priority_level.value if signal.priority_level else None,
                signal.current_profit,
                signal.status.value
            ))

            conn.commit()
            logger.info(f"信号已保存: {signal.signal_id}")
            return True

        except Exception as e:
            logger.error(f"保存信号失败: {e}")
            return False

        finally:
            conn.close()

    def get_signal_by_id(self, signal_id: str) -> Optional[Dict]:
        """
        根据信号ID获取信号

        Args:
            signal_id: 信号ID

        Returns:
            信号字典，如果不存在则返回None
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            sql = "SELECT * FROM signals WHERE signal_id = ?"
            cursor.execute(sql, (signal_id,))
            row = cursor.fetchone()

            if row:
                columns = [description[0] for description in cursor.description]
                signal_dict = dict(zip(columns, row))
                return signal_dict

            return None

        except Exception as e:
            logger.error(f"获取信号失败: {e}")
            return None

        finally:
            conn.close()

    def get_signals_by_filters(self, filters: Dict) -> List[Dict]:
        """
        根据筛选条件查询信号

        Args:
            filters: 筛选条件
                - ts_code: 股票代码
                - signal_type: 信号类型
                - signal_category: 信号类别
                - strategy_type: 策略类型
                - start_date: 开始日期
                - end_date: 结束日期
                - status: 信号状态

        Returns:
            信号列表
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            sql = "SELECT * FROM signals WHERE 1=1"
            params = []

            if 'ts_code' in filters:
                sql += " AND ts_code = ?"
                params.append(filters['ts_code'])

            if 'signal_type' in filters:
                sql += " AND signal_type = ?"
                params.append(filters['signal_type'])

            if 'signal_category' in filters:
                sql += " AND signal_category = ?"
                params.append(filters['signal_category'])

            if 'strategy_type' in filters:
                sql += " AND strategy_type = ?"
                params.append(filters['strategy_type'])

            if 'start_date' in filters:
                sql += " AND trigger_time >= ?"
                params.append(filters['start_date'])

            if 'end_date' in filters:
                sql += " AND trigger_time <= ?"
                params.append(filters['end_date'])

            if 'status' in filters:
                sql += " AND status = ?"
                params.append(filters['status'])

            sql += " ORDER BY trigger_time DESC"

            cursor.execute(sql, params)
            rows = cursor.fetchall()

            columns = [description[0] for description in cursor.description]
            signals = [dict(zip(columns, row)) for row in rows]

            return signals

        except Exception as e:
            logger.error(f"查询信号失败: {e}")
            return []

        finally:
            conn.close()

    def update_signal_status(self, signal_id: str, status: SignalStatus, confirm_time: datetime = None) -> bool:
        """
        更新信号状态

        Args:
            signal_id: 信号ID
            status: 新状态
            confirm_time: 确认时间（可选）

        Returns:
            是否更新成功
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            if confirm_time:
                sql = """
                    UPDATE signals
                    SET status = ?, confirm_time = ?
                    WHERE signal_id = ?
                """
                cursor.execute(sql, (status.value, confirm_time.isoformat(), signal_id))
            else:
                sql = """
                    UPDATE signals
                    SET status = ?
                    WHERE signal_id = ?
                """
                cursor.execute(sql, (status.value, signal_id))

            conn.commit()
            logger.info(f"信号状态已更新: {signal_id} -> {status.value}")
            return True

        except Exception as e:
            logger.error(f"更新信号状态失败: {e}")
            return False

        finally:
            conn.close()

    def get_signal_statistics(self, start_date: str = None, end_date: str = None) -> Dict:
        """
        获取信号统计

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
            sql_total = "SELECT COUNT(*) FROM signals WHERE 1=1"
            params = []

            if start_date:
                sql_total += " AND trigger_time >= ?"
                params.append(start_date)

            if end_date:
                sql_total += " AND trigger_time <= ?"
                params.append(end_date)

            cursor.execute(sql_total, params)
            total = cursor.fetchone()[0]

            # 按类型统计
            sql_by_type = """
                SELECT signal_type, COUNT(*) as count
                FROM signals WHERE 1=1
            """
            if start_date:
                sql_by_type += " AND trigger_time >= ?"
            if end_date:
                sql_by_type += " AND trigger_time <= ?"
            sql_by_type += " GROUP BY signal_type"

            cursor.execute(sql_by_type, params)
            by_type = {row[0]: row[1] for row in cursor.fetchall()}

            # 按状态统计
            sql_by_status = """
                SELECT status, COUNT(*) as count
                FROM signals WHERE 1=1
            """
            if start_date:
                sql_by_status += " AND trigger_time >= ?"
            if end_date:
                sql_by_status += " AND trigger_time <= ?"
            sql_by_status += " GROUP BY status"

            cursor.execute(sql_by_status, params)
            by_status = {row[0]: row[1] for row in cursor.fetchall()}

            # 按策略统计
            sql_by_strategy = """
                SELECT strategy_type, COUNT(*) as count
                FROM signals WHERE 1=1
            """
            if start_date:
                sql_by_strategy += " AND trigger_time >= ?"
            if end_date:
                sql_by_strategy += " AND trigger_time <= ?"
            sql_by_strategy += " GROUP BY strategy_type"

            cursor.execute(sql_by_strategy, params)
            by_strategy = {row[0]: row[1] for row in cursor.fetchall()}

            # 执行率统计
            sql_execution_rate = """
                SELECT
                    COUNT(CASE WHEN status = 'confirmed' THEN 1 END) as confirmed,
                    COUNT(*) as total
                FROM signals WHERE 1=1
            """
            if start_date:
                sql_execution_rate += " AND trigger_time >= ?"
            if end_date:
                sql_execution_rate += " AND trigger_time <= ?"

            cursor.execute(sql_execution_rate, params)
            confirmed, total_count = cursor.fetchone()
            execution_rate = (confirmed / total_count * 100) if total_count > 0 else 0

            return {
                'total': total,
                'by_type': by_type,
                'by_status': by_status,
                'by_strategy': by_strategy,
                'execution_rate': round(execution_rate, 2)
            }

        except Exception as e:
            logger.error(f"获取信号统计失败: {e}")
            return {}

        finally:
            conn.close()

    def get_pending_signals(self) -> List[Dict]:
        """
        获取所有待确认的信号

        Returns:
            待确认信号列表
        """
        return self.get_signals_by_filters({'status': 'pending'})

    def get_recent_signals(self, limit: int = 10) -> List[Dict]:
        """
        获取最近的信号

        Args:
            limit: 返回数量限制

        Returns:
            最近信号列表
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            sql = """
                SELECT * FROM signals
                ORDER BY trigger_time DESC
                LIMIT ?
            """
            cursor.execute(sql, (limit,))
            rows = cursor.fetchall()

            columns = [description[0] for description in cursor.description]
            signals = [dict(zip(columns, row)) for row in rows]

            return signals

        except Exception as e:
            logger.error(f"获取最近信号失败: {e}")
            return []

        finally:
            conn.close()
