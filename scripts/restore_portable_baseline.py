from __future__ import annotations

import argparse
import json
from pathlib import Path
from zipfile import ZipFile


def restore_bundle(bundle_path: Path, target_root: Path, overwrite: bool) -> int:
    if not bundle_path.is_file():
        raise FileNotFoundError(f"未找到基线包: {bundle_path}")

    target_root.mkdir(parents=True, exist_ok=True)

    with ZipFile(bundle_path, "r") as archive:
        members = [name for name in archive.namelist() if not name.endswith("/")]
        manifest = None
        if "manifest.json" in members:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))

        restored = 0
        skipped = 0
        for member in members:
            if member == "manifest.json":
                continue
            destination = target_root / member
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() and not overwrite:
                skipped += 1
                continue
            with archive.open(member) as src, destination.open("wb") as dst:
                dst.write(src.read())
            restored += 1

    print(f"恢复完成: {target_root}")
    print(f"已写入文件: {restored}")
    print(f"跳过文件: {skipped}")
    if manifest:
        missing_required = manifest.get("missing_required") or []
        if missing_required:
            print("注意: 导出时存在缺失必需文件，请补齐后再启动系统:")
            for item in missing_required:
                print(f"  - {item}")
            return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="恢复可迁移基线包到目标目录")
    parser.add_argument("bundle", type=Path, help="导出的 portable baseline zip 文件")
    parser.add_argument(
        "--target-root",
        type=Path,
        default=Path.cwd(),
        help="要恢复到的项目根目录，默认当前目录",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="覆盖目标目录中已有的同名文件",
    )
    args = parser.parse_args()
    return restore_bundle(
        bundle_path=args.bundle.resolve(),
        target_root=args.target_root.resolve(),
        overwrite=args.overwrite,
    )


if __name__ == "__main__":
    raise SystemExit(main())
