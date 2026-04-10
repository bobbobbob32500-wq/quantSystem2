# true_breakout_selector_v3_return_review

## Fixed scope
- selector: true_breakout_selector_v3_freeze_candidate_2
- params: quota=1:2, heat-cap=high, pathA=Top10%, pathB=Top20%
- entry: T+1 open; horizons: T+1/T+2/T+3 close

## Main window
- 20251230 ~ 20260330
- sample_n: 167
- mean_ret: t1=0.005348, t2=0.004228, t3=0.004556
- median_ret: t1=0.003301, t2=0.000000, t3=0.000244
- win_rate: t1=0.5509, t2=0.4910, t3=0.5030

## Confirm window
- 20250929 ~ 20251229
- sample_n: 172
- mean_ret: t1=0.005182, t2=0.011119, t3=0.008514
- median_ret: t1=0.000241, t2=0.006955, t3=0.002757
- win_rate: t1=0.5000, t2=0.5698, t3=0.5174

## By path
 sample_n  mean_ret_t1  mean_ret_t2  mean_ret_t3  median_ret_t1  median_ret_t2  median_ret_t3   win_t1   win_t2   win_t3  window group
       55     0.006419     0.006586     0.011933       0.004206      -0.001707      -0.002674 0.581818 0.454545 0.472727    main     A
      112     0.004823     0.003070     0.000933       0.002825       0.000919       0.001236 0.535714 0.508929 0.517857    main     B
       56     0.007335     0.013878     0.014209      -0.003169       0.005801       0.001424 0.464286 0.553571 0.517857 confirm     A
      116     0.004143     0.009787     0.005764       0.001323       0.008237       0.003965 0.517241 0.577586 0.517241 confirm     B

## By global rank bucket
 sample_n  mean_ret_t1  mean_ret_t2  mean_ret_t3  median_ret_t1  median_ret_t2  median_ret_t3   win_t1   win_t2   win_t3  window group
       60     0.006785     0.010369     0.009903      -0.003169       0.005801       0.000135 0.466667 0.550000 0.500000 confirm  top1
      120     0.005522     0.010928     0.007910       0.000000       0.010217       0.002757 0.491667 0.583333 0.525000 confirm  top2
      172     0.005182     0.011119     0.008514       0.000241       0.006955       0.002757 0.500000 0.569767 0.517442 confirm  top3
      172     0.005182     0.011119     0.008514       0.000241       0.006955       0.002757 0.500000 0.569767 0.517442 confirm  top5
       57     0.003110    -0.000168     0.005726       0.002732      -0.001985      -0.006485 0.543860 0.421053 0.438596    main  top1
      114     0.003845     0.002757     0.006037       0.002356      -0.001320       0.003513 0.535088 0.482456 0.517544    main  top2
      167     0.005348     0.004228     0.004556       0.003301       0.000000       0.000244 0.550898 0.491018 0.502994    main  top3
      167     0.005348     0.004228     0.004556       0.003301       0.000000       0.000244 0.550898 0.491018 0.502994    main  top5

## Main window best horizon: T+1