from __future__ import annotations

import argparse
import os
import subprocess
import sys
import venv
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIRS = (
    "data/cache",
    "data/database/backup",
    "data/history_records",
    "data/intraday_cache",
    "data/logs",
    "data/releases",
    "logs",
    "artifacts/portable_baseline",
)
REQUIRED_RUNTIME_FILES = (
    "data/database/quant_system.db",
    "data/history_recommendation.db",
    "data/cache/candidate_pool.json",
)
DEFAULT_JSON_PAYLOADS = {
    "data/cache/virtual_trades.json": {
        "updated_at": None,
        "open_trades": [],
        "closed_trades": [],
        "stats": {},
    },
    "data/cache/web_background_tasks.json": {
        "updated_at": None,
        "tasks": [],
    },
    "data/cache/monitor_session.json": {
        "updated_at": None,
        "session": {},
    },
}


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def ensure_python_version() -> None:
    if sys.version_info < (3, 10):
        raise RuntimeError("当前项目建议使用 Python 3.10+ 运行")


def ensure_directories(project_root: Path) -> None:
    for relative in DEFAULT_DIRS:
        (project_root / relative).mkdir(parents=True, exist_ok=True)


def ensure_default_runtime_files(project_root: Path) -> None:
    import json

    for relative, payload in DEFAULT_JSON_PAYLOADS.items():
        path = project_root / relative
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_venv(venv_dir: Path) -> Path:
    python_path = _venv_python(venv_dir)
    if python_path.exists():
        return python_path
    print(f"创建虚拟环境: {venv_dir}")
    builder = venv.EnvBuilder(with_pip=True)
    builder.create(venv_dir)
    return python_path


def install_requirements(project_root: Path, python_path: Path) -> None:
    files = ("requirements.txt", "requirements_api.txt")
    for filename in files:
        requirement_file = project_root / filename
        print(f"安装依赖: {filename}")
        subprocess.run(
            [str(python_path), "-m", "pip", "install", "-r", str(requirement_file)],
            check=True,
            cwd=str(project_root),
        )


def validate_runtime_files(project_root: Path) -> int:
    missing = [path for path in REQUIRED_RUNTIME_FILES if not (project_root / path).exists()]
    if not missing:
        print("运行数据检查通过")
        return 0
    print("以下运行数据缺失，请先执行 restore_portable_baseline.py 恢复基线包:")
    for path in missing:
        print(f"  - {path}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化可迁移基线环境")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=PROJECT_ROOT,
        help="项目根目录，默认当前仓库根目录",
    )
    parser.add_argument(
        "--venv",
        type=Path,
        default=PROJECT_ROOT / ".venv",
        help="虚拟环境目录，默认 <project>/.venv",
    )
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="跳过 pip 依赖安装",
    )
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    venv_dir = args.venv.resolve()

    ensure_python_version()
    ensure_directories(project_root)
    ensure_default_runtime_files(project_root)
    python_path = ensure_venv(venv_dir)
    if not args.skip_install:
        install_requirements(project_root=project_root, python_path=python_path)
    return validate_runtime_files(project_root=project_root)


if __name__ == "__main__":
    raise SystemExit(main())
