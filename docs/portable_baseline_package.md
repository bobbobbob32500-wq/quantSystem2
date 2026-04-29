# 可迁移基线包说明

这份文档对应的是“把当前后端系统和 Android 发布物完整备份，并在另一台环境恢复运行”的流程。

## 目标

迁移后，新环境至少具备下面三部分：

1. 当前仓库代码
2. 当前运行数据快照
3. 当前 Android 发布物与版本元数据

---

## 一、建议的基线组成

代码基线：

- Git 分支：`codex/system-baseline-20260429`

运行数据基线：

- `data/database/quant_system.db`
- `data/history_recommendation.db`
- `data/cache/candidate_pool.json`

可选运行态文件：

- `data/cache/virtual_trades.json`
- `data/cache/web_background_tasks.json`
- `data/cache/monitor_session.json`

Android 发布基线：

- `data/releases/android-latest.json`
- `data/releases/android-latest.apk`

---

## 二、在当前环境导出

### 1. 导出运行数据包

```bash
python scripts/export_portable_baseline.py --include-optional
```

导出结果默认位于：

```text
artifacts/portable_baseline/
```

压缩包里会包含：

- 必需运行数据文件
- 当前存在的可选缓存与 Android 发布文件
- `manifest.json`（文件清单、大小、SHA256、缺失项）

如果脚本提示 `missing_required`，说明当前环境自身就不完整，迁移前需要先补齐。

### 2. 备份代码

将当前分支推送到 GitHub，作为代码基线。

---

## 三、在新环境恢复

### 1. 获取代码

```bash
git clone <your-repo-url>
cd quantSystem2
git checkout codex/system-baseline-20260429
```

### 2. 恢复运行数据

```bash
python scripts/restore_portable_baseline.py /path/to/portable_baseline_xxx.zip --target-root .
```

如需覆盖已有文件：

```bash
python scripts/restore_portable_baseline.py /path/to/portable_baseline_xxx.zip --target-root . --overwrite
```

### 3. 初始化 Python 环境

```bash
python scripts/bootstrap_portable_env.py
```

如果你已经准备好了虚拟环境，只想做目录初始化与文件检查：

```bash
python scripts/bootstrap_portable_env.py --skip-install
```

---

## 四、启动方式

### 一键启动后端栈

```bash
python scripts/start_portable_stack.py
```

默认启动：

- 后台服务：`run_service.py`
- Web 看板：`http://0.0.0.0:8501`
- 移动 API：`http://0.0.0.0:8000`

日志输出到：

```text
logs/portable/
```

### 只启动 Dashboard + API

```bash
python scripts/start_portable_stack.py --skip-service
```

### 自定义端口

```bash
python scripts/start_portable_stack.py --dashboard-port 8502 --api-port 8001
```

---

## 五、Android App 迁移说明

Android 默认后端地址不再只能写死在代码里。现在支持：

1. Gradle 属性 `DEFAULT_API_BASE_URL`
2. 环境变量 `QUANT_DEFAULT_API_BASE_URL`
3. 兜底默认值 `http://101.133.149.141/`

打包新环境版本示例：

```bash
./gradlew :app:assembleRelease -PDEFAULT_API_BASE_URL=http://<new-host>/
```

Windows PowerShell 示例：

```powershell
$env:QUANT_DEFAULT_API_BASE_URL="http://<new-host>/"
.\gradlew.bat :app:assembleRelease
```

注意：如果用户已经在 App 设置页手动保存过地址，本地保存值仍然优先生效。

---

## 六、已知边界

1. 这套基线包解决的是“代码 + 当前运行数据 + Android 发布物”的迁移；仓库内已提供 `deploy/supervisor/` 与 `deploy/systemd/` 模板，但你仍需要按目标机器路径做一次落地配置。
2. 如果新环境网络策略不同，实时行情源可用性仍可能变化。
3. 导出脚本默认不包含 `data/intraday_cache/` 全量缓存；如有需要，可以后续扩展到单独归档。

---

## 七、推荐迁移顺序

1. 在旧环境执行 `export_portable_baseline.py`
2. 把代码分支和 zip 包一起保存
3. 新机器拉代码
4. 恢复 zip 包
5. 运行 `bootstrap_portable_env.py`
6. 运行 `start_portable_stack.py`
7. 用新的 API 地址重新打 Android 包或在 App 设置页修改地址

---

## 八、守护进程模板

仓库内已提供两套托管模板：

- `deploy/supervisor/quant-portable.conf`
- `deploy/systemd/quant-portable-service.service`
- `deploy/systemd/quant-portable-dashboard.service`
- `deploy/systemd/quant-portable-api.service`

默认假设项目部署在：

```text
/opt/quant-system
```

如果你的目录不同，请先把模板中的路径替换成实际路径。

### Supervisor 示例

```bash
mkdir -p /opt/quant-system/logs/supervisor
cp deploy/supervisor/quant-portable.conf /etc/supervisor/conf.d/quant-portable.conf
supervisorctl reread
supervisorctl update
supervisorctl status
```

### systemd 示例

```bash
cp deploy/systemd/quant-portable-*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now quant-portable-service
systemctl enable --now quant-portable-dashboard
systemctl enable --now quant-portable-api
systemctl status quant-portable-api
```
