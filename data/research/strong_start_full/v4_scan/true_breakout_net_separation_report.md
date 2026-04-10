# A_high 净分离规则草案

## 结论
- 在当前 core_pool（core_keep=True）中，A_high/C 从 `8/31` (`0.2581`) 提升到 `7/1` (`7.0000`)。
- 说明净分离规则对“保 A_high / 杀 C”有明显提升。

## kept_C 高频组合（C模式）
- `C_pattern_1`: low_score + low_trend | C支持率=0.387, Ahigh支持率=0.000
- `C_pattern_2`: low_platform_score + high_platform_compress | C支持率=0.452, Ahigh支持率=0.125
- `C_pattern_4`: low_score + low_rs20 | C支持率=0.323, Ahigh支持率=0.000
- `C_pattern_3`: high_industry_heat + high_chip_heat | C支持率=0.290, Ahigh支持率=0.000
- `C_pattern_5`: low_trend + high_industry_heat | C支持率=0.387, Ahigh支持率=0.125

## kept_Ahigh 高频组合（A_high模式）
- `Ahigh_pattern_1`: high_score + good_platform_score | Ahigh支持率=0.875, C支持率=0.161
- `Ahigh_pattern_4`: high_score + non_overheated_industry | Ahigh支持率=0.750, C支持率=0.226
- `Ahigh_pattern_3`: good_platform_score + cool_industry | Ahigh支持率=0.625, C支持率=0.194
- `Ahigh_pattern_2`: not_overheated_industry + not_overcompressed_platform | Ahigh支持率=0.750, C支持率=0.355
- `Ahigh_pattern_5`: high_rs20 + good_platform_score | Ahigh支持率=0.625, C支持率=0.258

## 净分离规则（最多3条）
- `R1`: `score_total>=0.8377 AND score_platform_axis_single>=0.3080` 才允许进核心池。
- `R2`: `industry_heat × chip_heat` 共振（高行业热度+高筹码热度）直接限流。
- `R3`: `低平台评分 + 高压缩比` 视为假压缩结构，直接限流。

## 规则前后
- 规则前 A_high占比（在 A_high+C 中）：`20.51%`
- 规则后 A_high占比（在 A_high+C 中）：`87.50%`
- A_high通过率：`87.50%`；C保留率：`3.23%`

## 下一步建议
- 已具备进入 `v3.1 结构升级` 条件（先把这三条规则并入结构层，再做同窗复核）。