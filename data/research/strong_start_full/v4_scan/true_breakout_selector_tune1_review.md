# true_breakout_selector_tune1 review

## Decision
Recommend **tune1**.

## Why
- Candidate A share: 0.2232 -> 0.2247
- Top20 A share: 0.2296 -> 0.2285
- Monotonic top enrichment kept: True -> True
- A coverage: 0.2098 -> 0.1748
- C coverage: 0.0941 -> 0.0777
- Candidate pool health: balanced -> balanced

## 4 key questions
1. Threshold Top30 -> Top20/25?
- Prefer **Top25** now: purity improves with manageable coverage loss.

2. Platform axis keep or reduce?
- Keep but reduce to auxiliary (0.02): still present, less dominant.

3. Chip axis strengthen?
- Slight strengthen is justified (0.23), not aggressive.

4. Industry axis impact?
- Keep unchanged in tune1 for stability; still important for purity.

## Recommendation
Adopt tune1 as the single next version for selector-only iteration.
