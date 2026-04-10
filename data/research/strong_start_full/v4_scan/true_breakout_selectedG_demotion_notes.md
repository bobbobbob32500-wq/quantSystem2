# true_breakout_selectedG_demotion_notes

## Position
- selected_G should default to observation pool, not core candidate pool.

## Rationale
- G contains uncertainty/mixed-path and buy-point-sensitive patterns; keeping them in core pool dilutes A_high purity.

## Suggested handling
1. Default demote all G to observe pool.
2. Keep tracking subtypes: grey_uncertain / path_mixed_unclear / buypoint_sensitive_recovery / early_spike_fade.
3. Only reconsider promotion after dedicated objective/label redesign; do not mix into current core selector target.

## Current reason breakdown
          selected_g_reason  sample_n  share_in_selected_G  mean_ret_t2   win_t2
             grey_uncertain      19.0             0.431818     0.023508 0.631579
         path_mixed_unclear      16.0             0.363636     0.001145 0.562500
buypoint_sensitive_recovery       4.0             0.090909     0.026505 1.000000
           early_spike_fade       3.0             0.068182    -0.020334 0.000000
          weak_continuation       2.0             0.045455     0.000310 0.500000