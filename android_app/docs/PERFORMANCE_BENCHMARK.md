# Android P2 性能基线（Macrobenchmark）

已新增 `:benchmark` 模块，用于量化以下指标：

- 冷启动耗时（`StartupTimingMetric`）
- 主 Tab 切换帧耗时（`FrameTimingMetric`）
- Baseline Profile 采集（加速真实设备启动与关键路径）

## 1. 构建 benchmark APK

```powershell
cd D:\HuaweiAI\quantSystem2\android_app
.\gradlew.bat :benchmark:assembleBenchmark :benchmark:assembleAndroidTest
```

## 2. 在真机执行基准测试

```powershell
cd D:\HuaweiAI\quantSystem2\android_app
.\gradlew.bat :benchmark:connectedBenchmarkAndroidTest
```

## 3. 结果查看

- Android Studio `Run` 窗口
- `android_app\benchmark\build\outputs\connected_android_test_additional_output\`

建议每次发布前至少对同一台真机跑 3 轮，记录中位数对比版本变化。
