# -*- coding: utf-8 -*-
"""
仓位控制引擎测试脚本
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.position_controller import PositionController

def test_position_controller():
    """测试仓位控制引擎"""
    print("\n" + "=" * 80)
    print("测试仓位控制引擎")
    print("=" * 80 + "\n")
    
    # 初始化
    config = ConfigManager()
    db = DatabaseManager(config)
    controller = PositionController(config, db)
    
    # 分析市场
    print("正在分析市场...")
    result = controller.analyze_market()
    
    # 输出结果
    print(f"\n{'='*80}")
    print("仓位控制结果")
    print(f"{'='*80}")
    
    print(f"\n市场状态: {result['market_regime']}")
    print(f"目标仓位: {result['target_position']*100:.0f}%")
    print(f"仓位等级: {result['position_level']}")
    print(f"策略建议: {result['strategy_suggestion']}")
    print(f"分析时间: {result['analyze_time']}")
    
    print(f"\n{'-'*80}")
    print("模块状态")
    print(f"{'-'*80}")
    print(f"趋势状态: {result['trend_state']:8s} (强度: {result['trend_strength']:.2f})")
    print(f"资金状态: {result['money_state']:8s} (强度: {result['money_strength']:.2f})")
    print(f"情绪状态: {result['sentiment_state']:12s} (强度: {result['sentiment_strength']:.2f})")
    print(f"风险状态: {result['risk_state']:8s} (强度: {result['risk_strength']:.2f})")
    
    print(f"\n{'='*80}")
    print("关键机制")
    print(f"{'='*80}")
    
    # 风险一票否决
    if result['risk_state'] == 'HIGH':
        print("[OK] 风险一票否决: 已触发")
    else:
        print("[OK] 风险一票否决: 未触发")
    
    # 情绪过热降仓
    if result['sentiment_state'] == 'OVERHEATED':
        print("[OK] 情绪过热降仓: 已触发（仓位降低20%）")
    elif result['sentiment_state'] == 'COLD':
        print("[OK] 情绪过冷降仓: 已触发（仓位降低10%）")
    else:
        print("[OK] 情绪调整: 未触发")
    
    print(f"\n{'='*80}")
    print("决策逻辑")
    print(f"{'='*80}")
    
    # 市场状态判定
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
    
    print(f"\n{'='*80}")
    print("测试完成")
    print(f"{'='*80}\n")

if __name__ == "__main__":
    test_position_controller()
