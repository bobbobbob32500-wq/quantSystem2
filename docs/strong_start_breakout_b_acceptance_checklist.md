# strong_start breakout-B acceptance checklist

Version: `breakout_b_freeze1`

## Mandatory checks
1. Three-state output stability  
- Pass criterion: `execution_state` contains only `ready/reject/risk`, with no null/other labels.

1b. Boolean consistency  
- Pass criterion: `execution_ready_flag=true` iff `execution_state=ready`; otherwise `false`.

2. Risk is controlled (not dominant)  
- Pass criterion: `risk` is materially smaller than `reject + ready` in sample verification.

3. No forced-ready inflation on ambiguous samples  
- Pass criterion: refined weak-confirmation rules reduce risk without large abnormal jump in ready.

4. No future-field leakage  
- Pass criterion: no forward return/performance fields in rule inputs or output contract.

5. Full contract completeness  
- Pass criterion: all required 12 fields exist and are populated per contract semantics.

6. Readable explainability  
- Pass criterion: `execution_reject_reason`, `execution_risk_tag`, and `key_reason_1/2/3` are understandable and consistent with final state.

## Evidence references (freeze basis)
- Pre-refine tri-state: `ready=25, reject=91, risk=8`
- Post-refine tri-state: `ready=27, reject=94, risk=3`
- Interpretation: risk reduced; no large forced-ready distortion.
