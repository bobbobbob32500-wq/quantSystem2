#!/usr/bin/env python
"""Smoke-test the mobile API from the Android client's perspective."""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any


def fetch_json(base_url: str, path: str) -> Any:
    url = f"{base_url.rstrip('/')}{path}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test Android mobile API endpoints.")
    parser.add_argument("--base-url", required=True, help="Example: http://127.0.0.1:8000/")
    args = parser.parse_args()

    base_url = args.base_url
    checks: list[tuple[str, Any]] = []

    try:
        root = fetch_json(base_url, "/")
        assert_true("message" in root, "Root response missing `message`")
        checks.append(("root", root))

        health = fetch_json(base_url, "/api/health")
        assert_true(health.get("status") == "healthy", "Health status is not healthy")
        checks.append(("health", health))

        overview = fetch_json(base_url, "/api/dashboard/overview")
        assert_true(overview.get("success") is True, "Overview request failed")
        assert_true(isinstance(overview.get("data"), dict), "Overview data missing")
        checks.append(("overview", overview))

        action_records = fetch_json(base_url, "/api/action_records?limit=5")
        assert_true(action_records.get("success") is True, "Action records request failed")
        assert_true(isinstance(action_records.get("data"), list), "Action records data missing")
        checks.append(("action_records", action_records))

        update = fetch_json(base_url, "/api/app_update/android/latest")
        assert_true(update.get("success") is True, "Update endpoint failed")
        assert_true(isinstance(update.get("data"), dict), "Update payload missing")
        checks.append(("app_update", update))
    except (AssertionError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"[FAIL] {exc}")
        return 1

    print("[PASS] Android mobile API smoke test succeeded.")
    for name, payload in checks:
        if name == "overview":
            meta = payload.get("data", {}).get("meta", {})
            print(f"- {name}: generated_label={meta.get('generated_label', '--')}")
        elif name == "action_records":
            print(f"- {name}: count={len(payload.get('data', []))}")
        else:
            print(f"- {name}: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
