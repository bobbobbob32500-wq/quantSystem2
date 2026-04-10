# S3 gate note
- gate type: score_total_floor
- rule: only when top1_score >= 0.85, output top2; otherwise output 0
- reason: reduce low-quality trading days with a single lightweight daily front-strength gate
- no feature expansion, no search, no framework rewrite