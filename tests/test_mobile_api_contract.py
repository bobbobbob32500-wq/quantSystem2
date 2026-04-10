from __future__ import annotations

import re
from pathlib import Path


BACKEND_ROUTE_RE = re.compile(r'@app\.(get|post|put|delete)\("([^"]+)"\)')
ANDROID_ROUTE_RE = re.compile(r'@(GET|POST|PUT|DELETE)\("([^"]+)"\)')


def test_android_api_service_routes_exist_in_backend() -> None:
    project_root = Path(__file__).resolve().parents[1]
    app_py = project_root / "src" / "api" / "app.py"
    api_service = (
        project_root
        / "android_app"
        / "app"
        / "src"
        / "main"
        / "java"
        / "com"
        / "quant"
        / "system"
        / "data"
        / "api"
        / "ApiService.kt"
    )

    backend_routes = {
        (method.upper(), path)
        for method, path in BACKEND_ROUTE_RE.findall(app_py.read_text(encoding="utf-8"))
    }
    android_routes = {
        (method.upper(), path)
        for method, path in ANDROID_ROUTE_RE.findall(api_service.read_text(encoding="utf-8"))
    }

    missing = sorted(android_routes - backend_routes, key=lambda item: (item[1], item[0]))
    assert not missing, f"Android routes missing in backend: {missing}"
