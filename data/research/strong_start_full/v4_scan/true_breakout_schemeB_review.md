# Scheme B Review

## Frozen dual-layer roles
- Main system: `v3.2_candidate`（唯一正式出票基础，决定能否进入核心候选池）。
- Enhancement tag: `v3.1_relaxed`（仅在已入 v3.2 主池样本上加优先级标签，不能单独出票）。
- Why 3.2 is main: 跨窗口稳定性更好、样本规模更可用。
- Why 3.1 is tag-only: 主窗强但留出波动较大，更适合作为“超强提示层”。
- Why 3.1 cannot be standalone: 易放大样本内效应，削弱主池稳定性。

## main
- core_pool: n=101, Ahigh=10.89%, C=40.59%, G=24.75%; win_t2=52.48%, mean_ret_t2=0.0062, median_ret_t2=0.0025
- priority_tag_1: n=7, Ahigh=42.86%, C=42.86%, G=0.00%; win_t2=57.14%, mean_ret_t2=0.0149, median_ret_t2=0.0183
- priority_tag_0: n=94, Ahigh=8.51%, C=40.43%, G=26.60%; win_t2=52.13%, mean_ret_t2=0.0055, median_ret_t2=0.0018

## confirm
- core_pool: n=109, Ahigh=11.93%, C=35.78%, G=33.94%; win_t2=56.88%, mean_ret_t2=0.0125, median_ret_t2=0.0062
- priority_tag_1: n=7, Ahigh=28.57%, C=42.86%, G=14.29%; win_t2=57.14%, mean_ret_t2=0.0284, median_ret_t2=0.0218
- priority_tag_0: n=102, Ahigh=10.78%, C=35.29%, G=35.29%; win_t2=56.86%, mean_ret_t2=0.0114, median_ret_t2=0.0062

## all
- core_pool: n=210, Ahigh=11.43%, C=38.10%, G=29.52%; win_t2=54.76%, mean_ret_t2=0.0094, median_ret_t2=0.0037
- priority_tag_1: n=14, Ahigh=35.71%, C=42.86%, G=7.14%; win_t2=57.14%, mean_ret_t2=0.0216, median_ret_t2=0.0201
- priority_tag_0: n=196, Ahigh=9.69%, C=37.76%, G=31.12%; win_t2=54.59%, mean_ret_t2=0.0086, median_ret_t2=0.0033
