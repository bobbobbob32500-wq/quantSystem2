# -*- coding: utf-8 -*-
"""
日志系统模块
提供统一的日志记录功能
"""

import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler


def setup_logger(name: str, log_level: str = "INFO") -> logging.Logger:
    """
    设置并返回日志记录器
    
    Args:
        name: 日志记录器名称
        log_level: 日志级别 (DEBUG/INFO/WARNING/ERROR/CRITICAL)
    
    Returns:
        logging.Logger: 配置好的日志记录器
    """
    # 创建日志记录器
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    
    # 避免重复添加handler
    if logger.handlers:
        return logger
    
    # 创建日志目录
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")
    os.makedirs(log_dir, exist_ok=True)
    
    # 日志文件路径
    log_file = os.path.join(log_dir, f"quant_system_{datetime.now().strftime('%Y%m%d')}.log")
    
    # 创建文件处理器 - 按大小轮转
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    
    # 创建控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # 创建格式化器
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # 添加处理器
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger


def get_logger(name: str) -> logging.Logger:
    """
    获取已配置的日志记录器
    
    Args:
        name: 日志记录器名称
    
    Returns:
        logging.Logger: 日志记录器
    """
    return logging.getLogger(name)
