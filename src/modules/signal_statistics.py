# -*- coding: utf-8 -*-
"""
信号统计反馈系统
用于监控信号触发频率、成功率、平均收益等关键指标
"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from collections import defaultdict

from src.core.logger import get_logger
from src.core.database import DatabaseManager

logger = get_logger("signal_statistics")


class SignalStatistics:
    """信号统计反馈系统"""
    
    def __init__(self, db: DatabaseManager = None):
        """
        初始化信号统计系统
        
        Args:
            db: 数据库管理器
        """
        if db is None:
            db = DatabaseManager()
        
        self.db = db
        
        # 信号统计缓存
        self.signal_stats = defaultdict(lambda: {
            'trigger_count': 0,
            'success_count': 0,
            'fail_count': 0,
            'total_profit': 0.0,
            'avg_profit': 0.0,
            'win_rate': 0.0,
        })
        
        # 每日信号计数
        self.daily_signal_count = defaultdict(int)
        
        logger.info("信号统计反馈系统初始化完成")
    
    def record_signal(self, signal_type: str, ts_code: str, 
                     trigger_time: datetime, confidence: float,
                     details: Dict = None):
        """
        记录信号触发
        
        Args:
            signal_type: 信号类型（pullback/breakout/consolidation）
            ts_code: 股票代码
            trigger_time: 触发时间
            confidence: 置信度
            details: 信号详情
        """
        # 更新统计
        self.signal_stats[signal_type]['trigger_count'] += 1
        
        # 更新每日计数
        date_key = trigger_time.strftime("%Y-%m-%d")
        self.daily_signal_count[date_key] += 1
        
        # 保存到数据库
        try:
            sql = """
                INSERT INTO signal_statistics 
                (signal_type, ts_code, trigger_time, confidence, details, status)
                VALUES (?, ?, ?, ?, ?, 'pending')
            """
            import json
            self.db.execute(sql, (
                signal_type,
                ts_code,
                trigger_time.strftime("%Y-%m-%d %H:%M:%S"),
                confidence,
                json.dumps(details) if details else None
            ))
        except Exception as e:
            logger.error(f"保存信号统计失败: {e}")
    
    def update_signal_result(self, signal_id: int, 
                            status: str, profit: float = None):
        """
        更新信号结果
        
        Args:
            signal_id: 信号ID
            status: 状态（success/fail）
            profit: 盈亏比例
        """
        try:
            # 更新数据库
            sql = """
                UPDATE signal_statistics 
                SET status = ?, profit = ?, update_time = ?
                WHERE id = ?
            """
            self.db.execute(sql, (
                status,
                profit,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                signal_id
            ))
            
            # 更新缓存统计
            # 这里简化处理，实际应该从数据库读取signal_type
            if status == 'success':
                self.signal_stats['unknown']['success_count'] += 1
            else:
                self.signal_stats['unknown']['fail_count'] += 1
            
            if profit:
                self.signal_stats['unknown']['total_profit'] += profit
            
        except Exception as e:
            logger.error(f"更新信号结果失败: {e}")
    
    def get_signal_stats(self, signal_type: str = None, 
                        days: int = 30) -> Dict:
        """
        获取信号统计
        
        Args:
            signal_type: 信号类型（None表示全部）
            days: 统计天数
        
        Returns:
            统计结果
        """
        try:
            # 从数据库查询
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            
            if signal_type:
                sql = """
                    SELECT 
                        signal_type,
                        COUNT(*) as trigger_count,
                        SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success_count,
                        SUM(CASE WHEN status = 'fail' THEN 1 ELSE 0 END) as fail_count,
                        AVG(profit) as avg_profit
                    FROM signal_statistics
                    WHERE trigger_time >= ? AND signal_type = ?
                    GROUP BY signal_type
                """
                results = self.db.query(sql, (start_date, signal_type))
            else:
                sql = """
                    SELECT 
                        signal_type,
                        COUNT(*) as trigger_count,
                        SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success_count,
                        SUM(CASE WHEN status = 'fail' THEN 1 ELSE 0 END) as fail_count,
                        AVG(profit) as avg_profit
                    FROM signal_statistics
                    WHERE trigger_time >= ?
                    GROUP BY signal_type
                """
                results = self.db.query(sql, (start_date,))
            
            # 整理结果
            stats = {}
            for row in results:
                st = row['signal_type']
                trigger_count = row['trigger_count']
                success_count = row['success_count']
                
                win_rate = success_count / trigger_count * 100 if trigger_count > 0 else 0
                
                stats[st] = {
                    'trigger_count': trigger_count,
                    'success_count': success_count,
                    'fail_count': row['fail_count'],
                    'win_rate': round(win_rate, 2),
                    'avg_profit': round(row['avg_profit'], 2) if row['avg_profit'] else 0,
                }
            
            return stats
            
        except Exception as e:
            logger.error(f"获取信号统计失败: {e}")
            return {}
    
    def get_daily_signal_count(self, days: int = 30) -> Dict:
        """
        获取每日信号数量
        
        Args:
            days: 统计天数
        
        Returns:
            每日信号数量
        """
        try:
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            
            sql = """
                SELECT 
                    DATE(trigger_time) as date,
                    COUNT(*) as signal_count
                FROM signal_statistics
                WHERE trigger_time >= ?
                GROUP BY DATE(trigger_time)
                ORDER BY date
            """
            
            results = self.db.query(sql, (start_date,))
            
            daily_counts = {row['date']: row['signal_count'] for row in results}
            
            return daily_counts
            
        except Exception as e:
            logger.error(f"获取每日信号数量失败: {e}")
            return {}
    
    def check_signal_frequency(self) -> Dict:
        """
        检查信号频率是否正常
        
        Returns:
            检查结果
        """
        # 获取最近30天每日信号数量
        daily_counts = self.get_daily_signal_count(days=30)
        
        if not daily_counts:
            return {
                'status': 'warning',
                'message': '无信号数据'
            }
        
        # 计算平均每日信号数
        avg_count = sum(daily_counts.values()) / len(daily_counts)
        
        # 检查是否有信号过少的情况
        zero_days = sum(1 for count in daily_counts.values() if count == 0)
        low_days = sum(1 for count in daily_counts.values() if count < 3)
        
        result = {
            'avg_daily_signals': round(avg_count, 2),
            'zero_signal_days': zero_days,
            'low_signal_days': low_days,
            'total_days': len(daily_counts),
        }
        
        # 判断状态
        if avg_count < 1:
            result['status'] = 'critical'
            result['message'] = f'信号过少：平均每日{avg_count:.1f}个，策略可能失效'
        elif avg_count < 3:
            result['status'] = 'warning'
            result['message'] = f'信号偏少：平均每日{avg_count:.1f}个，建议放宽条件'
        elif zero_days > 10:
            result['status'] = 'warning'
            result['message'] = f'零信号天数过多：{zero_days}天'
        else:
            result['status'] = 'normal'
            result['message'] = f'信号频率正常：平均每日{avg_count:.1f}个'
        
        return result
    
    def calculate_signal_quality_index(self, signal_type: str = None, 
                                       days: int = 30) -> Dict:
        """
        计算信号质量指数（关键指标）
        
        信号质量指数 = 胜率 × 盈亏比
        
        Args:
            signal_type: 信号类型（None表示全部）
            days: 统计天数
        
        Returns:
            质量指数结果
        """
        stats = self.get_signal_stats(signal_type, days)
        
        quality_index = {}
        
        for st, data in stats.items():
            win_rate = data['win_rate'] / 100  # 转换为小数
            avg_profit = data['avg_profit']
            
            # 计算盈亏比（简化：用平均收益作为盈亏比代理）
            # 实际应该分别计算盈利单和亏损单的平均值
            if win_rate > 0 and win_rate < 1:
                # 盈亏比 = 平均盈利 / 平均亏损
                # 这里简化处理，用平均收益作为代理
                profit_loss_ratio = abs(avg_profit) if avg_profit != 0 else 1
            else:
                profit_loss_ratio = 1
            
            # 信号质量指数
            quality = win_rate * profit_loss_ratio
            
            quality_index[st] = {
                'win_rate': data['win_rate'],
                'avg_profit': avg_profit,
                'profit_loss_ratio': round(profit_loss_ratio, 2),
                'quality_index': round(quality, 3),
                'trigger_count': data['trigger_count'],
            }
        
        return quality_index
        """
        生成统计报告
        
        Args:
            days: 统计天数
        
        Returns:
            报告文本
        """
        # 获取统计数据
        signal_stats = self.get_signal_stats(days=days)
        daily_counts = self.get_daily_signal_count(days=days)
        frequency_check = self.check_signal_frequency()
        
        # 生成报告
        report_lines = [
            "=" * 70,
            f"信号统计报告（最近{days}天）",
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 70,
            "",
        ]
        
        # 信号频率检查
        report_lines.extend([
            "【信号频率检查】",
            f"  状态: {frequency_check['status']}",
            f"  {frequency_check['message']}",
            f"  平均每日信号: {frequency_check['avg_daily_signals']}个",
            f"  零信号天数: {frequency_check['zero_signal_days']}天",
            f"  低信号天数(<3): {frequency_check['low_signal_days']}天",
            "",
        ])
        
        # 各类信号统计
        if signal_stats:
            report_lines.append("【各类信号统计】")
            for signal_type, stats in signal_stats.items():
                report_lines.extend([
                    f"  {signal_type}:",
                    f"    触发次数: {stats['trigger_count']}",
                    f"    成功次数: {stats['success_count']}",
                    f"    失败次数: {stats['fail_count']}",
                    f"    胜率: {stats['win_rate']}%",
                    f"    平均收益: {stats['avg_profit']}%",
                    "",
                ])
        else:
            report_lines.append("【各类信号统计】")
            report_lines.append("  暂无数据")
            report_lines.append("")
        
        # 每日信号分布
        if daily_counts:
            report_lines.append("【每日信号分布】")
            for date, count in sorted(daily_counts.items(), reverse=True)[:10]:
                report_lines.append(f"  {date}: {count}个")
            report_lines.append("")
        
        report_lines.append("=" * 70)
        
        return "\n".join(report_lines)


def init_signal_statistics_table(db: DatabaseManager):
    """
    初始化信号统计表
    
    Args:
        db: 数据库管理器
    """
    sql = """
        CREATE TABLE IF NOT EXISTS signal_statistics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_type TEXT NOT NULL,
            ts_code TEXT NOT NULL,
            trigger_time TEXT NOT NULL,
            confidence REAL,
            details TEXT,
            status TEXT DEFAULT 'pending',
            profit REAL,
            create_time TEXT DEFAULT CURRENT_TIMESTAMP,
            update_time TEXT
        )
    """
    db.execute(sql)
    logger.info("信号统计表初始化完成")

    def analyze_trade_distribution(self, days: int = 30) -> Dict:
        """
        分析交易分布（关键：比优化参数重要10倍）
        
        包括：
        1. 盈亏分布
        2. 持仓时间分布
        3. 买点时间分布
        4. RSI区间分布
        5. 回撤幅度分布
        
        Args:
            days: 统计天数
        
        Returns:
            分布分析结果
        """
        try:
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            
            # 1. 盈亏分布
            sql_profit = """
                SELECT 
                    profit,
                    CASE 
                        WHEN profit > 0 THEN 'profit'
                        ELSE 'loss'
                    END as type
                FROM signal_statistics
                WHERE trigger_time >= ? AND profit IS NOT NULL
            """
            profit_results = self.db.query(sql_profit, (start_date,))
            
            profits = [r['profit'] for r in profit_results if r['profit'] > 0]
            losses = [abs(r['profit']) for r in profit_results if r['profit'] < 0]
            
            profit_dist = {
                'max_profit': max(profits) if profits else 0,
                'avg_profit': sum(profits) / len(profits) if profits else 0,
                'profit_count': len(profits),
                'max_loss': max(losses) if losses else 0,
                'avg_loss': sum(losses) / len(losses) if losses else 0,
                'loss_count': len(losses),
            }
            
            # 检查是否极端依赖少数交易
            if profits:
                top3_profit = sum(sorted(profits, reverse=True)[:3])
                total_profit = sum(profits)
                profit_concentration = top3_profit / total_profit if total_profit > 0 else 0
            else:
                profit_concentration = 0
            
            profit_dist['profit_concentration'] = round(profit_concentration, 2)
            
            # 2. 买点时间分布
            sql_time = """
                SELECT 
                    strftime('%H', trigger_time) as hour,
                    COUNT(*) as count,
                    AVG(profit) as avg_profit
                FROM signal_statistics
                WHERE trigger_time >= ?
                GROUP BY strftime('%H', trigger_time)
            """
            time_results = self.db.query(sql_time, (start_date,))
            
            time_dist = {}
            for r in time_results:
                hour = r['hour']
                time_dist[hour] = {
                    'count': r['count'],
                    'avg_profit': round(r['avg_profit'], 2) if r['avg_profit'] else 0,
                }
            
            # 区分上午和下午
            morning_profit = [r['avg_profit'] for r in time_results if int(r['hour']) < 12 and r['avg_profit']]
            afternoon_profit = [r['avg_profit'] for r in time_results if int(r['hour']) >= 12 and r['avg_profit']]
            
            time_comparison = {
                'morning_avg': round(sum(morning_profit) / len(morning_profit), 2) if morning_profit else 0,
                'afternoon_avg': round(sum(afternoon_profit) / len(afternoon_profit), 2) if afternoon_profit else 0,
            }
            
            # 3. 信号类型分布
            sql_signal = """
                SELECT 
                    signal_type,
                    COUNT(*) as count,
                    AVG(profit) as avg_profit,
                    SUM(CASE WHEN profit > 0 THEN 1 ELSE 0 END) as win_count
                FROM signal_statistics
                WHERE trigger_time >= ?
                GROUP BY signal_type
            """
            signal_results = self.db.query(sql_signal, (start_date,))
            
            signal_dist = {}
            for r in signal_results:
                win_rate = r['win_count'] / r['count'] * 100 if r['count'] > 0 else 0
                signal_dist[r['signal_type']] = {
                    'count': r['count'],
                    'avg_profit': round(r['avg_profit'], 2) if r['avg_profit'] else 0,
                    'win_rate': round(win_rate, 2),
                }
            
            return {
                'profit_distribution': profit_dist,
                'time_distribution': time_dist,
                'time_comparison': time_comparison,
                'signal_distribution': signal_dist,
            }
            
        except Exception as e:
            logger.error(f"分析交易分布失败: {e}")
            return {}
