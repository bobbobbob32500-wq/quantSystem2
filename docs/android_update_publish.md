# Android 无线更新发布（个人开发）

## 1. 一键构建并发布

在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\publish_android_release.ps1 `
  -Variant debug `
  -Changelog "修复若干问题，优化体验" `
  -ApkUrl "https://你的-ngrok-域名.ngrok-free.dev/api/app_update/android/download"
```

脚本会自动：

1. 编译 APK（debug 或 release）
2. 复制到 `data/releases/android-latest.apk`
3. 生成 `data/releases/android-latest.json`

## 2. 手动发布（可选）

```powershell
python .\scripts\publish_android_release.py `
  --apk .\android_app\app\build\outputs\apk\debug\app-debug.apk `
  --changelog "修复若干问题，优化体验" `
  --apk-url "https://你的-ngrok-域名.ngrok-free.dev/api/app_update/android/download"
```

## 3. 版本号建议

- 默认会从已有 `android-latest.json` 自动把 `latest_version_code` +1
- 也可手动指定：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\publish_android_release.ps1 `
  -Variant debug `
  -VersionCode 8 `
  -VersionName "1.0.8" `
  -Changelog "新增执行记录页"
```

## 4. 校验更新接口

后端运行后访问：

- `/api/app_update/android/latest`
- `/api/app_update/android/download`

示例（本机）：

```powershell
Invoke-WebRequest http://127.0.0.1:8000/api/app_update/android/latest | Select-Object -Expand Content
```
