# -*- coding: utf-8 -*-
"""
启动带虚拟交易跟踪的实时监控系统
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime

print("="*80)
print("启动实时监控系统（带虚拟交易跟踪）")
print("="*80)

# 导入系统
try:
    from src.modules.enhanced_hybrid_system import EnhancedHybridSystem
    print("[OK] 系统模块导入成功")
except Exception as e:
    print(f"[FAIL] 导入失败: {e}")
    sys.exit(1)

# 创建系统
print("\n创建系统...")
try:
    system = EnhancedHybridSystem(
        enable_auto_optimization=True,   # 启用自动优化
        enable_virtual_trade=True        # 启用虚拟交易跟踪
    )
    print(f"[OK] 系统创建成功")
    print(f"  - 自动优化: {system.enable_auto_optimization}")
    print(f"  - 虚拟交易: {system.enable_virtual_trade}")
except Exception as e:
    print(f"[FAIL] 创建失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 准备候选池
print("\n准备候选池...")
try:
    system.prepare_candidate_pool()
    print(f"[OK] 候选池准备完成: {len(system.candidate_pool)}只股票")
except Exception as e:
    print(f"[FAIL] 候选池准备失败: {e}")
    sys.exit(1)

# 显示候选池
if system.candidate_pool:
    print("\n候选池股票:")
    for i, stock in enumerate(system.candidate_pool[:10], 1):
        pool_type = "核心池" if stock.get('pool_type') == 'core' else "备选池"
        print(f"  {i}. {stock['symbol']} {stock['name']} [{pool_type}]")

# 启动监控
print("\n" + "="*80)
print("启动实时监控...")
print("="*80)
print("\n系统将自动执行以下操作:")
print("  1. 检测买点信号")
print("  2. 记录虚拟交易")
print("  3. 检测平仓条件（止损-5%、止盈+10%、时间退出24h）")
print("  4. 计算盈亏并反馈给优化系统")
print("\n按 Ctrl+C 停止监控")
print("="*80)

try:
    # 启动监控（每10秒轮询一次）
    system.start_monitoring(interval_seconds=10)
except KeyboardInterrupt:
    print("\n\n监控已停止")
    
    # 显示虚拟交易统计
    if system.virtual_tracker:
        print("\n" + "="*80)
        print("虚拟交易统计")
        print("="*80)
        system.virtual_tracker.print_statistics()
        
        # 保存状态
        system.virtual_tracker.save_state()
        print("\n虚拟交易记录已保存")
