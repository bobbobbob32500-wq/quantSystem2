# -*- coding: utf-8 -*-
"""
A股量化交易辅助系统 V1.0
主入口模块
"""

__version__ = "1.0.0"
__author__ = "QuantSystem"

from src.core.logger import setup_logger
from src.core.config import ConfigManager
from src.core.database import DatabaseManager

# 初始化日志
logger = setup_logger("quant_system")


def init_system():
    """初始化系统"""
    logger.info("正在初始化A股量化交易辅助系统...")
    
    # 加载配置
    config = ConfigManager()
    logger.info("配置加载完成")
    
    # 初始化数据库
    db = DatabaseManager(config)
    logger.info("数据库初始化完成")
    
    logger.info("系统初始化完成")
    return config, db


if __name__ == "__main__":
    config, db = init_system()
