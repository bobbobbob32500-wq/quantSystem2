# AI本地最终版交付包

本目录用于“重大升级后 AI 功能本地最终版本确定”。

## 文件说明
- `AI_LOCAL_FINAL_RELEASE_PLAN.md`：五阶段执行方案与门禁。
- `requirements_baseline.md`：需求梳理与确认基线模板。
- `release_note_template.md`：最终版本说明模板。
- `test_report_template.md`：测试报告模板。
- `deploy_guide_template.md`：部署指南模板。
- `ai_feature_maturity_matrix.md`：AI功能稳定性分级（Stable/Beta/Experimental）。
- `rollback_drill_checklist.md`：回滚演练清单。

## 一键验证
```bash
python tools/run_ai_local_final_validation.py
```

验证配置见：`config/ai_local_final_validation.yaml`  
报告输出到：`reports/release/`

## 运营与发布门禁
```bash
python tools/generate_ai_slo_daily_report.py --days 7
python tools/run_real_llm_smoke_gate.py
python tools/run_ai_rollback_drill.py
```
