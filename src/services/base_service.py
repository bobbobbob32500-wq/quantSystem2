# -*- coding: utf-8 -*-
"""
业务逻辑层基类
"""

from typing import Optional, Dict, Any, List
from abc import ABC

from src.core.logger import get_logger
from src.core.database import DatabaseManager
from src.core.config import ConfigManager

logger = get_logger("service_base")


class BaseService(ABC):
    """业务逻辑层基类"""
    
    def __init__(self, config: ConfigManager = None, db: DatabaseManager = None):
        if config is None:
            config = ConfigManager()
        if db is None:
            db = DatabaseManager(config)
        
        self.config = config
        self.db = db
    
    def get_config(self, key: str, default: Any = None) -> Any:
        """获取配置"""
        return self.config.get(key, default)
    
    def log_info(self, message: str):
        """记录信息日志"""
        logger.info(message)
    
    def log_warning(self, message: str):
        """记录警告日志"""
        logger.warning(message)
    
    def log_error(self, message: str):
        """记录错误日志"""
        logger.error(message)
    
    def log_debug(self, message: str):
        """记录调试日志"""
        logger.debug(message)
