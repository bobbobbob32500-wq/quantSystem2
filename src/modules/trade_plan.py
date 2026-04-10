# -*- coding: utf-8 -*-
"""
14:50交易计划模块
收盘前10分钟生成尾盘操作计划
"""

from datetime import datetime
from typing import Dict, List, Optional

from src.core.logger import get_logger
from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.position_controller import PositionController
from src.modules.hold_analyzer import HoldAnalyzer
from src.modules.stock_selector import StockSelector
from src.modules.message_pusher import MessagePusher

logger = get_logger("trade_plan")


class TradePlanGenerator:
    """交易计划生成器"""
    
    def __init__(self, config: ConfigManager = None, db: DatabaseManager = None):
        """
        初始化交易计划生成器
        
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
        
        # 初始化各模块
        self.position_controller = PositionController(config, db)
        self.hold_analyzer = HoldAnalyzer(config, db)
        self.stock_selector = StockSelector(config, db)
        self.message_pusher = MessagePusher(config)
        
        logger.info("交易计划生成器初始化完成")
    
    def get_latest_price(self, ts_code: str) -> Optional[float]:
        """获取股票最新价格"""
        sql = """
            SELECT close FROM stock_daily
            WHERE ts_code = ?
            ORDER BY trade_date DESC
            LIMIT 1
        """
        result = self.db.query_one(sql, (ts_code,))
        return result['close'] if result else None
    
    def generate_hold_suggestion(self, hold: Dict, market_score: float) -> Dict:
        """
        生成单只持仓的尾盘建议
        
        Args:
            hold: 持仓信息
            market_score: 市场评分
        
        Returns:
            建议信息
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
                "suggestion": "无法获取价格",
                "action": "观望"
            }
        
        # 计算盈亏
        profit = round((current_price - hold_price) / hold_price * 100, 2) if hold_price > 0 else 0
        
        # 生成建议
        action = "持有"
        reason = ""
        
        # 基于市场环境
        if market_score < 40:
            if profit <= 5:
                action = "清仓"
                reason = "市场极差，低盈利持仓建议清仓"
            else:
                action = "减仓"
                reason = "市场极差，建议减仓锁定利润"
        elif market_score < 50:
            if profit < 0:
                action = "止损"
                reason = "市场转弱，亏损持仓建议止损"
            elif profit > 10:
                action = "减仓"
                reason = "市场震荡，高盈利建议减仓"
        
        # 基于止盈止损
        if target_profit and current_price >= target_profit:
            action = "止盈"
            reason = f"达到目标止盈价{target_profit}元"
        
        if target_stop and current_price <= target_stop:
            action = "止损"
            reason = f"触及止损价{target_stop}元"
        
        return {
            "ts_code": ts_code,
            "name": name,
            "current_price": current_price,
            "hold_price": hold_price,
            "profit": profit,
            "action": action,
            "reason": reason,
            "hold_num": hold_num,
            "market_value": round(current_price * hold_num, 2)
        }
    
    def generate_plan(self) -> Dict:
        """
        生成尾盘交易计划
        
        Returns:
            交易计划
        """
        logger.info("=" * 60)
        logger.info("开始生成14:50尾盘交易计划...")
        logger.info("=" * 60)
        
        generate_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        result = {
            "generate_time": generate_time,
            "market_score": 0,
            "market_status": "",
            "market_suggestion": "",
            "hold_suggestions": [],
            "stock_picks": [],
            "status": "success"
        }
        
        try:
            # 1. 获取最新市场评分
            logger.info("步骤1: 获取市场评分...")
            try:
                market_result = self.position_controller.analyze_market()
                # 使用target_position作为市场评分（0-100）
                market_score = market_result.get('target_position', 50) * 100
                market_weak = market_score < 45
                
                result["market_score"] = market_score
                result["market_weak"] = market_weak
                result["market_suggestion"] = market_result.get('strategy_suggestion', '')
                
                # 市场状态
                if market_score >= 80:
                    result["market_status"] = "强势"
                elif market_score >= 60:
                    result["market_status"] = "偏强"
                elif market_score >= 40:
                    result["market_status"] = "震荡"
                else:
                    result["market_status"] = "极差"
                
                logger.info(f"市场评分: {market_score}分, 状态: {result['market_status']}")
            except Exception as e:
                logger.error(f"获取市场评分失败: {e}")
                market_score = 50.0
            
            # 2. 生成持仓建议
            logger.info("步骤2: 生成持仓建议...")
            hold_list = self.hold_analyzer.get_hold_list()
            
            for hold in hold_list:
                suggestion = self.generate_hold_suggestion(hold, market_score)
                result["hold_suggestions"].append(suggestion)
            
            logger.info(f"持仓建议生成完成，共{len(hold_list)}只")
            
            # 3. 生成选股参考（如果市场状态允许）
            if market_score >= 50:
                logger.info("步骤3: 生成选股参考...")
                try:
                    stocks = self.stock_selector.run_selection()
                    result["stock_picks"] = stocks[:5]  # 只取前5只
                    logger.info(f"选股参考生成完成，共{len(result['stock_picks'])}只")
                except Exception as e:
                    logger.error(f"选股失败: {e}")
            
            logger.info("=" * 60)
            logger.info("尾盘交易计划生成完成")
            logger.info("=" * 60)
            
        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)
            logger.error(f"交易计划生成失败: {e}")
        
        return result
    
    def format_plan(self, result: Dict) -> str:
        """
        格式化交易计划为文本
        
        Args:
            result: 计划数据
        
        Returns:
            格式化的文本
        """
        lines = []
        
        lines.extend([
            "=" * 70,
            "                    14:50 尾盘交易计划",
            "=" * 70,
            f"生成时间: {result['generate_time']}",
            "",
            "-" * 70,
            "【市场状态】",
            f"  综合评分: {result['market_score']}分",
            f"  市场状态: {result['market_status']}",
            f"  操作建议: {result['market_suggestion']}",
            ""
        ])
        
        # 持仓建议
        if result.get("hold_suggestions"):
            lines.extend([
                "-" * 70,
                "【持仓操作建议】",
                ""
            ])
            
            for h in result["hold_suggestions"]:
                action_icon = {
                    "持有": "🔵",
                    "加仓": "🟢",
                    "减仓": "🟡",
                    "清仓": "🔴",
                    "止盈": "🟢",
                    "止损": "🔴"
                }.get(h['action'], "⚪")
                
                lines.extend([
                    f"  {action_icon} {h['ts_code']} {h['name']}",
                    f"     当前价: {h.get('current_price', 0)}元, 盈亏: {h.get('profit', 0)}%",
                    f"     建议: {h['action']}",
                    f"     原因: {h.get('reason', '-')}",
                    ""
                ])
        
        # 选股参考
        if result.get("stock_picks"):
            lines.extend([
                "-" * 70,
                "【尾盘选股参考】",
                ""
            ])
            
            for i, stock in enumerate(result["stock_picks"], 1):
                lines.extend([
                    f"  {i}. {stock['ts_code']} {stock['name']}",
                    f"     得分: {stock['total_score']}分 ({stock['level']})",
                    ""
                ])
        
        lines.extend([
            "=" * 70,
            "            请在收盘前完成相关操作",
            "=" * 70
        ])
        
        return "\n".join(lines)
    
    def format_markdown_plan(self, result: Dict) -> str:
        """
        格式化为Markdown（用于企业微信推送）
        
        Args:
            result: 计划数据
        
        Returns:
            Markdown文本
        """
        lines = []
        
        lines.extend([
            "## 📋 14:50 尾盘交易计划",
            "",
            f"**时间**: {result['generate_time']}",
            "",
            "---",
            "",
            "### 市场状态",
            "",
            f"**评分**: {result['market_score']}分 ({result['market_status']})",
            f"**建议**: {result['market_suggestion']}",
            "",
            "---"
        ])
        
        # 持仓建议
        if result.get("hold_suggestions"):
            lines.extend(["", "### 持仓操作", ""])
            
            for h in result["hold_suggestions"]:
                action = h['action']
                if action in ["清仓", "止损"]:
                    lines.append(f"- **{h['name']}**: <font color=\"warning\">{action}</font> ({h.get('profit', 0)}%)")
                elif action in ["减仓"]:
                    lines.append(f"- **{h['name']}**: <font color=\"info\">{action}</font> ({h.get('profit', 0)}%)")
                else:
                    lines.append(f"- **{h['name']}**: {action} ({h.get('profit', 0)}%)")
        
        # 选股参考
        if result.get("stock_picks"):
            lines.extend(["", "---", "", "### 选股参考", ""])
            
            for i, stock in enumerate(result["stock_picks"], 1):
                lines.append(f"{i}. **{stock['name']}** - {stock['total_score']}分")
        
        lines.extend(["", "---", "*请在收盘前完成相关操作*"])
        
        return "\n".join(lines)
    
    def run_and_push(self) -> Dict:
        """
        生成计划并推送
        
        Returns:
            计划数据
        """
        result = self.generate_plan()
        
        if result["status"] == "success":
            markdown_content = self.format_markdown_plan(result)
            self.message_pusher.push_markdown(markdown_content)
            logger.info("交易计划已推送到企业微信")
        
        return result
    
    def save_plan(self, result: Dict) -> bool:
        """
        保存计划到数据库
        
        Args:
            result: 计划数据
        
        Returns:
            是否成功
        """
        try:
            sql = """
                INSERT INTO system_log (log_time, log_level, module_name, log_content)
                VALUES (?, ?, ?, ?)
            """
            
            self.db.execute(sql, (
                result['generate_time'],
                "INFO",
                "trade_plan",
                f"尾盘计划生成 - 市场评分:{result['market_score']}分"
            ))
            
            logger.info("交易计划已保存")
            return True
        except Exception as e:
            logger.error(f"保存计划失败: {e}")
            return False
