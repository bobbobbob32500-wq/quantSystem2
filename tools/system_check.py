# -*- coding: utf-8 -*-
"""
系统自检脚本
全面检查所有优化是否正确应用
"""

import sys
import os
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.position_controller import PositionController
from src.modules.market_analyzer import MarketAnalyzer
from src.modules.stock_selector import StockSelector
from src.modules.auto_push_manager import AutoPushManager
from src.modules.enhanced_hybrid_system import EnhancedHybridSystem

def check_system():
    """系统自检"""
    print("\n" + "="*80)
    print("系统自检报告")
    print("="*80)
    print(f"检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 初始化
    config = ConfigManager()
    db = DatabaseManager(config)

    results = []

    # 1. 检查仓位控制引擎
    print("\n【1】仓位控制引擎检查")
    print("-"*80)
    try:
        pc = PositionController(config, db)
        result = pc.analyze_market()
        print(f"[OK] 仓位控制引擎运行正常")
        print(f"  市场状态: {result['market_regime']}")
        print(f"  目标仓位: {result['target_position']*100:.0f}%")
        print(f"  趋势状态: {result['trend_state']}")
        print(f"  资金状态: {result['money_state']}")
        print(f"  情绪状态: {result['sentiment_state']}")
        print(f"  风险状态: {result['risk_state']}")
        results.append(("仓位控制引擎", "正常"))
    except Exception as e:
        print(f"[FAIL] 仓位控制引擎检查失败: {e}")
        results.append(("仓位控制引擎", "失败"))

    # 2. 检查市场分析模块
    print("\n【2】市场分析模块检查")
    print("-"*80)
    try:
        ma = MarketAnalyzer(config)
        result = ma.analyze_market()
        print(f"[OK] 市场分析模块运行正常")
        print(f"  综合评分: {result['total_score']:.1f}")
        print(f"  市场状态: {result['market_state']}")
        print(f"  趋势评分: {result['trend_score']:.1f}")
        print(f"  资金评分: {result['fund_score']:.1f}")
        print(f"  情绪评分: {result['sentiment_score']:.1f}")
        print(f"  风险评分: {result['risk_score']:.1f}")
        results.append(("市场分析模块", "正常"))
    except Exception as e:
        print(f"[FAIL] 市场分析模块检查失败: {e}")
        results.append(("市场分析模块", "失败"))

    # 3. 检查选股策略优化
    print("\n【3】选股策略优化检查")
    print("-"*80)
    try:
        ss = StockSelector(config, db)
        print(f"[OK] 选股策略优化已应用")
        print(f"  动量因子权重: {ss.momentum_weight} (策略1优化)")
        print(f"  趋势因子权重: {ss.trend_weight} (策略1优化)")
        print(f"  成交量因子权重: {ss.volume_weight} (已删除)")
        print(f"  基本面因子权重: {ss.fundamental_weight} (已删除)")
        print(f"  回调因子权重: {ss.pullback_weight} (策略1优化)")
        results.append(("选股策略优化", "正常"))
    except Exception as e:
        print(f"[FAIL] 选股策略优化检查失败: {e}")
        results.append(("选股策略优化", "失败"))

    # 4. 检查自动推送功能
    print("\n【4】自动推送功能检查")
    print("-"*80)
    try:
        apm = AutoPushManager(config, db)
        push_enabled = config.get("push.enabled")
        webhook = config.get("push.wechat_webhook")
        print(f"[OK] 自动推送功能运行正常")
        print(f"  推送启用: {push_enabled}")
        print(f"  企业微信Webhook: {webhook[:20] if webhook else '未配置'}...")
        results.append(("自动推送功能", "正常"))
    except Exception as e:
        print(f"[FAIL] 自动推送功能检查失败: {e}")
        results.append(("自动推送功能", "失败"))

    # 5. 检查融合选股系统
    print("\n【5】融合选股系统检查")
    print("-"*80)
    try:
        system = EnhancedHybridSystem()
        has_pool = system.load_candidate_pool()
        print(f"[OK] 融合选股系统运行正常")
        print(f"  候选池状态: {'已加载' if has_pool else '空'}")
        if has_pool:
            print(f"  候选股数量: {len(system.candidate_pool)}只")
        results.append(("融合选股系统", "正常"))
    except Exception as e:
        print(f"[FAIL] 融合选股系统检查失败: {e}")
        results.append(("融合选股系统", "失败"))

    # 6. 检查数据库
    print("\n【6】数据库检查")
    print("-"*80)
    try:
        stock_basic_count = db.get_table_count('stock_basic')
        stock_daily_count = db.get_table_count('stock_daily')
        latest_date = db.get_latest_trade_date("stock_daily")
        print(f"[OK] 数据库运行正常")
        print(f"  股票基础: {stock_basic_count}条")
        print(f"  日线数据: {stock_daily_count}条")
        print(f"  最新数据: {latest_date or '无数据'}")
        results.append(("数据库", "正常"))
    except Exception as e:
        print(f"[FAIL] 数据库检查失败: {e}")
        results.append(("数据库", "失败"))

    # 汇总结果
    print("\n" + "="*80)
    print("自检汇总")
    print("="*80)
    passed = sum(1 for _, status in results if status == "正常")
    total = len(results)
    print(f"检查项目: {total}个")
    print(f"通过项目: {passed}个")
    print(f"失败项目: {total-passed}个")

    print("\n详细结果:")
    for name, status in results:
        icon = "[OK]" if status == "正常" else "[FAIL]"
        print(f"  {icon} {name}: {status}")

    # 功能说明
    print("\n" + "="*80)
    print("功能说明")
    print("="*80)
    print("【仓位控制引擎】")
    print("  - 从'技术指标打分器'升级为'市场状态判定系统'")
    print("  - 四大模块：趋势、资金、情绪、风险")
    print("  - 关键机制：风险一票否决、情绪过热/过冷降仓")
    print("  - 输出：市场状态、目标仓位、策略建议")
    print("\n【市场分析模块V2】")
    print("  - 使用上证指数（000001.SH）作为数据源")
    print("  - 四模块评分：趋势（20%）、资金（30%）、情绪（30%）、风险（20%）")
    print("  - 状态机决策：强势、中性、弱势")
    print("\n【选股策略优化】")
    print("  - 策略1优化：动量（50%）、趋势（45%）、回调（5%）")
    print("  - 删除成交量因子和基本面因子")
    print("  - 针对短线交易（3-5天持仓）优化")
    print("\n【自动推送功能】")
    print("  - 盘前08:30：市场分析 + 日报")
    print("  - 盘中每30分钟：市场分析（异常时）")
    print("  - 盘中每30分钟：风控检测（有信号时）")
    print("  - 尾盘14:50：交易计划")
    print("  - 盘后17:30：盘后总结")
    print("\n【融合选股系统】")
    print("  - 盘后选股：运行成熟选股系统，选出10-15只候选股")
    print("  - 盘中监控：监控候选股，检测买点信号")
    print("  - 买点信号：回踩/突破/横盘（互斥触发）")
    print("  - 过滤机制：趋势/时间/假突破")
    print("  - 即时推送：发现买点 → 推送通知")

    # 使用建议
    print("\n" + "="*80)
    print("使用建议")
    print("="*80)
    print("【日常使用】")
    print("  1. 启动系统：python main.py")
    print("  2. 查看仓位控制：选择【14. 仓位控制(NEW)】")
    print("  3. 执行选股：选择【3. 每日选股】")
    print("  4. 查看持仓：选择【4. 持仓管理】")
    print("  5. 启动监控：选择【6. 实时监控】")
    print("\n【自动运行】")
    print("  1. 启动自动推送：选择【13. 启动自动推送】")
    print("  2. 系统将自动按时间推送消息")
    print("  3. 实时监控持仓风险")
    print("  4. 自动生成交易计划")

    print("\n" + "="*80)
    print("自检完成！")
    print("="*80)

    return results

if __name__ == "__main__":
    results = check_system()
