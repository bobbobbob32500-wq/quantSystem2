# -*- coding: utf-8 -*-
"""
盘中监控模块接口
提供与主系统的集成接口
"""

import asyncio
from typing import List, Dict, Optional
from datetime import datetime
from src.core.logger import get_logger
from src.modules.intraday_monitor.monitor_engine import IntradayMonitorEngine

logger = get_logger("intraday_monitor")


class IntradayMonitor:
    """盘中监控模块"""
    
    def __init__(self):
        """初始化盘中监控模块"""
        self.engine: Optional[IntradayMonitorEngine] = None
        self.is_initialized = False
    
    def initialize(self, use_mock_data: bool = False):
        """
        初始化监控引擎
        
        Args:
            use_mock_data: 是否使用模拟数据
        """
        if self.is_initialized:
            return
        
        self.engine = IntradayMonitorEngine(use_mock_data=use_mock_data)
        self.is_initialized = True
        logger.info("盘中监控模块初始化完成")
    
    def set_monitor_pool(self, symbols: List[str]):
        """
        设置监控股票池
        
        Args:
            symbols: 股票代码列表
        """
        if not self.is_initialized:
            self.initialize()
        
        self.engine.set_monitor_pool(symbols)
        logger.info(f"设置监控股票池: {len(symbols)}只")
    
    def add_symbol(self, symbol: str):
        """添加监控股票"""
        if not self.is_initialized:
            self.initialize()
        
        self.engine.add_symbol(symbol)
    
    def remove_symbol(self, symbol: str):
        """移除监控股票"""
        if self.engine:
            self.engine.remove_symbol(symbol)
    
    def start_monitoring(self):
        """启动监控（同步接口）"""
        if not self.is_initialized:
            logger.error("监控引擎未初始化")
            return
        
        try:
            # 在新的事件循环中运行
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.engine.start())
        except KeyboardInterrupt:
            logger.info("用户中断监控")
            self.stop_monitoring()
        except Exception as e:
            logger.error(f"监控异常: {e}")
            self.stop_monitoring()
    
    def stop_monitoring(self):
        """停止监控"""
        if self.engine:
            self.engine.stop()
            logger.info("盘中监控已停止")
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        if self.engine:
            return self.engine.get_stats()
        return {}
    
    def get_recent_signals(self, minutes: int = 30) -> List[Dict]:
        """获取最近的信号"""
        if self.engine:
            signals = self.engine.get_recent_signals(minutes)
            return [s.to_dict() for s in signals]
        return []
    
    def get_recent_alerts(self, minutes: int = 60) -> List:
        """获取最近的提醒"""
        if self.engine:
            return self.engine.get_recent_alerts(minutes)
        return []
    
    def print_status(self):
        """打印状态"""
        stats = self.get_stats()
        
        print("\n" + "="*60)
        print("盘中监控状态")
        print("="*60)
        print(f"状态: {stats.get('state', '未初始化')}")
        print(f"监控股票数: {stats.get('monitoring_symbols', 0)}")
        print(f"运行时间: {stats.get('running_time', 'N/A')}")
        print(f"总检查次数: {stats.get('total_checks', 0)}")
        print(f"买入信号: {stats.get('buy_signals', 0)}")
        print(f"卖出信号: {stats.get('sell_signals', 0)}")
        print("="*60)


# ==============================================================================
# 命令行接口
# ==============================================================================

def intraday_monitor_menu():
    """盘中监控菜单"""
    monitor = IntradayMonitor()
    
    while True:
        print("\n" + "="*60)
        print("盘中实时监控系统")
        print("="*60)
        print("1. 设置监控股票池")
        print("2. 添加监控股票")
        print("3. 移除监控股票")
        print("4. 启动监控")
        print("5. 停止监控")
        print("6. 查看状态")
        print("7. 查看最近信号")
        print("8. 查看最近提醒")
        print("0. 返回主菜单")
        print("="*60)
        
        choice = input("请选择: ").strip()
        
        if choice == '1':
            # 设置监控股票池
            symbols_input = input("请输入股票代码（用逗号分隔）: ").strip()
            symbols = [s.strip() for s in symbols_input.split(',') if s.strip()]
            
            if symbols:
                monitor.set_monitor_pool(symbols)
                print(f"已设置监控股票池: {symbols}")
            else:
                print("输入无效")
        
        elif choice == '2':
            # 添加监控股票
            symbol = input("请输入股票代码: ").strip()
            if symbol:
                monitor.add_symbol(symbol)
                print(f"已添加监控股票: {symbol}")
        
        elif choice == '3':
            # 移除监控股票
            symbol = input("请输入股票代码: ").strip()
            if symbol:
                monitor.remove_symbol(symbol)
                print(f"已移除监控股票: {symbol}")
        
        elif choice == '4':
            # 启动监控
            print("\n启动盘中监控...")
            print("提示: 按 Ctrl+C 可停止监控")
            print("-"*60)
            
            use_mock = input("是否使用模拟数据？(y/n): ").strip().lower() == 'y'
            monitor.initialize(use_mock_data=use_mock)
            monitor.start_monitoring()
        
        elif choice == '5':
            # 停止监控
            monitor.stop_monitoring()
        
        elif choice == '6':
            # 查看状态
            monitor.print_status()
        
        elif choice == '7':
            # 查看最近信号
            minutes = int(input("查看最近多少分钟的信号？(默认30): ").strip() or "30")
            signals = monitor.get_recent_signals(minutes)
            
            print(f"\n最近{minutes}分钟的信号:")
            print("-"*60)
            
            if signals:
                for i, signal in enumerate(signals, 1):
                    print(f"{i}. {signal['symbol']} - {signal['action']}")
                    print(f"   类型: {signal['type']}")
                    print(f"   评分: {signal['score']:.1f}")
                    print(f"   价格: {signal['price']:.2f}")
                    print(f"   时间: {signal['timestamp']}")
                    print(f"   原因: {signal['reason']}")
                    print()
            else:
                print("暂无信号")
        
        elif choice == '8':
            # 查看最近提醒
            minutes = int(input("查看最近多少分钟的提醒？(默认60): ").strip() or "60")
            alerts = monitor.get_recent_alerts(minutes)
            
            print(f"\n最近{minutes}分钟的提醒:")
            print("-"*60)
            
            if alerts:
                for alert in alerts:
                    print(alert.to_text())
            else:
                print("暂无提醒")
        
        elif choice == '0':
            # 返回主菜单
            monitor.stop_monitoring()
            break
        
        else:
            print("无效选择，请重试")


if __name__ == "__main__":
    intraday_monitor_menu()
