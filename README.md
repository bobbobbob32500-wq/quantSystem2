# A 股量化交易辅助系统

面向 A 股沪深主板、小资金、短线 3-5 天场景的半自动交易辅助系统。系统的定位不是自动下单，而是：

- 盘前做候选池筛选
- 盘中监控买卖点
- 推送可信信号给用户
- 用虚拟交易、反馈闭环和参数优化持续迭代策略

---

## 当前核心能力

- 盘前选股
- 盘中买卖点监控
- 企业微信信号推送
- 虚拟交易跟踪
- 盘后反馈闭环
- 运行健康监控
- Web 可视化看板

---

## 可视化看板

当前看板已经升级为新版 Web 架构：

```text
Flask + Jinja + 原生 JavaScript + ECharts
```

不再使用旧版 Streamlit 页面。

### 启动

```bash
python start_dashboard.py
```

或：

```bash
start_dashboard.bat
```

### 地址

```text
http://127.0.0.1:8501
```

### 相关文档

- [可视化看板使用指南](./docs/dashboard_user_guide.md)
- [可视化看板设计方案](./docs/dashboard_design_proposal.md)
- [系统日常操作清单](./docs/daily_operation_sop.md)

---

## 主系统启动

命令行主入口：

```bash
python main.py
```

后台服务入口：

```bash
python run_service.py
```

---

## 数据位置

主要真实数据文件：

- `data/database/quant_system.db`
- `data/history_recommendation.db`
- `data/cache/candidate_pool.json`
- `data/cache/virtual_trades.json`

---

## 目录说明

### 核心入口

- `main.py`
- `run_service.py`
- `dashboard.py`

### 核心模块

- `src/modules/stock_selector.py`
- `src/modules/enhanced_hybrid_system.py`
- `src/modules/optimized_buy_signals.py`
- `src/modules/virtual_trade_tracker.py`
- `src/modules/signal_feedback_evaluator.py`

### 看板相关

- `src/services/dashboard_service.py`
- `web/templates/dashboard.html`
- `web/static/css/dashboard.css`
- `web/static/js/dashboard.js`

---

## 依赖安装

```bash
pip install -r requirements.txt
```

---

## 说明

本系统用于交易决策辅助，不构成自动化投资承诺或收益保证。最终买卖决策仍应由用户自行确认并承担风险。
