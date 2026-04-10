# v3.2 Rule Embed Note

v3.2 embeds robust R2_R3 only (R1 removed):
- R2 robust band: NOT(industry_axis >= q60 AND chip_winner >= q65)
- R3 robust band: NOT(platform_axis <= q35 AND platform_compress >= q65)
Quantiles are computed on the selected-universe (main+confirm) T-day visible scores.