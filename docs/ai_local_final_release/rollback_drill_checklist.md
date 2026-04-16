# AI本地最终版回滚演练清单

## 演练前
1. 确认已有最近一次验证报告：`reports/release/ai_local_final_validation_*.json`
2. 确认 smoke 用例可执行。
3. 确认当前分支与版本标识已记录。

## 演练执行
1. 运行：
```bash
python tools/run_ai_rollback_drill.py
```
2. 查看输出：
- `reports/release/ai_rollback_drill_*.md`
- `reports/release/ai_rollback_drill_*.json`

## 验收标准
1. `baseline_smoke` 通过。
2. `final_validation` 通过。
3. `rollback_anchor_exists` 为通过。

## 失败处理
1. 标记为“禁止上线”。
2. 按失败项修复后重跑演练。
3. 演练通过后再进入发布确认。

