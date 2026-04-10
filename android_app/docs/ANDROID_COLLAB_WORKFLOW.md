# Android Collaboration Workflow

## Goal

Keep Android feature delivery as the main development track while ensuring backend capabilities are integrated completely and reliably.

## Daily Collaboration Rhythm

1. Backend updates `src/api/app.py` and communicates changed routes, payloads, and edge cases.
2. Android updates `ApiService.kt`, repository mapping, and UI usage in the same cycle.
3. Regenerate the contract doc:
   - `python scripts/generate_android_api_contract.py`
4. Run contract and smoke checks:
   - `pytest tests/test_mobile_api_contract.py`
   - `python scripts/test_android_mobile_api.py --base-url http://127.0.0.1:8000/`
5. Real-device testing uses the same base URL configured in the app settings.

## Team Responsibilities

- Backend team
  - Maintain route behavior, response stability, and error semantics.
  - Update changelog notes for Android-impacting API changes.
  - Provide mock/example payloads when adding new fields.

- Android team
  - Keep `ApiService.kt`, model mapping, and UI states aligned with backend changes.
  - Validate loading, empty, success, and error states for each integrated module.
  - Confirm mobile UX remains stable under weak network and update scenarios.

## Required Gates Before Merge

- Contract test passes.
- Mobile API smoke test passes.
- `assembleDebug` passes.
- If a UI flow changed, perform one real-device regression round on the affected screen.

## Current Focus

- Interface accuracy and stability
- Android-side implementation completeness
- Interaction speed, operational clarity, and visual polish
- Consistent adherence to coding standards and UI/UX rules
