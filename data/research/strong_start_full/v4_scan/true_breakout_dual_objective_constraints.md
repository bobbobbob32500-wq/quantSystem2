# Dual Objective Constraints (Production-Oriented)

Current phase requires both quality floor and frequency floor.

## Quality Floor
- Ahigh/C ratio >= 1.5
- A_low + C share <= 45%
- T+2 win rate floor:
  - all window >= 60%
  - main/confirm window >= 55%

## Frequency Floor
- signal-day ratio floor:
  - all window >= 10%
  - main/confirm window >= 8%
- avg days per signal ceiling:
  - all window <= 10 days
  - main/confirm window <= 12 days

## Why this floor is realistic now
- Current Path A sample is sparse (17 events total in eval window).
- A too-tight floor would force empty output and block production progression.