# -*- coding: utf-8 -*-
"""
盘后作业模块
执行盘后数据复盘、日志归档、数据库备份等任务
"""

import os
import shutil
from datetime import datetime, timedelta
from typing import Dict, List

from src.core.logger import get_logger
from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.position_controller import PositionController
from src.modules.hold_analyzer import HoldAnalyzer

logger = get_logger("post_market")


class PostMarketWorker:
    """盘后作业执行器"""
    
    def __init__(self, config: ConfigManager = None, db: DatabaseManager = None):
        """
        初始化盘后作业执行器
        
        Args:
            config: 配置管理器
            db: 数据库管理器
        """
        if config is None:
            config = ConfigManager()
        if db is None:
            db = DatabaseManager(config)
        
        self.config = config
        self.db = db
        
        # 初始化模块
        self.position_controller = PositionController(config, db)
        self.hold_analyzer = HoldAnalyzer(config, db)
        
        logger.info("盘后作业执行器初始化完成")
    
    def generate_daily_summary(self) -> Dict:
        """
        生成每日复盘报告
        
        Returns:
            复盘报告
        """
        logger.info("生成每日复盘报告...")
        
        today = datetime.now().strftime("%Y-%m-%d")
        
        result = {
            "date": today,
            "market": None,
            "hold": None,
            "signals": None,
            "trades": None
        }
        
        try:
            # 市场复盘
            market_result = self.position_controller.analyze_market()
            result["market"] = {
                "score": market_result['total_score'],
                "status": "强势" if market_result['total_score'] >= 60 else "弱势",
                "suggestion": market_result['suggestion']
            }
            
            # 持仓复盘
            hold_result = self.hold_analyzer.run_analysis(market_result['total_score'])
            result["hold"] = {
                "count": hold_result['hold_count'],
                "total_profit": hold_result['total_profit'],
                "summary": hold_result['summary']
            }
            
            # 信号统计
            sql = """
                SELECT signal_type, COUNT(*) as count
                FROM signal_history
                WHERE date(signal_time) = ?
                GROUP BY signal_type
            """
            signals = self.db.query(sql, (today,))
            result["signals"] = signals
            
            # 交易统计
            sql = """
                SELECT COUNT(*) as count, 
                       SUM(CASE WHEN profit > 0 THEN 1 ELSE 0 END) as win_count,
                       SUM(profit) as total_profit
                FROM trade_log
                WHERE date(trade_time) = ?
            """
            trades = self.db.query_one(sql, (today,))
            result["trades"] = trades
            
            logger.info("每日复盘报告生成完成")
            
        except Exception as e:
            logger.error(f"生成复盘报告失败: {e}")
        
        return result
    
    def archive_logs(self, days: int = 7) -> Dict:
        """
        归档日志文件
        
        Args:
            days: 保留最近几天的日志
        
        Returns:
            归档结果
        """
        logger.info("开始归档日志文件...")
        
        result = {
            "archived_files": 0,
            "deleted_files": 0,
            "status": "success"
        }
        
        try:
            log_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "logs"
            )
            
            if not os.path.exists(log_dir):
                logger.warning("日志目录不存在")
                return result
            
            # 创建归档目录
            archive_dir = os.path.join(log_dir, "archive")
            os.makedirs(archive_dir, exist_ok=True)
            
            # 归档旧日志
            today = datetime.now()
            cutoff_date = today - timedelta(days=days)
            
            for filename in os.listdir(log_dir):
                if filename.endswith(".log") and not filename.startswith("quant_system"):
                    continue
                
                if filename.startswith("quant_system_"):
                    # 解析日期
                    try:
                        date_str = filename.replace("quant_system_", "").replace(".log", "")
                        file_date = datetime.strptime(date_str, "%Y%m%d")
                        
                        if file_date < cutoff_date:
                            # 移动到归档目录
                            src = os.path.join(log_dir, filename)
                            dst = os.path.join(archive_dir, filename)
                            shutil.move(src, dst)
                            result["archived_files"] += 1
                    except:
                        pass
            
            # 删除过旧的归档文件（超过30天）
            archive_cutoff = today - timedelta(days=30)
            
            for filename in os.listdir(archive_dir):
                if filename.endswith(".log"):
                    try:
                        date_str = filename.replace("quant_system_", "").replace(".log", "")
                        file_date = datetime.strptime(date_str, "%Y%m%d")
                        
                        if file_date < archive_cutoff:
                            os.remove(os.path.join(archive_dir, filename))
                            result["deleted_files"] += 1
                    except:
                        pass
            
            logger.info(f"日志归档完成，归档{result['archived_files']}个，删除{result['deleted_files']}个")
            
        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)
            logger.error(f"日志归档失败: {e}")
        
        return result
    
    def backup_database(self) -> Dict:
        """
        备份数据库
        
        Returns:
            备份结果
        """
        logger.info("开始备份数据库...")
        
        result = {
            "backup_file": None,
            "status": "success"
        }
        
        try:
            backup_file = self.db.backup_database()
            result["backup_file"] = backup_file
            logger.info(f"数据库备份完成: {backup_file}")
            
        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)
            logger.error(f"数据库备份失败: {e}")
        
        return result
    
    def clean_old_data(self, days: int = 365) -> Dict:
        """
        清理过期数据
        
        Args:
            days: 保留天数
        
        Returns:
            清理结果
        """
        logger.info("开始清理过期数据...")
        
        result = {
            "cleaned_records": 0,
            "status": "success"
        }
        
        try:
            cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            
            # 清理系统日志
            sql = "DELETE FROM system_log WHERE date(log_time) < ?"
            count = self.db.execute(sql, (cutoff_date,))
            result["cleaned_records"] += count
            
            # 清理旧备份
            self.db.clean_old_backups(30)
            
            logger.info(f"数据清理完成，共清理{result['cleaned_records']}条记录")
            
        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)
            logger.error(f"数据清理失败: {e}")
        
        return result
    
    def run_all_tasks(self) -> Dict:
        """
        执行所有盘后任务
        
        Returns:
            执行结果
        """
        logger.info("=" * 60)
        logger.info("开始执行盘后作业...")
        logger.info("=" * 60)
        
        start_time = datetime.now()
        
        result = {
            "start_time": start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "summary": None,
            "archive": None,
            "backup": None,
            "clean": None,
            "status": "success"
        }
        
        try:
            # 1. 生成复盘报告
            logger.info("任务1: 生成复盘报告")
            result["summary"] = self.generate_daily_summary()
            
            # 2. 归档日志
            logger.info("任务2: 归档日志")
            result["archive"] = self.archive_logs()
            
            # 3. 备份数据库
            logger.info("任务3: 备份数据库")
            result["backup"] = self.backup_database()
            
            # 4. 清理过期数据
            logger.info("任务4: 清理过期数据")
            result["clean"] = self.clean_old_data()
            
            end_time = datetime.now()
            result["end_time"] = end_time.strftime("%Y-%m-%d %H:%M:%S")
            result["duration"] = str(end_time - start_time)
            
            logger.info("=" * 60)
            logger.info("盘后作业执行完成")
            logger.info(f"耗时: {result['duration']}")
            logger.info("=" * 60)
            
        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)
            logger.error(f"盘后作业执行失败: {e}")
        
        return result
    
    def format_report(self, result: Dict) -> str:
        """
        格式化盘后作业报告
        
        Args:
            result: 作业结果
        
        Returns:
            报告文本
        """
        lines = []
        
        lines.extend([
            "=" * 70,
            "                    盘后作业执行报告",
            "=" * 70,
            f"开始时间: {result['start_time']}",
            f"结束时间: {result.get('end_time', '-')}",
            f"执行耗时: {result.get('duration', '-')}",
            "",
            "-" * 70,
            "【复盘摘要】",
            ""
        ])
        
        if result.get("summary"):
            summary = result["summary"]
            
            if summary.get("market"):
                lines.extend([
                    f"  市场评分: {summary['market']['score']}分 ({summary['market']['status']})",
                    f"  操作建议: {summary['market']['suggestion']}",
                    ""
                ])
            
            if summary.get("hold"):
                lines.extend([
                    f"  持仓数量: {summary['hold']['count']}只",
                    f"  总盈亏: {summary['hold']['total_profit']}元",
                    ""
                ])
        
        lines.extend([
            "-" * 70,
            "【作业执行情况】",
            ""
        ])
        
        if result.get("archive"):
            archive = result["archive"]
            lines.append(f"  日志归档: 归档{archive.get('archived_files', 0)}个，删除{archive.get('deleted_files', 0)}个")
        
        if result.get("backup"):
            backup = result["backup"]
            lines.append(f"  数据库备份: {backup.get('backup_file', '失败')}")
        
        if result.get("clean"):
            clean = result["clean"]
            lines.append(f"  数据清理: 清理{clean.get('cleaned_records', 0)}条记录")
        
        lines.extend([
            "",
            "=" * 70
        ])
        
        return "\n".join(lines)
