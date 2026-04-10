# -*- coding: utf-8 -*-
"""
核心功能自动化自检：选股、盘中信号构建、推送、看板 API、监控生命周期等。
用法: python tools/core_function_self_check.py [--write-report]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 与业务域对齐的回归用例集（不含 nightly/slow 默认跳过的用例需加 --run-nightly 才跑）
CORE_TEST_FILES = [
    "tests/test_stock_selector_pre_market.py",
    "tests/test_optimized_buy_signals.py",
    "tests/test_wechat_pusher_encoding.py",
    "tests/test_signal_building_runtime.py",
    "tests/test_dashboard_web.py",
    "tests/test_message_templates.py",
    "tests/test_position_event_store.py",
    "tests/test_monitor_lifecycle_runtime.py",
    "tests/test_realtime_signal_chain.py",
    "tests/test_system_integrity_guards.py",
]


def run_pytest() -> tuple[int, str]:
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *CORE_TEST_FILES,
        "-v",
        "--tb=short",
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    return proc.returncode, out


def main() -> int:
    parser = argparse.ArgumentParser(description="核心功能自检")
    parser.add_argument(
        "--write-report",
        action="store_true",
        help="将摘要写入 data/reports/核心功能验证报告_<时间戳>.md",
    )
    args = parser.parse_args()

    print("=" * 72)
    print("核心功能自检（pytest）")
    print("=" * 72)
    print("范围: 选股预检、盘中买点信号、消息模板与推送编码、看板 API、监控生命周期等")
    print()

    code, output = run_pytest()
    print(output)
    if code != 0:
        print(f"\n自检结束: 失败 (退出码 {code})")
    else:
        print("\n自检结束: 通过")

    if args.write_report:
        report_dir = ROOT / "data" / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = report_dir / f"核心功能验证报告_{stamp}.md"

        passed = len(re.findall(r" PASSED ", output))
        skipped = len(re.findall(r" SKIPPED ", output))
        failed = len(re.findall(r" FAILED ", output))
        summary_line = ""
        for line in output.splitlines():
            if "passed" in line and ("skipped" in line or "failed" in line):
                summary_line = line.strip()
                break
        lines = [
            "# 核心功能验证报告（自动化）",
            "",
            "## 执行摘要",
            "",
            f"- **生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"- **统计（行级匹配）**: 约 {passed} 通过 / {skipped} 跳过 / {failed} 失败",
            f"- **pytest 汇总行**: {summary_line or '（见下文）'}",
            f"- **自检结论**: {'通过' if code == 0 and failed == 0 else '需处理失败用例'}",
            "",
            "---",
            "",
            f"- **生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"- **命令**: `python -m pytest` + 固定用例列表（见 `tools/core_function_self_check.py`）",
            "",
            "## 覆盖模块",
            "",
            "| 领域 | 对应测试文件 |",
            "|------|----------------|",
            "| 选股（盘前预检等） | test_stock_selector_pre_market.py |",
            "| 盘中买点/信号 | test_optimized_buy_signals.py, test_signal_building_runtime.py |",
            "| 推送与模板 | test_wechat_pusher_encoding.py, test_message_templates.py |",
            "| 持仓事件落库 | test_position_event_store.py |",
            "| Web 看板 API | test_dashboard_web.py |",
            "| 监控生命周期 | test_monitor_lifecycle_runtime.py |",
            "| 实时信号链 | test_realtime_signal_chain.py |",
            "| 系统完整性约束 | test_system_integrity_guards.py |",
            "",
            "## pytest 原始输出",
            "",
            "```",
            output.strip(),
            "```",
            "",
            "## 说明",
            "",
            "- `test_stock_selector_pre_market` 中带 `nightly` 标记的用例默认跳过，需加 `--run-nightly` 才执行。",
            "- 完整实盘表现需结合真实行情与 Tushare 额度，本自检以回归与逻辑为主。",
            "",
        ]
        report_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"\n报告已写入: {report_path}")

    return code


if __name__ == "__main__":
    sys.exit(main())
