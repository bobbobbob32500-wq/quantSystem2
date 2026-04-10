"""
信号冷却数据访问对象

提供信号冷却的增删改查操作
"""

import sqlite3
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class SignalCooldownDAO:
    """信号冷却数据访问对象"""

    def __init__(self, db_path: str = "data/quant_system.db"):
        """
        初始化SignalCooldownDAO

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path

    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
        return sqlite3.connect(self.db_path)

    def set_cooldown(self, ts_code: str, cooldown_days: int = 1) -> bool:
        """
        设置信号冷却时间

        Args:
            ts_code: 股票代码
            cooldown_days: 冷却天数

        Returns:
            是否设置成功
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cooldown_until = datetime.now() + timedelta(days=cooldown_days)

            sql = """
                INSERT OR REPLACE INTO signal_cooldown (ts_code, cooldown_until)
                VALUES (?, ?)
            """
            cursor.execute(sql, (ts_code, cooldown_until.isoformat()))

            conn.commit()
            logger.info(f"信号冷却已设置: {ts_code} -> {cooldown_until.isoformat()}")
            return True

        except Exception as e:
            logger.error(f"设置信号冷却失败: {e}")
            return False

        finally:
            conn.close()

    def is_in_cooldown(self, ts_code: str) -> bool:
        """
        检查股票是否在冷却期

        Args:
            ts_code: 股票代码

        Returns:
            是否在冷却期
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            sql = "SELECT cooldown_until FROM signal_cooldown WHERE ts_code = ?"
            cursor.execute(sql, (ts_code,))
            row = cursor.fetchone()

            if row:
                cooldown_until = datetime.fromisoformat(row[0])
                is_cooldown = datetime.now() < cooldown_until

                # 如果冷却期已过，删除记录
                if not is_cooldown:
                    self.remove_cooldown(ts_code)

                return is_cooldown

            return False

        except Exception as e:
            logger.error(f"检查信号冷却失败: {e}")
            return False

        finally:
            conn.close()

    def remove_cooldown(self, ts_code: str) -> bool:
        """
        移除信号冷却

        Args:
            ts_code: 股票代码

        Returns:
            是否移除成功
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            sql = "DELETE FROM signal_cooldown WHERE ts_code = ?"
            cursor.execute(sql, (ts_code,))

            conn.commit()
            logger.info(f"信号冷却已移除: {ts_code}")
            return True

        except Exception as e:
            logger.error(f"移除信号冷却失败: {e}")
            return False

        finally:
            conn.close()

    def get_cooldown_list(self) -> list:
        """
        获取所有在冷却期的股票列表

        Returns:
            冷却期股票列表
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            sql = "SELECT ts_code, cooldown_until FROM signal_cooldown"
            cursor.execute(sql)
            rows = cursor.fetchall()

            cooldown_list = []
            for row in rows:
                ts_code, cooldown_until_str = row
                cooldown_until = datetime.fromisoformat(cooldown_until_str)

                if datetime.now() < cooldown_until:
                    cooldown_list.append({
                        'ts_code': ts_code,
                        'cooldown_until': cooldown_until.isoformat(),
                        'remaining_seconds': (cooldown_until - datetime.now()).total_seconds()
                    })
                else:
                    # 清理过期记录
                    self.remove_cooldown(ts_code)

            return cooldown_list

        except Exception as e:
            logger.error(f"获取冷却列表失败: {e}")
            return []

        finally:
            conn.close()
