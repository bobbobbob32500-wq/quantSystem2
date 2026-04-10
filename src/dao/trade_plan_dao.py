"""
交易计划数据访问对象

提供交易计划的增删改查操作
"""

import sqlite3
import logging
from typing import List, Dict, Optional
from datetime import datetime

from src.models.trade_plan import TradePlan, TradePlanStatus, OperationType

logger = logging.getLogger(__name__)


class TradePlanDAO:
    """交易计划数据访问对象"""

    def __init__(self, db_path: str = "data/quant_system.db"):
        """
        初始化TradePlanDAO

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path

    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
        return sqlite3.connect(self.db_path)

    def save_trade_plan(self, plan: TradePlan) -> bool:
        """
        保存交易计划

        Args:
            plan: 交易计划对象

        Returns:
            是否保存成功
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            sql = """
                INSERT INTO trade_plans (
                    plan_id, signal_id, ts_code, name, operation_type,
                    suggested_price, suggested_quantity, execute_window_start,
                    execute_window_end, status, execute_status, execute_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """

            cursor.execute(sql, (
                plan.plan_id,
                plan.signal_id,
                plan.ts_code,
                plan.name,
                plan.operation_type.value,
                plan.suggested_price,
                plan.suggested_quantity,
                plan.execute_window_start.isoformat(),
                plan.execute_window_end.isoformat(),
                plan.status.value,
                plan.execute_status,
                plan.execute_time.isoformat() if plan.execute_time else None
            ))

            conn.commit()
            logger.info(f"交易计划已保存: {plan.plan_id}")
            return True

        except Exception as e:
            logger.error(f"保存交易计划失败: {e}")
            return False

        finally:
            conn.close()

    def get_trade_plan_by_id(self, plan_id: str) -> Optional[Dict]:
        """
        根据计划ID获取交易计划

        Args:
            plan_id: 计划ID

        Returns:
            交易计划字典，如果不存在则返回None
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            sql = "SELECT * FROM trade_plans WHERE plan_id = ?"
            cursor.execute(sql, (plan_id,))
            row = cursor.fetchone()

            if row:
                columns = [description[0] for description in cursor.description]
                plan_dict = dict(zip(columns, row))
                return plan_dict

            return None

        except Exception as e:
            logger.error(f"获取交易计划失败: {e}")
            return None

        finally:
            conn.close()

    def get_pending_plans(self) -> List[Dict]:
        """
        获取所有待执行的交易计划

        Returns:
            待执行计划列表
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            sql = """
                SELECT * FROM trade_plans
                WHERE status = 'pending'
                ORDER BY execute_window_start ASC
            """
            cursor.execute(sql)
            rows = cursor.fetchall()

            columns = [description[0] for description in cursor.description]
            plans = [dict(zip(columns, row)) for row in rows]

            return plans

        except Exception as e:
            logger.error(f"获取待执行计划失败: {e}")
            return []

        finally:
            conn.close()

    def update_plan_status(self, plan_id: str, status: TradePlanStatus,
                          execute_status: str = None, execute_time: datetime = None) -> bool:
        """
        更新计划状态

        Args:
            plan_id: 计划ID
            status: 新状态
            execute_status: 执行状态说明
            execute_time: 执行时间

        Returns:
            是否更新成功
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            if execute_time:
                sql = """
                    UPDATE trade_plans
                    SET status = ?, execute_status = ?, execute_time = ?
                    WHERE plan_id = ?
                """
                cursor.execute(sql, (status.value, execute_status, execute_time.isoformat(), plan_id))
            else:
                sql = """
                    UPDATE trade_plans
                    SET status = ?, execute_status = ?
                    WHERE plan_id = ?
                """
                cursor.execute(sql, (status.value, execute_status, plan_id))

            conn.commit()
            logger.info(f"交易计划状态已更新: {plan_id} -> {status.value}")
            return True

        except Exception as e:
            logger.error(f"更新交易计划状态失败: {e}")
            return False

        finally:
            conn.close()

    def cancel_plan(self, plan_id: str) -> bool:
        """
        取消交易计划

        Args:
            plan_id: 计划ID

        Returns:
            是否取消成功
        """
        return self.update_plan_status(plan_id, TradePlanStatus.CANCELLED, "用户取消")

    def mark_plan_expired(self, plan_id: str) -> bool:
        """
        标记交易计划为已过期

        Args:
            plan_id: 计划ID

        Returns:
            是否标记成功
        """
        return self.update_plan_status(plan_id, TradePlanStatus.EXPIRED, "执行时间窗口已过期")

    def get_plans_by_stock(self, ts_code: str) -> List[Dict]:
        """
        获取某只股票的所有交易计划

        Args:
            ts_code: 股票代码

        Returns:
            交易计划列表
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            sql = "SELECT * FROM trade_plans WHERE ts_code = ? ORDER BY create_time DESC"
            cursor.execute(sql, (ts_code,))
            rows = cursor.fetchall()

            columns = [description[0] for description in cursor.description]
            plans = [dict(zip(columns, row)) for row in rows]

            return plans

        except Exception as e:
            logger.error(f"获取股票交易计划失败: {e}")
            return []

        finally:
            conn.close()
