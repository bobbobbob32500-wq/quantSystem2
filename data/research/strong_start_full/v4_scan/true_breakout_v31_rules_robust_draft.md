# v3.1 Rules Robust Draft

## keep
- R2_R3
- R3
- BASELINE

## candidate_keep
- R1_R2
- R1_R2_R3
- R2

## drop
- R1
- R1_R3

## threshold robustness candidates
- R1_conservative [drop]: score_total>=q55 & score_platform_axis_single>=q45 (main A/C=0.286, confirm A/C=0.167)
- R1_relaxed [drop]: score_total>=q50(~q55 proxied by q45) & score_platform_axis_single>=q40 (main A/C=0.250, confirm A/C=0.250)
- R3_relaxed [drop]: NOT(platform<=q35 & compress>=q65) (main A/C=0.250, confirm A/C=0.295)
- R3_conservative [drop]: NOT(platform<=q45 & compress>=q60) (main A/C=0.237, confirm A/C=0.262)
- R2_relaxed [keep]: NOT(industry>=q70 & chip>=q75) (main A/C=0.305, confirm A/C=0.262)
- R2_conservative [keep]: NOT(industry>=q60 & chip>=q65) (main A/C=0.304, confirm A/C=0.286)