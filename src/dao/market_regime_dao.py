"""
市场状态数据访问对象

提供市场状态的增删改查操作
"""

import json
import sqlite3
import logging
from typing import List, Dict, Optional
from datetime import datetime

from src.models.market_regime import MarketRegimeResult

logger = logging.getLogger(__name__)


class MarketRegimeDAO:
    """市场状态数据访问对象"""

    def __init__(self, db_path: str = "data/quant_system.db"):
        """
        初始化MarketRegimeDAO

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path

    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
        return sqlite3.connect(self.db_path)

    def save_market_regime(self, regime_result: MarketRegimeResult) -> bool:
        """
        保存市场状态

        Args:
            regime_result: 市场状态结果

        Returns:
            是否保存成功
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            sql = """
                INSERT INTO market_regime_history (
                    regime, trend_state, money_state, max_position,
                    trigger_time, trend_details, money_details
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """

            cursor.execute(sql, (
                regime_result.regime.value,
                regime_result.trend_state.value,
                regime_result.money_state.value,
                regime_result.max_position[1],  # 保存最大仓位
                regime_result.trigger_time.isoformat(),
                json.dumps(regime_result.trend_details, ensure_ascii=False),
                json.dumps(regime_result.money_details, ensure_ascii=False)
            ))

            conn.commit()
            logger.info(f"市场状态已保存: {regime_result.regime.value}")
            return True

        except Exception as e:
            logger.error(f"保存市场状态失败: {e}")
            return False

        finally:
            conn.close()

    def get_latest_regime(self) -> Optional[Dict]:
        """
        获取最新的市场状态

        Returns:
            市场状态字典，如果不存在则返回None
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            sql = """
                SELECT * FROM market_regime_history
                ORDER BY trigger_time DESC
                LIMIT 1
            """
            cursor.execute(sql)
            row = cursor.fetchone()

            if row:
                columns = [description[0] for description in cursor.description]
                regime_dict = dict(zip(columns, row))
                return regime_dict

            return None

        except Exception as e:
            logger.error(f"获取最新市场状态失败: {e}")
            return None

        finally:
            conn.close()

    def get_regime_history(self, start_date: str = None, end_date: str = None,
                          limit: int = 100) -> List[Dict]:
        """
        获取市场状态历史

        Args:
            start_date: 开始日期
            end_date: 结束日期
            limit: 返回数量限制

        Returns:
            市场状态历史列表
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            sql = "SELECT * FROM market_regime_history WHERE 1=1"
            params = []

            if start_date:
                sql += " AND trigger_time >= ?"
                params.append(start_date)

            if end_date:
                sql += " AND trigger_time <= ?"
                params.append(end_date)

            sql += " ORDER BY trigger_time DESC LIMIT ?"
            params.append(limit)

            cursor.execute(sql, params)
            rows = cursor.fetchall()

            columns = [description[0] for description in cursor.description]
            regimes = [dict(zip(columns, row)) for row in rows]

            return regimes

        except Exception as e:
            logger.error(f"获取市场状态历史失败: {e}")
            return []

        finally:
            conn.close()

    def get_regime_statistics(self, start_date: str = None, end_date: str = None) -> Dict:
        """
        获取市场状态统计

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
            sql_total = "SELECT COUNT(*) FROM market_regime_history WHERE 1=1"
            params = []

            if start_date:
                sql_total += " AND trigger_time >= ?"
                params.append(start_date)

            if end_date:
                sql_total += " AND trigger_time <= ?"
                params.append(end_date)

            cursor.execute(sql_total, params)
            total = cursor.fetchone()[0]

            # 按状态统计
            sql_by_regime = """
                SELECT regime, COUNT(*) as count
                FROM market_regime_history WHERE 1=1
            """
            if start_date:
                sql_by_regime += " AND trigger_time >= ?"
            if end_date:
                sql_by_regime += " AND trigger_time <= ?"
            sql_by_regime += " GROUP BY regime"

            cursor.execute(sql_by_regime, params)
            by_regime = {row[0]: row[1] for row in cursor.fetchall()}

            return {
                'total': total,
                'by_regime': by_regime
            }

        except Exception as e:
            logger.error(f"获取市场状态统计失败: {e}")
            return {}

        finally:
            conn.close()
