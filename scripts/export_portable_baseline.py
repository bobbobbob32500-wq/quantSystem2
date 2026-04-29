from __future__ import annotations

import argparse
import hashlib
import json
import socket
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "artifacts" / "portable_baseline"
DEFAULT_REQUIRED_ITEMS = (
    "data/database/quant_system.db",
    "data/history_recommendation.db",
    "data/cache/candidate_pool.json",
)
DEFAULT_OPTIONAL_ITEMS = (
    "data/cache/virtual_trades.json",
    "data/cache/web_background_tasks.json",
    "data/cache/monitor_session.json",
    "data/releases/android-latest.json",
    "data/releases/android-latest.apk",
)
OPTIONAL_PATTERNS = (
    "data/cache/*.json",
    "data/releases/*",
)


@dataclass(frozen=True)
class ExportItem:
    relative_path: str
    required: bool = False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_paths(include_optional: bool) -> tuple[list[ExportItem], list[str]]:
    items = [ExportItem(path, required=True) for path in DEFAULT_REQUIRED_ITEMS]
    items.extend(ExportItem(path, required=False) for path in DEFAULT_OPTIONAL_ITEMS)
    optional_paths: list[str] = []
    if include_optional:
        seen = {item.relative_path for item in items}
        for pattern in OPTIONAL_PATTERNS:
            for candidate in sorted(PROJECT_ROOT.glob(pattern)):
                if not candidate.is_file():
                    continue
                relative = candidate.relative_to(PROJECT_ROOT).as_posix()
                if relative in seen:
                    continue
                seen.add(relative)
                items.append(ExportItem(relative, required=False))
        optional_paths = list(OPTIONAL_PATTERNS)
    return items, optional_paths


def export_bundle(output_path: Path, include_optional: bool) -> int:
    export_items, optional_patterns = _iter_paths(include_optional=include_optional)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, object] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hostname": socket.gethostname(),
        "python_version": sys.version,
        "project_root": str(PROJECT_ROOT),
        "optional_patterns": optional_patterns,
        "files": [],
        "missing_required": [],
        "missing_optional": [],
    }

    files_added = 0
    with ZipFile(output_path, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for item in export_items:
            source = PROJECT_ROOT / item.relative_path
            if not source.exists():
                bucket = "missing_required" if item.required else "missing_optional"
                cast_list = manifest[bucket]
                assert isinstance(cast_list, list)
                cast_list.append(item.relative_path)
                continue

            archive.write(source, arcname=item.relative_path)
            files_entry = manifest["files"]
            assert isinstance(files_entry, list)
            files_entry.append(
                {
                    "path": item.relative_path,
                    "size_bytes": source.stat().st_size,
                    "sha256": _sha256(source),
                    "required": item.required,
                }
            )
            files_added += 1

        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    missing_required = manifest["missing_required"]
    assert isinstance(missing_required, list)
    print(f"导出完成: {output_path}")
    print(f"已打包文件: {files_added}")
    if missing_required:
        print("缺失必需文件:")
        for item in missing_required:
            print(f"  - {item}")
        return 1

    missing_optional = manifest["missing_optional"]
    assert isinstance(missing_optional, list)
    if missing_optional:
        print("缺失可选文件:")
        for item in missing_optional:
            print(f"  - {item}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="导出可迁移基线包所需运行数据")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR / f"portable_baseline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
        help="输出 zip 文件路径",
    )
    parser.add_argument(
        "--include-optional",
        action="store_true",
        help="额外打包 data/cache 与 data/releases 下的其他文件",
    )
    args = parser.parse_args()
    return export_bundle(output_path=args.output.resolve(), include_optional=args.include_optional)


if __name__ == "__main__":
    raise SystemExit(main())
