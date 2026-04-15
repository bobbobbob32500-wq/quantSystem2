"""
导出LightGBM模型供突破策略使用
从optuna_breakout_optimize.py的训练结果中导出模型文件
"""
import json
import os
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.database import DatabaseManager
from src.core.config import ConfigManager


def export_lgb_model():
    """导出LightGBM模型"""
    print("=" * 60)
    print("导出LightGBM模型")
    print("=" * 60)
    
    # 加载模型配置
    model_config_path = "models/breakout_lgb_model.json"
    with open(model_config_path, "r", encoding="utf-8") as f:
        model_config = json.load(f)
    
    print(f"模型配置: {model_config_path}")
    print(f"版本: {model_config['version']}")
    print(f"AUC: {model_config['performance']['best_auc']}")
    
    # LightGBM参数
    lgb_params = model_config["lgb_params"]
    feature_cols = model_config["feature_cols"]
    
    print(f"\n特征数量: {len(feature_cols)}")
    print(f"LightGBM参数: {lgb_params}")
    
    # 创建输出目录
    os.makedirs("models", exist_ok=True)
    
    # 保存模型配置（供运行时加载）
    output_path = "models/breakout_lgb_model_v1.txt"
    
    # 由于我们没有保存训练时的模型对象，这里只保存配置
    # 实际使用时需要重新训练或从optuna脚本中导出
    
    print(f"\n模型配置已保存到: {model_config_path}")
    print("\n注意: 要使用LightGBM推理，需要:")
    print("1. 在optuna_breakout_optimize.py中添加模型保存代码")
    print("2. 或重新训练并保存模型")
    
    return model_config


if __name__ == "__main__":
    export_lgb_model()
