# 二次启动策略日常信号接入完成报告

## 任务结论

本轮“将二次启动策略接入日常信号流程，并与原策略分开”的任务已完成。

当前状态：

- 已完成独立菜单接入
- 已完成日报独立展示
- 已完成自动推送独立发送
- 已完成独立落库与历史推荐库同步写入
- 已完成历史日期回放验证

## 本次最终验证结果

为避免使用“无候选日期”误判落库失败，本次先用全历史信号生成方式确认当前 walk-forward 参数下的有效信号日。

确认结果：

- 全样本区间 `20250901 ~ 20260331` 共生成 `21` 条历史信号
- 最近一个可稳定复现的历史候选日为 `20260316`
- 该日 `get_daily_selection('20260316')` 返回 `1` 条候选
- 执行 `persist_daily_selection('20260316', rows)` 后返回 `1`

双库回查结果：

- 主库 `data/database/quant_system.db`
  - 表：`secondary_launch_selection_history`
  - 记录：`('20260316', '002730.SZ', 'secondary_launch_walkforward', 1)`
- 历史推荐库 `data/history_recommendation.db`
  - 表：`recommendations`
  - 记录：`('20260316', '002730.SZ', 'secondary_launch_walkforward', '二次启动策略候选 | RS20=0.221 | 回撤=4.81%')`

结论：

`get_daily_selection -> persist_daily_selection -> 主库落表 -> 历史推荐库同步写入`

整条链路验证通过。

## 问题复盘

之前“看起来没有落库”的根因不是写库逻辑异常，而是：

1. 选取的历史交易日并不一定存在候选
2. 当 `get_daily_selection(trade_date)` 返回空列表时，`persist_daily_selection` 会直接返回 `0`
3. 因而表面现象像“未写入”，实际是“无可写入数据”

这说明当前实现逻辑是正确的，问题主要在验证方法，而不是功能本身。

## 已完成的系统接入范围

### 1. 菜单入口

- 主菜单已新增 `17. 二次启动策略`
- 日常选股菜单已支持与原策略分开调用

### 2. 日报输出

- 日报中已增加“二次启动策略”独立板块
- 与原有主策略分开展示候选与参数信息

### 3. 自动推送

- 盘前推送已支持先推原策略，再单独推送二次启动策略结果
- 二次启动策略为空时不会影响原策略推送

### 4. 数据持久化

- 主库新增表：`secondary_launch_selection_history`
- 历史推荐库写入 `strategy_type='secondary_launch_walkforward'`
- 可与原策略历史记录分开追踪、评估、复盘

## 当前有效参数

基于 walk-forward 结果，当前已接入日常流程的参数为：

- `hold_days = 2`
- `drawdown_min = 0.03`
- `drawdown_max = 0.08`
- `vol_shrink_ratio = 0.60`
- `last_limit_up_days_min = 2`
- `last_limit_up_days_max = 4`
- `limit_up_count_10_min = 1`
- `limit_up_count_10_max = 1`
- `picks_per_day = 2`

## 本次新增辅助脚本

- `tools/verify_secondary_launch_persistence.py`

用途：

- 固化历史候选验证流程
- 一键验证双库写入是否正常
- 后续回归测试时可直接复用

## 风险提示

虽然“接入流程”和“落库链路”已经完成，但策略层面的实盘稳健性仍应继续观察：

- 旧版单次 OOS 报告曾显示稳健性不足
- 当前 walk-forward 结果明显改善，但样本量仍不算大
- 建议继续积累更多真实交易日信号，再做滚动复核

## 最终结论

本次任务的工程目标已经全部完成，且独立持久化链路已验证通过。

可以将二次启动策略作为一条独立的日常信号流程继续运行，并与原策略分开跟踪表现。
