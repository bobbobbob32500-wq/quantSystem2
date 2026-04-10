# 弱网/断网恢复专项回归（P2）

已提供自动化脚本：

- [network_resilience_regression.ps1](/D:/HuaweiAI/quantSystem2/android_app/scripts/network_resilience_regression.ps1)

## 使用方法

```powershell
cd D:\HuaweiAI\quantSystem2\android_app
powershell -ExecutionPolicy Bypass -File .\scripts\network_resilience_regression.ps1
```

若要在网络切换后附带执行 Android UI 自动化测试：

```powershell
cd D:\HuaweiAI\quantSystem2\android_app
powershell -ExecutionPolicy Bypass -File .\scripts\network_resilience_regression.ps1 -RunConnectedTests
```

## 脚本覆盖场景

1. 仅移动数据（关闭 Wi-Fi）
2. 完全断网（关闭 Wi-Fi + 数据）
3. 弱网恢复（先开数据后开 Wi-Fi）

## 期望结果

- 断网时页面出现可读错误与重试入口；
- 有缓存时可回退到本地缓存并保持可用；
- 网络恢复后可重新拉取实时数据；
- 首页“网络状态”文案能反映正常/较慢/异常状态。
