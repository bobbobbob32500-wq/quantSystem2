# -*- coding: utf-8 -*-
"""
P0 优化功能快速测试脚本，验证修复后的基础能力是否正常工作。
"""

import os
import sys

import pytest

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.factor_analysis import FactorAnalyzer
from src.core.logger import get_logger

logger = get_logger("test_p0_quick")


def run_factor_ic_analysis_check(strict: bool = False) -> bool:
    """执行因子 IC 分析检查。strict=True 时以 pytest 语义失败/跳过。"""
    logger.info("=" * 80)
    logger.info("测试因子IC分析功能")
    logger.info("=" * 80)

    config = ConfigManager()
    db = DatabaseManager(config)

    try:
        analyzer = FactorAnalyzer(config, db)
        logger.info("因子分析器初始化成功")
    except Exception as exc:
        message = f"因子分析器初始化失败: {exc}"
        logger.error(message)
        if strict:
            pytest.fail(message)
        return False

    sql = "SELECT COUNT(*) as count FROM factor_values"
    result = db.query_one(sql)
    factor_count = result['count'] if result else 0
    logger.info(f"factor_values表中有 {factor_count} 条记录")

    if factor_count == 0:
        message = "factor_values 表为空，缺少可用于 IC 分析的研究数据"
        logger.warning(message)
        if strict:
            pytest.skip(message)
        return False

    factor_names = ['trend_score', 'momentum_score', 'volume_score', 'pullback_score', 'quality_score']
    calculated_count = 0

    logger.info("开始计算因子IC...")
    for factor_name in factor_names:
        try:
            ic_df = analyzer.calculate_stock_factor_ic(factor_name, period=5)
            if ic_df.empty:
                logger.warning(f"{factor_name}: 暂无IC数据")
                continue

            ic_stats = analyzer.calculate_ic_statistics(ic_df)
            logger.info(
                "%s: IC均值=%.3f, IC_IR=%.3f",
                factor_name,
                ic_stats['ic_mean'],
                ic_stats['ic_ir']
            )
            calculated_count += 1
        except Exception as exc:
            logger.error(f"{factor_name}: 计算失败 - {exc}")
            if strict:
                pytest.fail(f"{factor_name} IC 计算失败: {exc}")
            return False

    if strict and calculated_count == 0:
        pytest.skip("当前数据库中尚无足够的因子样本可生成 IC 统计")

    logger.info("=" * 80)
    logger.info("因子IC分析检查完成")
    logger.info("=" * 80)
    return calculated_count > 0


def run_database_connection_check(strict: bool = False) -> bool:
    """执行数据库连接检查。strict=True 时以 pytest 语义失败。"""
    logger.info("=" * 80)
    logger.info("测试数据库连接")
    logger.info("=" * 80)

    config = ConfigManager()
    db = DatabaseManager(config)

    try:
        conn = db._get_connection()
        logger.info("数据库连接成功")

        sql = "SELECT COUNT(*) as count FROM stock_basic"
        result = conn.execute(sql).fetchone()
        stock_count = result[0] if result else 0
        logger.info(f"查询成功: stock_basic表有 {stock_count} 条记录")

        conn.close()
        logger.info("连接关闭成功")
        return True
    except Exception as exc:
        message = f"数据库连接失败: {exc}"
        logger.error(message)
        if strict:
            pytest.fail(message)
        return False


def test_database_connection():
    """测试数据库连接。"""
    assert run_database_connection_check(strict=True) is True


def test_factor_ic_analysis():
    """测试因子 IC 分析功能。"""
    run_factor_ic_analysis_check(strict=True)


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("P0优化功能快速测试")
    print("=" * 80 + "\n")

    print("\n【测试1: 数据库连接】")
    test1_passed = run_database_connection_check(strict=False)

    print("\n【测试2: 因子IC分析】")
    test2_passed = run_factor_ic_analysis_check(strict=False)

    print("\n" + "=" * 80)
    print("测试总结")
    print("=" * 80)
    print(f"数据库连接: {'通过' if test1_passed else '失败'}")
    print(f"因子IC分析: {'通过' if test2_passed else '失败/跳过'}")

    if test1_passed and test2_passed:
        print("\n所有测试通过，P0优化功能可以正常使用")
        print("可运行主程序使用: python main.py")
    else:
        print("\n部分测试未通过，请检查数据准备或错误日志")

    print("=" * 80)
