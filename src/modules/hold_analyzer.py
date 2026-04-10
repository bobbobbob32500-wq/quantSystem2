# -*- coding: utf-8 -*-
"""
持仓分析模块
分析用户持仓股的实时盈亏、风险等级，给出持仓调整建议
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from src.core.logger import get_logger
from src.core.config import ConfigManager
from src.core.database import DatabaseManager

logger = get_logger("hold_analysis")


class HoldAnalyzer:
    """持仓分析器"""
    
    def __init__(self, config: ConfigManager = None, db: DatabaseManager = None):
        """
        初始化持仓分析器
        
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
        
        logger.info("持仓分析器初始化完成")
    
    def get_hold_list(self) -> List[Dict]:
        """
        获取持仓列表
        
        Returns:
            持仓列表
        """
        sql = """
            SELECT id, ts_code, name, hold_price, hold_num, target_profit, target_stop, hold_date, status
            FROM hold_stock
            WHERE status = 1
        """
        results = self.db.query(sql)
        return results if results else []
    
    def add_hold(self, ts_code: str, name: str, hold_price: float, hold_num: int,
                 target_profit: float = None, target_stop: float = None) -> bool:
        """
        添加持仓
        
        Args:
            ts_code: 股票代码
            name: 股票名称
            hold_price: 持仓成本
            hold_num: 持仓数量
            target_profit: 目标止盈价
            target_stop: 目标止损价
        
        Returns:
            是否成功
        """
        try:
            hold_date = datetime.now().strftime("%Y-%m-%d")
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            sql = """
                INSERT INTO hold_stock (ts_code, name, hold_price, hold_num, target_profit, target_stop, hold_date, status, create_time, update_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """
            
            self.db.execute(sql, (
                ts_code, name, hold_price, hold_num,
                target_profit, target_stop, hold_date,
                current_time, current_time
            ))
            
            logger.info(f"添加持仓成功: {ts_code} {name}")
            return True
        except Exception as e:
            logger.error(f"添加持仓失败: {e}")
            return False
    
    def update_hold(self, hold_id: int, **kwargs) -> bool:
        """
        更新持仓信息
        
        Args:
            hold_id: 持仓ID
            **kwargs: 要更新的字段
        
        Returns:
            是否成功
        """
        if not kwargs:
            return False
        
        try:
            update_fields = []
            params = []
            
            for key, value in kwargs.items():
                if key in ['hold_price', 'hold_num', 'target_profit', 'target_stop', 'status']:
                    update_fields.append(f"{key} = ?")
                    params.append(value)
            
            if not update_fields:
                return False
            
            update_fields.append("update_time = ?")
            params.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            params.append(hold_id)
            
            sql = f"UPDATE hold_stock SET {', '.join(update_fields)} WHERE id = ?"
            self.db.execute(sql, tuple(params))
            
            logger.info(f"更新持仓成功: ID={hold_id}")
            return True
        except Exception as e:
            logger.error(f"更新持仓失败: {e}")
            return False
    
    def delete_hold(self, hold_id: int) -> bool:
        """
        删除持仓（软删除）
        
        Args:
            hold_id: 持仓ID
        
        Returns:
            是否成功
        """
        return self.update_hold(hold_id, status=0)
    
    def get_latest_price(self, ts_code: str) -> Optional[float]:
        """
        获取股票最新价格（优先使用实时价格）
        
        Args:
            ts_code: 股票代码
        
        Returns:
            最新价格
        """
        # 优先尝试获取实时价格
        try:
            from src.modules.realtime_quote_fetcher import RealtimeQuoteFetcher
            
            # 去除交易所后缀
            code = ts_code.split('.')[0] if '.' in ts_code else ts_code
            
            fetcher = RealtimeQuoteFetcher()
            quote_data = fetcher.get_realtime_quote_single(code, src='sina')
            
            if quote_data and quote_data.get('price', 0) > 0:
                logger.debug(f"使用实时价格: {ts_code} = {quote_data['price']}")
                return quote_data['price']
                
        except Exception as e:
            logger.warning(f"获取实时价格失败 {ts_code}: {e}，使用数据库价格")
        
        # 回退到数据库价格
        sql = """
            SELECT close FROM stock_daily
            WHERE ts_code = ?
            ORDER BY trade_date DESC
            LIMIT 1
        """
        result = self.db.query_one(sql, (ts_code,))
        if result:
            logger.debug(f"使用数据库价格: {ts_code} = {result['close']}")
            return result['close']
        
        logger.warning(f"无法获取价格: {ts_code}")
        return None
    
    def get_stock_daily_data(self, ts_code: str, days: int = 60) -> pd.DataFrame:
        """
        获取个股日线数据
        
        Args:
            ts_code: 股票代码
            days: 获取天数
        
        Returns:
            日线数据DataFrame
        """
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
        
        sql = """
            SELECT trade_date, open, close, high, low, vol, amount, pct_chg
            FROM stock_daily
            WHERE ts_code = ? AND trade_date >= ? AND trade_date <= ?
            ORDER BY trade_date DESC
        """
        
        results = self.db.query(sql, (ts_code, start_date, end_date))
        
        if not results:
            return pd.DataFrame()
        
        df = pd.DataFrame(results)
        # 处理日期格式
        try:
            if len(str(df['trade_date'].iloc[0])) == 8:
                df['trade_date'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')
            else:
                df['trade_date'] = pd.to_datetime(df['trade_date'])
        except:
            df['trade_date'] = pd.to_datetime(df['trade_date'])
        df = df.sort_values('trade_date').reset_index(drop=True)
        
        if len(df) > days:
            df = df.tail(days)
        
        return df
    
    def calculate_profit(self, hold_price: float, current_price: float) -> float:
        """
        计算盈亏比例
        
        Args:
            hold_price: 持仓成本
            current_price: 当前价格
        
        Returns:
            盈亏比例(%)
        """
        if hold_price == 0:
            return 0.0
        return round((current_price - hold_price) / hold_price * 100, 2)
    
    def calculate_risk_level(self, profit: float, market_score: float = 50.0) -> str:
        """
        计算风险等级
        
        Args:
            profit: 盈亏比例
            market_score: 市场评分
        
        Returns:
            风险等级
        """
        # 综合考虑盈亏和市场环境
        risk_score = profit - (market_score - 50) * 0.5
        
        if risk_score < -10:
            return "高风险"
        elif risk_score < -5:
            return "中高风险"
        elif risk_score < 5:
            return "中风险"
        elif risk_score < 15:
            return "中低风险"
        else:
            return "低风险"
    
    def generate_suggestion(self, profit: float, market_score: float, 
                           target_profit: float = None, target_stop: float = None,
                           current_price: float = None) -> str:
        """
        生成持仓建议
        
        Args:
            profit: 盈亏比例
            market_score: 市场评分
            target_profit: 目标止盈价
            target_stop: 目标止损价
            current_price: 当前价格
        
        Returns:
            建议文本
        """
        suggestions = []
        
        # 基于市场环境的建议
        if market_score < 40:
            suggestions.append("市场环境极差，建议减仓或清仓")
        elif market_score < 60:
            suggestions.append("市场震荡，建议控制仓位")
        
        # 基于盈亏的建议
        if profit < -10:
            suggestions.append("亏损超过10%，建议止损")
        elif profit < -5:
            suggestions.append("亏损超过5%，注意风险控制")
        elif profit > 20:
            suggestions.append("盈利超过20%，可考虑分批止盈")
        elif profit > 10:
            suggestions.append("盈利良好，可继续持有")
        
        # 基于止盈止损的建议
        if target_profit and current_price and current_price >= target_profit:
            suggestions.append("已达到目标止盈价，建议止盈")
        
        if target_stop and current_price and current_price <= target_stop:
            suggestions.append("已触及止损价，建议止损")
        
        if not suggestions:
            suggestions.append("持仓正常，继续持有")
        
        return "；".join(suggestions)
    
    def analyze_single_hold(self, hold: Dict, market_score: float = 50.0) -> Dict:
        """
        分析单只持仓
        
        Args:
            hold: 持仓信息
            market_score: 市场评分
        
        Returns:
            分析结果
        """
        ts_code = hold['ts_code']
        name = hold['name']
        hold_price = hold['hold_price']
        hold_num = hold['hold_num']
        target_profit = hold.get('target_profit')
        target_stop = hold.get('target_stop')
        
        # 获取最新价格
        current_price = self.get_latest_price(ts_code)
        
        if current_price is None:
            return {
                "ts_code": ts_code,
                "name": name,
                "error": "无法获取最新价格"
            }
        
        # 计算盈亏
        profit = self.calculate_profit(hold_price, current_price)
        profit_amount = round((current_price - hold_price) * hold_num, 2)
        market_value = round(current_price * hold_num, 2)
        
        # 计算风险等级
        risk_level = self.calculate_risk_level(profit, market_score)
        
        # 生成建议
        suggestion = self.generate_suggestion(
            profit, market_score, target_profit, target_stop, current_price
        )
        
        return {
            "ts_code": ts_code,
            "name": name,
            "hold_price": hold_price,
            "hold_num": hold_num,
            "current_price": current_price,
            "profit": profit,
            "profit_amount": profit_amount,
            "market_value": market_value,
            "risk_level": risk_level,
            "suggestion": suggestion,
            "target_profit": target_profit,
            "target_stop": target_stop
        }
    
    def run_analysis(self, market_score: float = 50.0) -> Dict:
        """
        执行持仓分析
        
        Args:
            market_score: 市场评分
        
        Returns:
            分析结果
        """
        logger.info("=" * 50)
        logger.info("开始执行持仓分析...")
        logger.info("=" * 50)
        
        # 获取持仓列表
        hold_list = self.get_hold_list()
        
        if not hold_list:
            logger.info("当前无持仓")
            return {
                "hold_count": 0,
                "total_profit": 0,
                "total_market_value": 0,
                "holds": [],
                "summary": "当前无持仓"
            }
        
        # 分析各持仓
        results = []
        total_profit = 0
        total_market_value = 0
        
        for hold in hold_list:
            result = self.analyze_single_hold(hold, market_score)
            if "error" not in result:
                results.append(result)
                total_profit += result['profit_amount']
                total_market_value += result['market_value']
        
        # 按盈亏排序
        results.sort(key=lambda x: x['profit'], reverse=True)
        
        # 生成汇总
        profit_count = sum(1 for r in results if r['profit'] > 0)
        loss_count = sum(1 for r in results if r['profit'] < 0)
        
        summary = f"共{len(results)}只持仓，盈利{profit_count}只，亏损{loss_count}只，总盈亏{round(total_profit, 2)}元"
        
        logger.info("=" * 50)
        logger.info(f"持仓分析完成: {summary}")
        for r in results:
            logger.info(f"  {r['ts_code']} {r['name']}: {r['profit']}% ({r['risk_level']})")
        logger.info("=" * 50)
        
        return {
            "hold_count": len(results),
            "total_profit": round(total_profit, 2),
            "total_market_value": round(total_market_value, 2),
            "holds": results,
            "summary": summary,
            "analyze_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    
    def generate_report(self, result: Dict) -> str:
        """
        生成持仓分析报告
        
        Args:
            result: 分析结果
        
        Returns:
            报告文本
        """
        report_lines = [
            "=" * 60,
            "持仓分析报告",
            f"生成时间: {result.get('analyze_time', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}",
            "=" * 60,
            "",
            f"持仓数量: {result['hold_count']}只",
            f"总市值: {result['total_market_value']}元",
            f"总盈亏: {result['total_profit']}元",
            "",
            "-" * 60
        ]
        
        if not result['holds']:
            report_lines.append("无持仓记录")
            return "\n".join(report_lines)
        
        for hold in result['holds']:
            report_lines.extend([
                f"【{hold['ts_code']}】{hold['name']}",
                f"    持仓成本: {hold['hold_price']}元 × {hold['hold_num']}股",
                f"    当前价格: {hold['current_price']}元",
                f"    市值: {hold['market_value']}元",
                f"    盈亏: {hold['profit']}% ({hold['profit_amount']}元)",
                f"    风险等级: {hold['risk_level']}",
                f"    建议: {hold['suggestion']}",
                ""
            ])
        
        report_lines.extend([
            "-" * 60,
            f"汇总: {result['summary']}",
            "=" * 60
        ])
        
        return "\n".join(report_lines)
