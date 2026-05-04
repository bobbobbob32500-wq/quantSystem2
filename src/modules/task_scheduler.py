# -*- coding: utf-8 -*-
"""
定时任务调度模块
基于APScheduler实现任务调度管理
"""

from datetime import datetime
from typing import Callable, Dict, List, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

from src.core.logger import get_logger
from src.core.runtime_monitor import IncidentCategory
from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.core.exceptions import SchedulerException

logger = get_logger("scheduler")

_task_db = None

def _set_task_db(db):
    global _task_db
    _task_db = db


class TaskScheduler:
    """任务调度器"""
    
    def __init__(self, config: ConfigManager = None, runtime_monitor=None):
        """
        初始化任务调度器
        
        Args:
            config: 配置管理器
        """
        if config is None:
            config = ConfigManager()
        
        self.config = config
        self.runtime_monitor = runtime_monitor
        self.scheduler = BackgroundScheduler(
            job_defaults={
                "misfire_grace_time": 300,
                "coalesce": True,
                "max_instances": 1,
            }
        )
        self.jobs: Dict[str, Dict] = {}
        
        # 添加事件监听
        self.scheduler.add_listener(self._job_executed, EVENT_JOB_EXECUTED)
        self.scheduler.add_listener(self._job_error, EVENT_JOB_ERROR)
        
        logger.info("任务调度器初始化完成")
    
    def _job_executed(self, event):
        """任务执行成功回调"""
        job_id = event.job_id
        logger.info(f"任务执行成功: {job_id}")
        self._persist_job_result(job_id, "success")
    
    def _job_error(self, event):
        """任务执行失败回调"""
        job_id = event.job_id
        exception = event.exception
        logger.error(f"任务执行失败: {job_id}, 错误: {exception}")
        self._persist_job_result(job_id, "error", str(exception)[:500] if exception else "")
    
    def _persist_job_result(self, job_id: str, status: str, error_message: str = ""):
        """持久化任务执行结果到数据库"""
        if _task_db is None:
            return
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            _task_db.execute(
                "INSERT INTO task_execution_log (job_id, status, start_time, end_time, error_message) VALUES (?, ?, ?, ?, ?)",
                (job_id, status, now, now, error_message),
            )
        except Exception as e:
            logger.warning(f"持久化任务执行结果失败: {e}")
    
    def add_cron_job(self, job_id: str, func: Callable, 
                     cron_expr: str = None, 
                     hour: int = None, minute: int = None,
                     day_of_week: str = None,
                     **kwargs) -> bool:
        """
        添加Cron定时任务
        
        Args:
            job_id: 任务ID
            func: 任务函数
            cron_expr: Cron表达式
            hour: 小时
            minute: 分钟
            day_of_week: 星期几 (mon,tue,wed,thu,fri,sat,sun)
            **kwargs: 任务函数参数
        
        Returns:
            是否成功
        """
        try:
            if cron_expr:
                trigger = CronTrigger.from_crontab(cron_expr)
            else:
                trigger_args = {}
                if hour is not None:
                    trigger_args['hour'] = hour
                if minute is not None:
                    trigger_args['minute'] = minute
                if day_of_week:
                    trigger_args['day_of_week'] = day_of_week
                trigger = CronTrigger(**trigger_args)
            
            self.scheduler.add_job(
                func,
                trigger=trigger,
                id=job_id,
                kwargs=kwargs,
                replace_existing=True
            )
            
            self.jobs[job_id] = {
                "type": "cron",
                "func": func.__name__,
                "trigger": str(trigger),
                "status": "added"
            }
            
            logger.info(f"添加Cron任务成功: {job_id}, 触发器: {trigger}")
            return True
        
        except Exception as e:
            logger.error(f"添加Cron任务失败: {job_id}, 错误: {e}")
            return False
    
    def add_interval_job(self, job_id: str, func: Callable,
                         minutes: int = None, seconds: int = None,
                         hours: int = None,
                         start_date: datetime = None,
                         end_date: datetime = None,
                         **kwargs) -> bool:
        """
        添加间隔任务
        
        Args:
            job_id: 任务ID
            func: 任务函数
            minutes: 间隔分钟
            seconds: 间隔秒
            hours: 间隔小时
            start_date: 开始时间
            end_date: 结束时间
            **kwargs: 任务函数参数
        
        Returns:
            是否成功
        """
        try:
            trigger_args = {}
            if minutes:
                trigger_args['minutes'] = minutes
            if seconds:
                trigger_args['seconds'] = seconds
            if hours:
                trigger_args['hours'] = hours
            if start_date:
                trigger_args['start_date'] = start_date
            if end_date:
                trigger_args['end_date'] = end_date
            
            trigger = IntervalTrigger(**trigger_args)
            
            self.scheduler.add_job(
                func,
                trigger=trigger,
                id=job_id,
                kwargs=kwargs,
                replace_existing=True
            )
            
            self.jobs[job_id] = {
                "type": "interval",
                "func": func.__name__,
                "trigger": str(trigger),
                "status": "added"
            }
            
            logger.info(f"添加间隔任务成功: {job_id}, 触发器: {trigger}")
            return True
        
        except Exception as e:
            logger.error(f"添加间隔任务失败: {job_id}, 错误: {e}")
            return False
    
    def remove_job(self, job_id: str) -> bool:
        """
        移除任务
        
        Args:
            job_id: 任务ID
        
        Returns:
            是否成功
        """
        try:
            self.scheduler.remove_job(job_id)
            if job_id in self.jobs:
                self.jobs[job_id]["status"] = "removed"
            logger.info(f"移除任务成功: {job_id}")
            return True
        except Exception as e:
            logger.error(f"移除任务失败: {job_id}, 错误: {e}")
            return False
    
    def pause_job(self, job_id: str) -> bool:
        """
        暂停任务
        
        Args:
            job_id: 任务ID
        
        Returns:
            是否成功
        """
        try:
            self.scheduler.pause_job(job_id)
            if job_id in self.jobs:
                self.jobs[job_id]["status"] = "paused"
            logger.info(f"暂停任务成功: {job_id}")
            return True
        except Exception as e:
            logger.error(f"暂停任务失败: {job_id}, 错误: {e}")
            return False
    
    def resume_job(self, job_id: str) -> bool:
        """
        恢复任务
        
        Args:
            job_id: 任务ID
        
        Returns:
            是否成功
        """
        try:
            self.scheduler.resume_job(job_id)
            if job_id in self.jobs:
                self.jobs[job_id]["status"] = "running"
            logger.info(f"恢复任务成功: {job_id}")
            return True
        except Exception as e:
            logger.error(f"恢复任务失败: {job_id}, 错误: {e}")
            return False
    
    def run_job_now(self, job_id: str) -> bool:
        """
        立即执行任务
        
        Args:
            job_id: 任务ID
        
        Returns:
            是否成功
        """
        try:
            job = self.scheduler.get_job(job_id)
            if job:
                job.func(*job.args, **job.kwargs)
                logger.info(f"立即执行任务成功: {job_id}")
                return True
            else:
                logger.warning(f"任务不存在: {job_id}")
                return False
        except Exception as e:
            logger.error(f"立即执行任务失败: {job_id}, 错误: {e}")
            return False
    
    def get_jobs(self) -> List[Dict]:
        """
        获取所有任务列表
        
        Returns:
            任务列表
        """
        jobs = []
        for job in self.scheduler.get_jobs():
            job_info = {
                "id": job.id,
                "name": job.name,
                "trigger": str(job.trigger)
            }
            # APScheduler 3.11+ 使用不同的属性访问方式
            try:
                next_run = job.next_run_time
                job_info["next_run_time"] = str(next_run) if next_run else None
            except AttributeError:
                job_info["next_run_time"] = None
            
            if job.id in self.jobs:
                job_info.update(self.jobs[job.id])
            jobs.append(job_info)
        return jobs
    
    def get_job_status(self, job_id: str) -> Optional[str]:
        """
        获取任务状态
        
        Args:
            job_id: 任务ID
        
        Returns:
            任务状态
        """
        if job_id in self.jobs:
            return self.jobs[job_id].get("status")
        return None
    
    def start(self):
        """启动调度器"""
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("任务调度器已启动")
    
    def shutdown(self, wait: bool = True):
        """
        关闭调度器
        
        Args:
            wait: 是否等待任务完成
        """
        if self.scheduler.running:
            self.scheduler.shutdown(wait=wait)
            logger.info("任务调度器已关闭")
    
    def is_running(self) -> bool:
        """调度器是否运行中"""
        return self.scheduler.running


