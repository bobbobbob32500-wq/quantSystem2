from __future__ import annotations

from pathlib import Path


def test_main_screen_navigation_labels_not_mojibake() -> None:
    project_root = Path(__file__).resolve().parents[1]
    main_screen = (
        project_root
        / "android_app"
        / "app"
        / "src"
        / "main"
        / "java"
        / "com"
        / "quant"
        / "system"
        / "ui"
        / "screen"
        / "MainScreen.kt"
    )

    content = main_screen.read_text(encoding="utf-8")

    expected_labels = [
        '"总览"',
        '"候选池"',
        '"信号"',
        '"持仓"',
        'Actions("动作中心")',
        'History("执行历史")',
        'Settings("设置")',
        'Strategy("策略中心")',
        'Analytics("复盘统计")',
        'NotificationLogs("通知日志")',
    ]
    for label in expected_labels:
        assert label in content

    # Guard against known mojibake fragments seen in previous regressions.
    bad_fragments = [
        "鎬昏",
        "鍊欓€夋睜",
        "淇″彿",
        "鎸佷粨",
        "鎿嶄綔涓績",
        "鎵ц鍘嗗彶",
        "澶嶇洏缁熻",
        "鏃犳硶鎵撳紑",
        "锘縫ackage",
    ]
    for fragment in bad_fragments:
        assert fragment not in content
