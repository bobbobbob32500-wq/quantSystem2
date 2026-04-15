# -*- coding: utf-8 -*-
"""
Qlib 快速入门 - 5 分钟体验 Qlib 因子计算
直接运行此脚本即可体验 Qlib 的核心功能
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.config import ConfigManager
from src.modules.qlib_lgb_params import get_lgb_params_for_qlib


def check_qlib():
    """检查 Qlib 是否可用"""
    try:
        import qlib
        return True
    except ImportError:
        return False


def demo_qlib_factors():
    """演示 Qlib 因子计算"""
    print("=" * 60)
    print("Qlib 因子计算演示")
    print("=" * 60)
    
    import qlib
    from qlib.data import D
    
    cfg = ConfigManager()
    uri = os.path.expanduser(str(cfg.get("qlib.provider_uri", "~/.qlib/qlib_data/cn_data")))
    qlib.init(provider_uri=uri)
    print("\n[1] Qlib 初始化成功")
    
    # 查看可用股票
    instruments = D.instruments('all')
    print(f"\n[2] 可用股票数量: {len(instruments)}")
    print(f"    示例: {list(instruments)[:5]}")
    
    # 获取股票数据
    fields = ['$open', '$close', '$high', '$low', '$volume']
    data = D.features(['SH600000'], fields, '2023-01-01', '2023-12-31')
    print(f"\n[3] 获取数据示例 (SH600000):")
    print(data.head())
    
    # 计算 Alpha158 因子
    from qlib.contrib.data.handler import Alpha158
    
    handler = Alpha158(
        instruments='SH600000',
        start_time='2023-01-01',
        end_time='2023-12-31'
    )
    
    factor_data = handler.fetch(col_mode='single')
    print(f"\n[4] Alpha158 因子计算结果:")
    print(f"    因子数量: {len(factor_data.columns)}")
    print(f"    交易日数量: {len(factor_data)}")
    print(f"    因子名称示例: {list(factor_data.columns[:5])}")
    
    # 查看因子值
    print(f"\n[5] 因子值示例 (前5行, 前5列):")
    print(factor_data.iloc[:5, :5])
    
    print("\n" + "=" * 60)
    print("演示完成!")
    print("=" * 60)


def demo_qlib_model():
    """演示 Qlib 模型训练"""
    print("\n" + "=" * 60)
    print("Qlib 模型训练演示 (LightGBM)")
    print("=" * 60)
    
    import qlib
    from qlib.data import D
    from qlib.data.dataset import DatasetH
    from qlib.contrib.data.handler import Alpha158
    from qlib.contrib.model.gbdt import LGBModel
    from qlib.contrib.eval.meta import RiskModel
    
    cfg = ConfigManager()
    uri = os.path.expanduser(str(cfg.get("qlib.provider_uri", "~/.qlib/qlib_data/cn_data")))
    qlib.init(provider_uri=uri)
    
    # 创建数据集
    dataset = DatasetH(
        handler={
            'class': 'Alpha158',
            'module_path': 'qlib.contrib.data.handler',
            'kwargs': {
                'start_time': '2020-01-01',
                'end_time': '2023-12-31',
                'fit_start_time': '2020-01-01',
                'fit_end_time': '2022-12-31',
                'instruments': 'csi300',
            },
        },
        segments={
            'train': ('2020-01-01', '2022-12-31'),
            'valid': ('2023-01-01', '2023-06-30'),
            'test': ('2023-07-01', '2023-12-31'),
        },
    )
    
    print("\n[1] 数据集创建成功")
    print(f"    训练集: 2020-01-01 ~ 2022-12-31")
    print(f"    验证集: 2023-01-01 ~ 2023-06-30")
    print(f"    测试集: 2023-07-01 ~ 2023-12-31")
    
    # 训练 LightGBM 模型（与 config.yaml 中 qlib 段及 Optuna 结果一致）
    model = LGBModel(**get_lgb_params_for_qlib(cfg))
    
    print("\n[2] 开始训练 LightGBM 模型...")
    model.fit(dataset)
    print("[3] 模型训练完成")
    
    # 预测
    pred = model.predict(dataset)
    print(f"\n[4] 预测结果:")
    print(f"    预测数量: {len(pred)}")
    print(pred.head())
    
    print("\n" + "=" * 60)
    print("模型训练演示完成!")
    print("=" * 60)


def demo_qlib_backtest():
    """演示 Qlib 回测"""
    print("\n" + "=" * 60)
    print("Qlib 回测演示")
    print("=" * 60)
    
    import qlib
    from qlib.data import D
    
    qlib.init(provider_uri='~/.qlib/qlib_data/cn_data')
    
    # 获取沪深300成分股
    instruments = D.instruments('csi300')
    print(f"\n[1] 沪深300成分股数量: {len(instruments)}")
    
    # 获取数据
    data = D.features(
        instruments[:10],
        ['$close', '$volume'],
        '2023-01-01', '2023-12-31'
    )
    
    print(f"\n[2] 数据获取成功")
    print(data.head())
    
    print("\n" + "=" * 60)
    print("回测演示完成!")
    print("=" * 60)


def main():
    """主函数"""
    if not check_qlib():
        print("Qlib 未安装或未激活!")
        print("\n请执行以下命令：")
        print("  1. conda activate qlib_env")
        print("  2. python scripts/qlib_quick_start.py")
        return
    
    print("\nQlib 快速入门")
    print("=" * 60)
    print("\n选择演示：")
    print("  1. 因子计算演示 (推荐)")
    print("  2. 模型训练演示")
    print("  3. 回测演示")
    print("  4. 全部演示")
    
    choice = input("\n请输入选项 (1-4): ").strip()
    
    if choice == '1':
        demo_qlib_factors()
    elif choice == '2':
        demo_qlib_model()
    elif choice == '3':
        demo_qlib_backtest()
    elif choice == '4':
        demo_qlib_factors()
        demo_qlib_model()
        demo_qlib_backtest()
    else:
        print("无效选项")


if __name__ == '__main__':
    main()