class QuantTaskManager:
    """量化系统任务管理器"""
    
    def __init__(self, config: ConfigManager = None, db: DatabaseManager = None, runtime_monitor=None):
        """
        初始化任务管理器
        
        Args:
            config: 配置管理器
            db: 数据库管理器
        """
        if config is None:
            config = ConfigManager()
        if db is None:
            from src.core.database import DatabaseManager
            db = DatabaseManager(config)
        
        self.config = config
        self.db = db
        self.runtime_monitor = runtime_monitor
        self.scheduler = TaskScheduler(config, runtime_monitor=runtime_monitor)
        
        # 加载任务配置
        self.daily_report_time = config.get("scheduler.daily_report_time", "08:30")
        self.trade_plan_time = config.get("scheduler.trade_plan_time", "14:50")
        self.data_update_time = config.get("scheduler.data_update_time", "17:30")
        self.post_market_time = config.get("scheduler.post_market_time", "18:00")
        self.feedback_digest_time = config.get("scheduler.feedback_digest_time", "18:10")
        
        # 自动推送管理器
        self.auto_push = None
        
        logger.info("量化任务管理器初始化完成")
    
    def setup_auto_push_tasks(self):
        """
        设置自动推送任务
        包括：市场分析、风控检测、日报、交易计划、盘后作业
        """
        from src.modules.auto_push_manager import AutoPushManager
        
        self.auto_push = AutoPushManager(self.config, self.db)
        
        # 解析时间配置
        daily_hour, daily_minute = map(int, self.daily_report_time.split(":"))
        plan_hour, plan_minute = map(int, self.trade_plan_time.split(":"))
        post_hour, post_minute = map(int, self.post_market_time.split(":"))
        feedback_hour, feedback_minute = map(int, self.feedback_digest_time.split(":"))
        
        # 1. 市场分析推送 - 盘前8:30
        self.scheduler.add_cron_job(
            "push_market_analysis_morning",
            self.auto_push.push_market_analysis,
            hour=daily_hour,
            minute=daily_minute,
            day_of_week="mon-fri"
        )
        
        # 2. 市场分析推送 - 盘中每30分钟
        self.scheduler.add_cron_job(
            "push_market_analysis_1030",
            self.auto_push.push_market_analysis,
            hour=10, minute=30, day_of_week="mon-fri"
        )
        self.scheduler.add_cron_job(
            "push_market_analysis_1100",
            self.auto_push.push_market_analysis,
            hour=11, minute=0, day_of_week="mon-fri"
        )
        self.scheduler.add_cron_job(
            "push_market_analysis_1330",
            self.auto_push.push_market_analysis,
            hour=13, minute=30, day_of_week="mon-fri"
        )
        self.scheduler.add_cron_job(
            "push_market_analysis_1400",
            self.auto_push.push_market_analysis,
            hour=14, minute=0, day_of_week="mon-fri"
        )
        self.scheduler.add_cron_job(
            "push_market_analysis_1430",
            self.auto_push.push_market_analysis,
            hour=14, minute=30, day_of_week="mon-fri"
        )
        
        # 3. 风控检测推送 - 盘中每5分钟
        self.scheduler.add_cron_job(
            "push_risk_0935",
            self.auto_push.push_risk_signals,
            hour=9, minute=35, day_of_week="mon-fri"
        )
        self.scheduler.add_cron_job(
            "push_risk_1000",
            self.auto_push.push_risk_signals,
            hour=10, minute=0, day_of_week="mon-fri"
        )
        self.scheduler.add_cron_job(
            "push_risk_1030",
            self.auto_push.push_risk_signals,
            hour=10, minute=30, day_of_week="mon-fri"
        )
        self.scheduler.add_cron_job(
            "push_risk_1100",
            self.auto_push.push_risk_signals,
            hour=11, minute=0, day_of_week="mon-fri"
        )
        self.scheduler.add_cron_job(
            "push_risk_1330",
            self.auto_push.push_risk_signals,
            hour=13, minute=30, day_of_week="mon-fri"
        )
        self.scheduler.add_cron_job(
            "push_risk_1400",
            self.auto_push.push_risk_signals,
            hour=14, minute=0, day_of_week="mon-fri"
        )
        self.scheduler.add_cron_job(
            "push_risk_1430",
            self.auto_push.push_risk_signals,
            hour=14, minute=30, day_of_week="mon-fri"
        )
        self.scheduler.add_cron_job(
            "push_risk_1450",
            self.auto_push.push_risk_signals,
            hour=14, minute=50, day_of_week="mon-fri"
        )

        # 3.1 持仓事件失败重试队列（交易时段每5分钟）
        self.scheduler.add_cron_job(
            "retry_position_events",
            self.auto_push.retry_position_events,
            hour="9-15",
            minute="*/5",
            day_of_week="mon-fri"
        )

        # 3.2 通用推送 outbox 重试（交易时段每2分钟）
        self.scheduler.add_cron_job(
            "retry_push_outbox",
            self.auto_push.retry_push_outbox,
            hour="9-15",
            minute="*/2",
            day_of_week="mon-fri"
        )
        
        # 4. 盘前选股计划推送（兼容旧任务名push_daily_report）- 盘前
        self.scheduler.add_cron_job(
            "push_daily_report",
            self.auto_push.push_daily_report,
            hour=daily_hour,
            minute=daily_minute,
            day_of_week="mon-fri"
        )
        
        # 5. 交易计划推送 - 尾盘14:50
        self.scheduler.add_cron_job(
            "push_trade_plan",
            self.auto_push.push_trade_plan,
            hour=plan_hour,
            minute=plan_minute,
            day_of_week="mon-fri"
        )
        
        # 6. 盘后作业推送 - 收盘后17:30
        update_hour, update_minute = map(int, self.data_update_time.split(":"))
        self.scheduler.add_cron_job(
            "push_post_market",
            self.auto_push.push_post_market_summary,
            hour=update_hour,
            minute=update_minute,
            day_of_week="mon-fri"
        )

        # 7. 盘后闭环反馈摘要推送（独立模板）
        self.scheduler.add_cron_job(
            "push_feedback_digest",
            self.auto_push.push_signal_feedback_digest,
            hour=feedback_hour,
            minute=feedback_minute,
            day_of_week="mon-fri"
        )
        
        logger.info("自动推送任务设置完成")
    
    def setup_default_tasks(self, 
                           daily_report_func: Callable = None,
                           trade_plan_func: Callable = None,
                           data_update_func: Callable = None,
                           post_market_func: Callable = None,
                           monitor_func: Callable = None):
        """
        设置默认任务
        
        Args:
            daily_report_func: 日报任务函数
            trade_plan_func: 交易计划任务函数
            data_update_func: 数据更新任务函数
            post_market_func: 盘后作业任务函数
            monitor_func: 监控任务函数
        """
        # 解析时间配置
        daily_hour, daily_minute = map(int, self.daily_report_time.split(":"))
        plan_hour, plan_minute = map(int, self.trade_plan_time.split(":"))
        update_hour, update_minute = map(int, self.data_update_time.split(":"))
        post_hour, post_minute = map(int, self.post_market_time.split(":"))
        
        # 添加日报任务 (工作日 08:30)
        if daily_report_func:
            self.scheduler.add_cron_job(
                "daily_report",
                daily_report_func,
                hour=daily_hour,
                minute=daily_minute,
                day_of_week="mon-fri"
            )
        
        # 添加交易计划任务 (工作日 14:50)
        if trade_plan_func:
            self.scheduler.add_cron_job(
                "trade_plan",
                trade_plan_func,
                hour=plan_hour,
                minute=plan_minute,
                day_of_week="mon-fri"
            )
        
        # 添加数据更新任务 (工作日 17:30)
        if data_update_func:
            self.scheduler.add_cron_job(
                "data_update",
                data_update_func,
                hour=update_hour,
                minute=update_minute,
                day_of_week="mon-fri"
            )
        
        # 添加盘后作业任务 (工作日 18:00)
        if post_market_func:
            self.scheduler.add_cron_job(
                "post_market",
                post_market_func,
                hour=post_hour,
                minute=post_minute,
                day_of_week="mon-fri"
            )
        
        # 添加监控任务 (交易时段每5分钟，非交易日自动跳过)
        if monitor_func:
            def _monitor_with_trade_day_check(**kwargs):
                from datetime import date as _date
                today_str = _date.today().strftime("%Y%m%d")
                try:
                    if _task_db is not None:
                        row = _task_db.query_one(
                            "SELECT 1 FROM stock_daily WHERE trade_date = ? LIMIT 1",
                            (today_str,)
                        )
                        if not row:
                            return
                except Exception:
                    pass
                monitor_func(**kwargs)

            self.scheduler.add_interval_job(
                "realtime_monitor",
                _monitor_with_trade_day_check,
                minutes=5
            )
        
        logger.info("默认任务设置完成")
    
    def start(self):
        """启动任务管理器"""
        self.scheduler.start()
        logger.info("量化任务管理器已启动")
    
    def stop(self):
        """停止任务管理器"""
        self.scheduler.shutdown()
        logger.info("量化任务管理器已停止")
    
    def get_task_list(self) -> List[Dict]:
        """获取任务列表"""
        return self.scheduler.get_jobs()
