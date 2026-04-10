from __future__ import annotations

import os
import sys


def check_dependencies() -> bool:
    """检查必要依赖，缺失时给出安装提示并返回 False。"""
    print("=" * 80)
    print("检查看板依赖")
    print("=" * 80)

    missing = []
    for package in ["flask", "pandas", "numpy"]:
        try:
            __import__(package)
            print(f"  {package}: 已安装")
        except ImportError:
            print(f"  {package}: 未安装")
            missing.append(package)

    if missing:
        print()
        print("缺少以下依赖，请先执行安装：")
        print(f"  pip install {' '.join(missing)}")
        return False

    print()
    return True


def start_dashboard():
    """直接在当前进程中启动看板 Flask 应用。"""
    print("=" * 80)
    print("启动 Web 可视化看板")
    print("=" * 80)
    print()

    host = os.environ.get("DASHBOARD_HOST", "127.0.0.1")
    port = int(os.environ.get("DASHBOARD_PORT", "8501"))

    print(f"看板地址: http://{host}:{port}")
    print("按 Ctrl+C 停止看板")
    print("=" * 80)
    print()

    # 直接导入并运行，避免 subprocess 吞掉异常信息
    from dashboard import create_app

    app = create_app()
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    try:
        if not check_dependencies():
            sys.exit(1)
        start_dashboard()
    except KeyboardInterrupt:
        print("\n看板已停止")
    except Exception as exc:
        print(f"\n启动失败: {exc}")
        sys.exit(1)
