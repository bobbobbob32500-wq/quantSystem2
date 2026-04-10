# -*- coding: utf-8 -*-
"""
历史推荐记录整理工具
从数据库中提取历史推荐记录，转换为回测所需格式
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime
import sqlite3
import json
import os
from src.core.logger import get_logger

logger = get_logger("history_records_organizer")


class HistoryRecordsOrganizer:
    """历史推荐记录整理工具"""
    
    def __init__(self, db_path: str = "data/quant_system.db"):
        """初始化"""
        self.db_path = db_path
        
        # 缓存目录
        self.cache_dir = 'data/history_records'
        os.makedirs(self.cache_dir, exist_ok=True)
    
    def extract_from_database(self, 
                             start_date: Optional[str] = None,
                             end_date: Optional[str] = None) -> List[Dict]:
        """
        从数据库提取历史推荐记录
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            历史推荐记录列表
        """
        logger.info("="*70)
        logger.info("从数据库提取历史推荐记录")
        logger.info("="*70)
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 查询买入信号
            sql = """
                SELECT 
                    signal_id,
                    ts_code,
                    name,
                    signal_type,
                    strategy_type,
                    trigger_time,
                    trigger_conditions,
                    reason,
                    suggested_price,
                    suggested_position,
                    priority_score,
                    status,
                    confirm_time
                FROM signals
                WHERE signal_type = 'buy'
                ORDER BY trigger_time DESC
            """
            
            cursor.execute(sql)
            rows = cursor.fetchall()
            
            columns = [description[0] for description in cursor.description]
            buy_signals = [dict(zip(columns, row)) for row in rows]
            
            logger.info(f"找到 {len(buy_signals)} 条买入信号")
            
            # 转换为观察池记录格式
            observation_records = self._convert_to_observation_records(buy_signals)
            
            conn.close()
            
            return observation_records
            
        except Exception as e:
            logger.error(f"提取历史记录失败: {e}")
            return []
    
    def _convert_to_observation_records(self, buy_signals: List[Dict]) -> List[Dict]:
        """
        转换为观察池记录格式
        
        Args:
            buy_signals: 买入信号列表
        
        Returns:
            观察池记录列表
        """
        observation_records = []
        
        for signal in buy_signals:
            try:
                # 解析触发时间
                trigger_time = signal.get('trigger_time')
                if trigger_time:
                    if isinstance(trigger_time, str):
                        trigger_time = datetime.fromisoformat(trigger_time)
                    selection_date = trigger_time.strftime('%Y-%m-%d')
                else:
                    continue
                
                # 解析股票代码
                ts_code = signal.get('ts_code', '')
                symbol = ts_code.split('.')[0] if '.' in ts_code else ts_code
                
                # 解析触发条件
                trigger_conditions = signal.get('trigger_conditions', '{}')
                if isinstance(trigger_conditions, str):
                    trigger_conditions = json.loads(trigger_conditions)
                
                # 构建观察池记录
                record = {
                    'symbol': symbol,
                    'name': signal.get('name', ''),
                    'selection_date': selection_date,
                    'selection_reason': signal.get('reason', ''),
                    'selection_score': signal.get('priority_score', 0),
                    'strategy_type': signal.get('strategy_type', ''),
                    
                    # 买入信息（如果有）
                    'buy_date': selection_date,  # 假设当天买入
                    'buy_price': signal.get('suggested_price', 0),
                    'buy_signal': signal.get('reason', ''),
                    
                    # 卖出信息（需要后续补充）
                    'sell_date': None,
                    'sell_price': None,
                    'sell_signal': None,
                    
                    # 收益信息（需要后续补充）
                    'profit_pct': None,
                    'hold_days': None,
                    
                    # 原始信号ID
                    'signal_id': signal.get('signal_id', ''),
                }
                
                observation_records.append(record)
                
            except Exception as e:
                logger.warning(f"转换记录失败: {e}")
                continue
        
        logger.info(f"转换完成: {len(observation_records)} 条观察池记录")
        
        return observation_records
    
    def supplement_sell_info(self, observation_records: List[Dict]) -> List[Dict]:
        """
        补充卖出信息
        
        Args:
            observation_records: 观察池记录列表
        
        Returns:
            补充后的观察池记录列表
        """
        logger.info("补充卖出信息...")
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            for record in observation_records:
                symbol = record['symbol']
                selection_date = record['selection_date']
                
                # 查询对应的卖出信号
                ts_code = f"{symbol}.SZ" if symbol.startswith('0') else f"{symbol}.SH"
                
                sql = """
                    SELECT 
                        trigger_time,
                        reason,
                        suggested_price,
                        current_profit
                    FROM signals
                    WHERE ts_code = ?
                      AND signal_type = 'sell'
                      AND trigger_time >= ?
                    ORDER BY trigger_time ASC
                    LIMIT 1
                """
                
                cursor.execute(sql, (ts_code, selection_date))
                row = cursor.fetchone()
                
                if row:
                    sell_time, sell_reason, sell_price, profit_pct = row
                    
                    if isinstance(sell_time, str):
                        sell_time = datetime.fromisoformat(sell_time)
                    
                    record['sell_date'] = sell_time.strftime('%Y-%m-%d')
                    record['sell_price'] = sell_price
                    record['sell_signal'] = sell_reason
                    record['profit_pct'] = profit_pct if profit_pct else 0
                    
                    # 计算持仓天数
                    buy_date = datetime.strptime(record['buy_date'], '%Y-%m-%d')
                    sell_date = datetime.strptime(record['sell_date'], '%Y-%m-%d')
                    record['hold_days'] = (sell_date - buy_date).days
            
            conn.close()
            
            # 统计补充情况
            completed_count = sum(1 for r in observation_records if r.get('sell_date'))
            logger.info(f"卖出信息补充完成: {completed_count}/{len(observation_records)}")
            
            return observation_records
            
        except Exception as e:
            logger.error(f"补充卖出信息失败: {e}")
            return observation_records
    
    def save_to_cache(self, 
                     observation_records: List[Dict],
                     filename: str = 'observation_records.json') -> str:
        """
        保存到缓存
        
        Args:
            observation_records: 观察池记录列表
            filename: 文件名
        
        Returns:
            文件路径
        """
        filepath = os.path.join(self.cache_dir, filename)
        
        # 添加元数据
        data = {
            'metadata': {
                'total_records': len(observation_records),
                'created_time': datetime.now().isoformat(),
                'source': 'database',
            },
            'records': observation_records,
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"历史记录已保存: {filepath}")
        
        return filepath
    
    def load_from_cache(self, filename: str = 'observation_records.json') -> List[Dict]:
        """
        从缓存加载
        
        Args:
            filename: 文件名
        
        Returns:
            观察池记录列表
        """
        filepath = os.path.join(self.cache_dir, filename)
        
        if not os.path.exists(filepath):
            logger.warning(f"缓存文件不存在: {filepath}")
            return []
        
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        records = data.get('records', [])
        metadata = data.get('metadata', {})
        
        logger.info(f"历史记录已加载: {len(records)}条")
        logger.info(f"创建时间: {metadata.get('created_time', 'unknown')}")
        
        return records
    
    def get_statistics(self, observation_records: List[Dict]) -> Dict:
        """
        获取统计信息
        
        Args:
            observation_records: 观察池记录列表
        
        Returns:
            统计信息
        """
        if not observation_records:
            return {}
        
        # 基础统计
        total = len(observation_records)
        completed = sum(1 for r in observation_records if r.get('sell_date'))
        pending = total - completed
        
        # 收益统计
        profits = [r.get('profit_pct', 0) for r in observation_records if r.get('profit_pct') is not None]
        
        if profits:
            avg_profit = np.mean(profits)
            max_profit = max(profits)
            min_profit = min(profits)
            win_rate = sum(1 for p in profits if p > 0) / len(profits)
        else:
            avg_profit = 0
            max_profit = 0
            min_profit = 0
            win_rate = 0
        
        # 持仓天数统计
        hold_days = [r.get('hold_days', 0) for r in observation_records if r.get('hold_days') is not None]
        avg_hold_days = np.mean(hold_days) if hold_days else 0
        
        # 策略统计
        strategy_count = {}
        for record in observation_records:
            strategy = record.get('strategy_type', 'unknown')
            strategy_count[strategy] = strategy_count.get(strategy, 0) + 1
        
        return {
            'total': total,
            'completed': completed,
            'pending': pending,
            'avg_profit': avg_profit,
            'max_profit': max_profit,
            'min_profit': min_profit,
            'win_rate': win_rate,
            'avg_hold_days': avg_hold_days,
            'strategy_count': strategy_count,
        }
    
    def print_statistics(self, observation_records: List[Dict]) -> None:
        """打印统计信息"""
        stats = self.get_statistics(observation_records)
        
        if not stats:
            print("无统计数据")
            return
        
        print("\n" + "="*70)
        print("历史推荐记录统计")
        print("="*70)
        
        print(f"\n【基础统计】")
        print(f"  总记录数: {stats['total']}")
        print(f"  已完成: {stats['completed']}")
        print(f"  待处理: {stats['pending']}")
        
        print(f"\n【收益统计】")
        print(f"  平均收益: {stats['avg_profit']:.2f}%")
        print(f"  最大收益: {stats['max_profit']:.2f}%")
        print(f"  最小收益: {stats['min_profit']:.2f}%")
        print(f"  胜率: {stats['win_rate']*100:.2f}%")
        
        print(f"\n【持仓统计】")
        print(f"  平均持仓天数: {stats['avg_hold_days']:.1f}天")
        
        print(f"\n【策略统计】")
        for strategy, count in stats['strategy_count'].items():
            print(f"  {strategy}: {count}次")
        
        print("="*70)
