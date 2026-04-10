# true_breakout_selector_v2_2_trend_fix_note

1) Single-core trend axis with cap: keep rs20 quantile only as core to stop momentum over-amplification.
2) Remove three misleading trend atoms from main sort: ret60 / vs_index20 / close_ma60_gap.
3) Keep remaining trend atoms only as weak auxiliary (10% total contribution).