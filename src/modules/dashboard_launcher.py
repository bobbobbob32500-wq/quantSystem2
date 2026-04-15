# -*- coding: utf-8 -*-
"""
Web 看板启动辅助：供 main.py 菜单统一调用，避免用户单独运行多个脚本。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def project_root() -> Path:
    """仓库根目录（本文件位于 src/modules/）。"""
    return Path(__file__).resolve().parents[2]


def check_dashboard_dependencies() -> tuple[bool, str]:
    """检查 Flask 看板所需依赖。"""
    missing: list[str] = []
    for pkg in ("flask", "pandas", "numpy"):
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        return False, f"缺少依赖: {', '.join(missing)}，请先执行: pip install {' '.join(missing)}"
    return True, ""


def launch_dashboard_in_new_console() -> tuple[bool, str]:
    """
    启动看板：Windows 下新开控制台窗口，不阻塞主菜单；
    其他平台使用独立会话后台进程。
    """
    ok, msg = check_dashboard_dependencies()
    if not ok:
        return False, msg
    root = project_root()
    script = root / "start_dashboard.py"
    if not script.is_file():
        return False, f"未找到启动脚本: {script}"
    cmd = [sys.executable, str(script)]
    try:
        if sys.platform == "win32":
            subprocess.Popen(
                cmd,
                cwd=str(root),
                creationflags=subprocess.CREATE_NEW_CONSOLE,  # type: ignore[attr-defined]
            )
        else:
            subprocess.Popen(cmd, cwd=str(root), start_new_session=True)
        host = os.environ.get("DASHBOARD_HOST", "0.0.0.0")
        port = os.environ.get("DASHBOARD_PORT", "8501")
        return (
            True,
            f"已在新窗口启动看板进程。浏览器访问: http://{host}:{port}/\n"
            f"    若页面无法打开，请查看新窗口中的报错信息。",
        )
    except Exception as exc:
        return False, str(exc)


def launch_dashboard_blocking() -> None:
    """在当前进程启动 Flask（阻塞直到 Ctrl+C），用于本地调试。"""
    root = project_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from start_dashboard import check_dependencies, start_dashboard

    if not check_dependencies():
        return
    start_dashboard()
