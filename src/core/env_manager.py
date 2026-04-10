# -*- coding: utf-8 -*-
"""
环境变量管理模块
安全加载和管理敏感配置信息
"""

import os
from typing import Optional
from pathlib import Path

try:
    from dotenv import load_dotenv
    DOTENV_AVAILABLE = True
except ImportError:
    DOTENV_AVAILABLE = False


class EnvManager:
    """环境变量管理器"""
    
    _instance = None
    _loaded = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._loaded:
            self._load_env()
            self._loaded = True
    
    def _load_env(self):
        """加载环境变量文件"""
        env_path = self._find_env_file()
        
        if env_path and env_path.exists():
            if DOTENV_AVAILABLE:
                load_dotenv(env_path)
            else:
                self._manual_load(env_path)
    
    def _find_env_file(self) -> Optional[Path]:
        """查找.env文件"""
        current_path = Path(__file__).resolve()
        
        for parent in [current_path.parent] + list(current_path.parents):
            env_file = parent / '.env'
            if env_file.exists():
                return env_file
        
        return None
    
    def _manual_load(self, env_path: Path):
        """手动加载.env文件（当python-dotenv不可用时）"""
        try:
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        if value and not os.getenv(key):
                            os.environ[key] = value
        except Exception:
            pass
    
    @staticmethod
    def get(key: str, default: str = None) -> Optional[str]:
        """
        获取环境变量
        
        Args:
            key: 环境变量名
            default: 默认值
        
        Returns:
            环境变量值
        """
        EnvManager()
        return os.getenv(key, default)
    
    @staticmethod
    def get_required(key: str) -> str:
        """
        获取必需的环境变量
        
        Args:
            key: 环境变量名
        
        Returns:
            环境变量值
        
        Raises:
            ValueError: 环境变量未设置
        """
        value = EnvManager.get(key)
        if value is None or value == f'your_{key.lower()}_here':
            raise ValueError(f"必需的环境变量 {key} 未设置，请在 .env 文件中配置")
        return value
    
    @staticmethod
    def get_int(key: str, default: int = 0) -> int:
        """获取整数类型环境变量"""
        value = EnvManager.get(key)
        if value is None:
            return default
        try:
            return int(value)
        except ValueError:
            return default
    
    @staticmethod
    def get_bool(key: str, default: bool = False) -> bool:
        """获取布尔类型环境变量"""
        value = EnvManager.get(key)
        if value is None:
            return default
        return value.lower() in ('true', '1', 'yes', 'on')


env_manager = EnvManager()
