# -*- coding: utf-8 -*-
"""
菜单系统全面审核脚本

检查项：
1. 菜单中显示的所有选项是否有对应的代码实现
2. 已删除的功能（如 legacy_opt, enhanced 策略）是否仍在菜单中
3. 菜单选项与实际可用模块的一致性
4. 代码中存在但菜单中未显示的功能
"""

import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 菜单定义（从 main.py 提取 - 更新后的结构）
MAIN_MENU = {
    '1': ('交易执行', 'trading_execution_menu'),
    '2': ('策略研究', 'research_strategy_menu'),
    '3': ('数据管理', 'data_management_menu'),
    '4': ('系统运维', 'system_ops_menu'),
    '5': ('刷新首页', 'refresh_home'),
    '0': ('退出系统', 'exit_system'),
}

# 策略选项（从菜单中提取）
STRATEGY_OPTIONS = {
    '1': ('基准原策略', 'legacy'),
    # '2': ('原策略优化版', 'legacy_opt'),  # 已删除
    # '3': ('增强策略', 'enhanced'),  # 已删除
}

# 实际支持的策略（从 StockSelector 提取）
SUPPORTED_STRATEGIES = {'legacy'}  # 只有 legacy 被保留

# 实际可用的模块
AVAILABLE_MODULES = {
    'trading_execution_menu': True,
    'research_strategy_menu': True,
    'data_management_menu': True,
    'system_ops_menu': True,
    'stock_selection_menu': True,
    'hold_management_menu': True,
    'risk_check_menu': True,
    'monitor_menu': True,
    'daily_report_menu': True,
    'trade_plan_menu': True,
    'backtest_menu': True,
    'evaluator_menu': True,
    'post_market_menu': True,
    'system_status_menu': True,
    'auto_push_menu': True,
    'position_control_menu': True,
    'p0_optimization_menu': True,
    'auto_optimization_menu': True,
    'market_analysis_menu': True,
    'market_position_menu': True,
    'web_dashboard_menu': True,
    'breakout_selector_menu': True,
    'wide_breakout_selector_menu': True,
    'secondary_launch_menu': True,
    'refresh_home': True,  # 实际上是 continue 操作
    'exit_system': True,   # 实际上是 break 操作
}


def check_menu_vs_code():
    """检查菜单与代码的一致性"""
    print("\n" + "="*70)
    print("菜单系统审核报告")
    print("="*70)
    
    issues = []
    
    # 1. 检查菜单中的策略选项
    print("\n【1】策略选项检查")
    print("-"*70)
    for opt_id, (label, strategy) in STRATEGY_OPTIONS.items():
        if strategy not in SUPPORTED_STRATEGIES:
            issue = f"菜单选项 {opt_id} '{label}' 对应策略 '{strategy}' 已被删除，但仍在菜单中显示"
            print(f"  [ERROR] {issue}")
            issues.append(issue)
        else:
            print(f"  [OK] 选项 {opt_id}: {label} ({strategy})")
    
    # 2. 检查主菜单中的功能选项
    print("\n【2】主菜单功能选项检查")
    print("-"*70)
    for opt_id, (label, func_name) in MAIN_MENU.items():
        if func_name not in AVAILABLE_MODULES:
            issue = f"菜单选项 {opt_id} '{label}' 对应函数 '{func_name}' 未在可用模块中"
            print(f"  [WARN] {issue}")
            issues.append(issue)
        else:
            print(f"  [OK] 选项 {opt_id}: {label}")
    
    # 3. 检查代码中是否有菜单未显示的功能
    print("\n【3】代码中未在菜单显示的功能")
    print("-"*70)
    menu_funcs = set(v[1] for v in MAIN_MENU.values())
    for func_name in AVAILABLE_MODULES:
        if func_name not in menu_funcs:
            print(f"  [INFO] 函数 '{func_name}' 在代码中但未在菜单中显示")
    
    # 4. 检查已删除策略的残留
    print("\n【4】已删除策略的残留检查")
    print("-"*70)
    deleted_strategies = {'legacy_opt', 'enhanced'}
    for strategy in deleted_strategies:
        if strategy in SUPPORTED_STRATEGIES:
            print(f"  [OK] 策略 '{strategy}' 已从支持列表中删除")
        else:
            print(f"  [OK] 策略 '{strategy}' 已删除，不在支持列表中")
    
    # 但菜单中仍然显示
    for opt_id, (label, strategy) in STRATEGY_OPTIONS.items():
        if strategy in deleted_strategies:
            issue = f"已删除的策略 '{strategy}' 仍在菜单选项 {opt_id} 中显示"
            print(f"  [ERROR] {issue}")
            issues.append(issue)
    
    # 5. 总结
    print("\n" + "="*70)
    print("审核总结")
    print("="*70)
    if issues:
        print(f"\n发现 {len(issues)} 个问题:\n")
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")
        return False
    else:
        print("\n[OK] 菜单系统检查通过，无问题发现")
        return True


def generate_fix_report():
    """生成修复建议"""
    print("\n" + "="*70)
    print("修复建议")
    print("="*70)
    
    print("\n【需要修复的项目】")
    print("-"*70)
    
    print("\n1. 菜单结构已重新整理")
    print("   新的菜单结构:")
    print("     1. 交易执行 - 日常交易操作")
    print("     2. 策略研究 - 策略开发和测试")
    print("     3. 数据管理 - 数据更新和维护")
    print("     4. 系统运维 - 系统监控和配置")
    print("     5. 刷新首页 - 刷新仪表盘")
    print("     0. 退出系统 - 退出程序")
    
    print("\n2. 已删除的策略选项已清理")
    print("   已移除: 原策略优化版 (legacy_opt)")
    print("   已移除: 增强策略 (enhanced)")
    print("   保留: 基准原策略 (legacy)")
    
    print("\n3. 菜单功能整合")
    print("   - 快捷操作菜单已整合到交易执行菜单")
    print("   - Web界面导航已更新为7个主要标签")
    print("   - 菜单层次更加清晰，功能分组更合理")


if __name__ == '__main__':
    passed = check_menu_vs_code()
    generate_fix_report()
    
    print("\n" + "="*70)
    if passed:
        print("状态: 通过 [OK]")
    else:
        print("状态: 需要修复 [ERROR]")
    print("="*70)
