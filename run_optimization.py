# -*- coding: utf-8 -*-
"""
系统优化快速启动脚本
一键执行所有优化操作
"""

import sys
import subprocess
import importlib.util
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.core.logger import get_logger

logger = get_logger("optimizer_launcher")


class OptimizerLauncher:
    """优化启动器"""

    def __init__(self):
        self.project_root = project_root
        self.python = sys.executable
        self.success_count = 0
        self.fail_count = 0
        self.skip_count = 0

    @staticmethod
    def _module_available(module_name: str) -> bool:
        """检查模块是否可用"""
        return importlib.util.find_spec(module_name) is not None

    def run_command(self, cmd: str, description: str) -> bool:
        """运行命令"""
        logger.info(f"开始: {description}")
        try:
            result = subprocess.run(cmd, shell=True, cwd=str(self.project_root))
            if result.returncode == 0:
                logger.info(f"✓ 完成: {description}")
                self.success_count += 1
                return True

            logger.error(f"✗ 失败: {description}")
            self.fail_count += 1
            return False
        except Exception as e:
            logger.error(f"✗ 错误: {description} - {e}")
            self.fail_count += 1
            return False

    def skip_step(self, description: str, reason: str) -> None:
        """记录跳过步骤"""
        logger.warning(f"- 跳过: {description} ({reason})")
        self.skip_count += 1

    def optimize_database(self) -> bool:
        """优化数据库"""
        logger.info("\n" + "=" * 60)
        logger.info("第一步：数据库优化")
        logger.info("=" * 60)

        return self.run_command(
            f'"{self.python}" "tools/db_optimizer.py"',
            "数据库优化（创建索引、分析表、清理数据库）",
        )

    def run_tests(self) -> bool:
        """运行测试"""
        logger.info("\n" + "=" * 60)
        logger.info("第二步：运行测试")
        logger.info("=" * 60)

        return self.run_command(
            f'"{self.python}" -m pytest "tests/test_code_standards.py" -v',
            "代码规范工具测试",
        )

    def generate_coverage_report(self) -> bool:
        """生成覆盖率报告"""
        logger.info("\n" + "=" * 60)
        logger.info("第三步：生成覆盖率报告")
        logger.info("=" * 60)

        if not self._module_available("pytest"):
            self.skip_step("生成测试覆盖率报告", "未安装 pytest")
            return True

        if not self._module_available("pytest_cov"):
            self.skip_step("生成测试覆盖率报告", "未安装 pytest-cov")
            return True

        return self.run_command(
            f'"{self.python}" -m pytest "tests/" --cov=src --cov-report=html --cov-report=term',
            "生成测试覆盖率报告",
        )

    def run_code_quality_checks(self) -> bool:
        """运行代码质量检查"""
        logger.info("\n" + "=" * 60)
        logger.info("第四步：代码质量检查")
        logger.info("=" * 60)

        checks = []
        if self._module_available("pylint"):
            checks.append(
                (f'"{self.python}" -m pylint "src/core/code_standards.py"', "Pylint 检查")
            )
        else:
            self.skip_step("Pylint 检查", "未安装 pylint")

        if self._module_available("flake8"):
            checks.append(
                (f'"{self.python}" -m flake8 "src/core/code_standards.py"', "Flake8 检查")
            )
        else:
            self.skip_step("Flake8 检查", "未安装 flake8")

        all_success = True
        for cmd, desc in checks:
            if not self.run_command(cmd, desc):
                all_success = False

        return all_success

    def print_summary(self):
        """打印总结"""
        logger.info("\n" + "=" * 60)
        logger.info("优化完成总结")
        logger.info("=" * 60)
        logger.info(f"✓ 成功: {self.success_count}")
        logger.info(f"- 跳过: {self.skip_count}")
        logger.info(f"✗ 失败: {self.fail_count}")

        if self.fail_count == 0:
            logger.info("\n🎉 所有优化操作完成！")
        else:
            logger.warning(f"\n⚠️  有 {self.fail_count} 个操作失败，请检查日志")

    def run_all(self):
        """运行所有优化"""
        logger.info("\n" + "=" * 60)
        logger.info("A股量化系统 - 优化启动")
        logger.info("=" * 60)

        # 1. 数据库优化
        self.optimize_database()

        # 2. 运行测试
        self.run_tests()

        # 3. 生成覆盖率报告
        self.generate_coverage_report()

        # 4. 代码质量检查
        self.run_code_quality_checks()

        # 5. 打印总结
        self.print_summary()


def main():
    """主函数"""
    launcher = OptimizerLauncher()
    launcher.run_all()


if __name__ == "__main__":
    main()
