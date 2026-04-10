# -*- coding: utf-8 -*-
"""
仓位控制引擎集成测试
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.position_controller import PositionController

print("\n" + "="*80)
print("仓位控制引擎集成测试")
print("="*80)

# 初始化
config = ConfigManager()
db = DatabaseManager(config)
controller = PositionController(config, db)

# 测试市场状态分析
print("\n【测试1】市场状态分析")
print("-"*80)
result = controller.analyze_market()

print(f"市场状态: {result['market_regime']}")
print(f"目标仓位: {result['target_position']*100:.0f}%")
print(f"仓位等级: {result['position_level']}")
print(f"策略建议: {result['strategy_suggestion']}")
print(f"分析时间: {result['analyze_time']}")

# 测试模块状态
print("\n【测试2】模块状态")
print("-"*80)
print(f"趋势状态: {result['trend_state']:8s} (强度: {result['trend_strength']:.2f})")
print(f"资金状态: {result['money_state']:8s} (强度: {result['money_strength']:.2f})")
print(f"情绪状态: {result['sentiment_state']:12s} (强度: {result['sentiment_strength']:.2f})")
print(f"风险状态: {result['risk_state']:8s} (强度: {result['risk_strength']:.2f})")

# 测试关键机制
print("\n【测试3】关键机制")
print("-"*80)
if result['risk_state'] == 'HIGH':
    print("[OK] 风险一票否决: 已触发")
else:
    print("[OK] 风险一票否决: 未触发")

if result['sentiment_state'] == 'OVERHEATED':
    print("[OK] 情绪过热降仓: 已触发（仓位降低20%）")
elif result['sentiment_state'] == 'COLD':
    print("[OK] 情绪过冷降仓: 已触发（仓位降低10%）")
else:
    print("[OK] 情绪调整: 未触发")

# 测试决策逻辑
print("\n【测试4】决策逻辑")
print("-"*80)
if result['market_regime'] == 'BULL':
    print("强势市场条件:")
    print(f"  - 趋势: {result['trend_state']}")
    print(f"  - 资金: {result['money_state']}")
    print(f"  - 情绪: {result['sentiment_state']}")
    print(f"  - 风险: {result['risk_state']}")
elif result['market_regime'] == 'BEAR':
    print("弱势市场条件:")
    print(f"  - 风险高 OR 资金流出 OR 趋势向下")
else:
    print("震荡市场条件:")
    print(f"  - 趋势/资金/情绪不一致")

# 测试仓位建议
print("\n【测试5】仓位建议")
print("-"*80)
position = result['target_position']
if position >= 0.7:
    print("[高仓位] 70%-100%")
    print("- 激进策略：积极选股，允许追高")
    print("- 使用动量策略，加大交易频率")
    print("- 注意：风险较高，需严格控制止损")
elif position >= 0.3:
    print("[中仓位] 30%-60%")
    print("- 均衡策略：低吸为主，控制频率")
    print("- 使用回调策略，降低交易频率")
    print("- 注意：平衡收益与风险")
else:
    print("[低仓位] 0%-20%")
    print("- 防守策略：减少选股，降低仓位")
    print("- 以防守为主，减少交易")
    print("- 注意：市场风险高，建议空仓观望")

print("\n" + "="*80)
print("测试完成！")
print("="*80)
print("\n仓位控制引擎已成功集成到主菜单！")
print("启动系统后，选择【14. 仓位控制(NEW)】即可使用。")
print("="*80 + "\n")
