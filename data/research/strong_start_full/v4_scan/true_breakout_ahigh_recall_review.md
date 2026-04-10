# A_high 全量召回审计

- A_high 总样本数: 24
- core_pool 召回率: 100.00%
- priority_tag=1 召回率: 20.83%
- strict_pool 召回率: 20.83%
- F3 召回率: 20.83%

## 最大漏抓源头
- not_in_path_A 占 A_high 比例: 70.83%

## 召回优先 candidate 方向（仅方向，不落地）
1. 先提升 Path A 覆盖：当前主漏抓在 path 分流前，优先修复 A_high 到 Path A 的召回。
2. 在 priority_tag 前增加 A_high 召回友好分层：降低对 path A 里中等强度 A_high 的早期漏失。
3. F3 保持高纯定位不动，把“召回扩容”放在 F3 之前的层级完成。

## 推进判断
- 当前主线必须改成召回优先（先抓到，再纯化）。
- 当前不应继续买点开发，先重建高召回强启动主线。