#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Publish Android APK metadata for in-app update endpoint."""
from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


def parse_gradle_version(gradle_file: Path) -> tuple[Optional[int], Optional[str]]:
    if not gradle_file.exists():
        return None, None
    content = gradle_file.read_text(encoding="utf-8")
    code_match = re.search(r"\bversionCode\s*=\s*(\d+)", content)
    name_match = re.search(r'versionName\s*=\s*"([^"]+)"', content)
    version_code = int(code_match.group(1)) if code_match else None
    version_name = name_match.group(1).strip() if name_match else None
    return version_code, version_name


def load_existing_meta(meta_file: Path) -> Dict[str, Any]:
    if not meta_file.exists():
        return {}
    try:
        return json.loads(meta_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def resolve_version_code(
    user_value: Optional[int],
    existing_meta: Dict[str, Any],
    gradle_code: Optional[int],
) -> int:
    if user_value is not None:
        return int(user_value)

    existing = existing_meta.get("latest_version_code")
    if existing is None:
        existing = existing_meta.get("version_code")
    if existing is not None:
        try:
            return int(existing) + 1
        except Exception:
            pass

    if gradle_code is not None:
        return gradle_code

    return 1


def resolve_version_name(
    user_value: Optional[str],
    gradle_name: Optional[str],
    version_code: int,
) -> str:
    if user_value:
        return user_value.strip()
    if gradle_name:
        return f"{gradle_name}.{version_code}"
    now = datetime.now().strftime("%Y.%m.%d.%H%M")
    return f"dev-{now}"


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Publish APK for Android in-app update endpoint.",
    )
    parser.add_argument(
        "--apk",
        required=True,
        help="Source APK file path.",
    )
    parser.add_argument(
        "--out-dir",
        default=str(project_root / "data" / "releases"),
        help="Release directory. Default: data/releases",
    )
    parser.add_argument(
        "--version-code",
        type=int,
        help="Latest version code. If omitted, auto-increment from existing metadata.",
    )
    parser.add_argument(
        "--version-name",
        help="Latest version name.",
    )
    parser.add_argument(
        "--changelog",
        default="常规更新与稳定性优化",
        help="Changelog text shown in app.",
    )
    parser.add_argument(
        "--apk-url",
        default="",
        help="Public APK URL (optional). If empty, server auto-generates download URL.",
    )
    parser.add_argument(
        "--force-update",
        action="store_true",
        help="Whether this release is mandatory.",
    )
    args = parser.parse_args()

    apk_source = Path(args.apk).expanduser().resolve()
    if not apk_source.exists():
        raise FileNotFoundError(f"APK not found: {apk_source}")

    release_dir = Path(args.out_dir).expanduser().resolve()
    release_dir.mkdir(parents=True, exist_ok=True)
    apk_target = release_dir / "android-latest.apk"
    meta_target = release_dir / "android-latest.json"

    existing_meta = load_existing_meta(meta_target)
    gradle_file = project_root / "android_app" / "app" / "build.gradle.kts"
    gradle_code, gradle_name = parse_gradle_version(gradle_file)

    version_code = resolve_version_code(args.version_code, existing_meta, gradle_code)
    version_name = resolve_version_name(args.version_name, gradle_name, version_code)

    shutil.copy2(apk_source, apk_target)

    payload: Dict[str, Any] = {
        "latest_version_code": version_code,
        "latest_version_name": version_name,
        "changelog": args.changelog.strip(),
        "force_update": bool(args.force_update),
        "published_at": datetime.now().isoformat(timespec="seconds"),
    }
    if args.apk_url.strip():
        payload["apk_url"] = args.apk_url.strip()

    meta_target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("Android release published.")
    print(f"- APK:  {apk_target}")
    print(f"- META: {meta_target}")
    print(f"- latest_version_code: {version_code}")
    print(f"- latest_version_name: {version_name}")
    print("- Next: restart backend if needed, then use /api/app_update/android/latest to verify.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
