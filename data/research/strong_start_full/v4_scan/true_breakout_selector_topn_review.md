# true_breakout_selector_topn_review

## Win definitions
- primary: win_t2 (T+2 close > buy_open_t1)
- secondary: win_t1 (T+1 close > buy_open_t1)

## TopN compare
   group   n  avg_ret_t1  med_ret_t1   win_t1  avg_ret_t2  med_ret_t2   win_t2
    top1 118    0.006509    0.000649 0.500000    0.008306   -0.002126 0.491525
    top2 236    0.005272   -0.002081 0.474576    0.011665    0.000618 0.500000
    top3 354    0.003612   -0.003295 0.466102    0.005968   -0.003389 0.463277
    top5 590    0.001781   -0.004215 0.452542    0.002142   -0.005519 0.442373
rank6_10 571   -0.000130   -0.005155 0.437828   -0.002738   -0.007031 0.437828

## Top3 vs Top4~5
 group   n  avg_ret_t1  med_ret_t1   win_t1  avg_ret_t2  med_ret_t2   win_t2
top1_3 354    0.003612   -0.003295 0.466102    0.005968   -0.003389 0.463277
top4_5 236   -0.000965   -0.007524 0.432203   -0.003597   -0.008346 0.411017

## Stability
- days(top5 avg t1 > 0): 64/118
- days(top5 win t1 > 50%): 50/118
- days(top5 avg t1 > rank6_10): 58/118

## Answers
- best group by win_t2: top2
- best group by win_t1: top1
- top5 better than rank6_10 on t2 avg: True
- top1_3 better than top4_5 on t2 avg: True