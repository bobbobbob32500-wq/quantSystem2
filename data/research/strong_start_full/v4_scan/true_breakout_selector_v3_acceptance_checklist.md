# true_breakout_selector_v3_acceptance_checklist

## Selector main-structure freeze checklist

1. Path A internal ranking effective  
- Pass standard: Path A top segment A-share >= Path A broader segment A-share.  
- Status: PASS.

2. Path B internal ranking effective  
- Pass standard: Path B top segment A-share >= Path B broader segment A-share.  
- Status: PASS.

3. `M1_quota_merge` outperforms S3/S4/S5 on A-share  
- Pass standard: `A_share(M1) > A_share(S3/S4/S5)` in frozen near-window test.  
- Status: PASS.

4. Candidate A-share above full-sample baseline  
- Pass standard: candidate A-share > `35.39%`.  
- Status: PASS (`41.63%`).

5. Path B is not silent  
- Pass standard: merged output has meaningful non-zero Path B contribution.  
- Status: PASS.

6. `industry_heat_C` / `trend_chase_C` are controlled better than naive merge  
- Pass standard: selected-rate of these modes is reduced in frozen mechanism vs naive merge.  
- Status: PASS.

7. Output boundary is clean  
- Pass standard: no entry/exit/execution/future/performance fields in selector contract.  
- Status: PASS.

## Freeze decision
- Decision: ACCEPT as `freeze_candidate_1` for parameter phase.
