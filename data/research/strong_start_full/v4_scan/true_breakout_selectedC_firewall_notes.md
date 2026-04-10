# true_breakout_selectedC_firewall_notes

## Target C modes
- mixed_pseudo_C
- platform_false_break_C
- industry_heat_C

## Lightweight firewall directions (T-day only)
1. Heat resonance cap: when trend-axis and industry-axis are both extreme, cap incremental score instead of linear stacking.
2. Platform integrity guard: for weak-platform signatures (false-break profile), require minimum platform-compress quality before entering core pool.
3. Mixed-C dampener: when trend/industry are high but chip/platform quality are non-confirming, route to observe pool instead of core candidate.

## Why
- selected_C is dominated by mixed + platform-false-break + industry-heat modes, and these modes have weak/negative T+2 behavior.

## Current reason breakdown
     selected_c_reason  sample_n  share_in_selected_C  mean_ret_t2   win_t2  median_trend_axis  median_industry_axis  median_platform_axis  median_chip_axis
        mixed_pseudo_C      48.0             0.676056    -0.024343 0.187500           0.765934              0.532207              0.672375          0.741112
platform_false_break_C      10.0             0.140845    -0.047669 0.200000           0.904203              0.619910              0.241514          0.797917
       industry_heat_C       7.0             0.098592    -0.051323 0.142857           0.903918              0.821698              0.209222          0.844211
         trend_chase_C       4.0             0.056338    -0.031552 0.250000           0.880536              0.722744              0.253921          0.606109
     chip_distortion_C       2.0             0.028169    -0.002434 0.500000           0.884982              0.153487              0.581913          0.658754