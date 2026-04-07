# StudioOps Follow-up Audit (-03)

## 1) Scope
- Static-only re-check of the remaining items from `.tmp2/delivery_architecture_audit-02.md`.
- No runtime execution (no app start, no tests, no Docker).

## 2) Verdict
- **Pass (follow-up scope)**
- The previously open documentation mismatch is now fixed.
- The previously noted coverage lag for new hardening rules is also addressed by new API tests.

## 3) Re-check Results

### A) Documentation-to-code mismatch (previously Open)
- Status: **Resolved**
- Evidence:
  - `docs/api-spec.md:32`-`docs/api-spec.md:34` now describes login failures as `200` (normal form) and `422` (HTMX), matching implementation.
  - `app/blueprints/auth.py:50`-`app/blueprints/auth.py:57` returns `422` for HTMX validation failures.
  - `docs/design.md:23` now explicitly allows lightweight blueprint read queries, aligning with actual route code.
  - Example blueprint query usage still present and now consistent with docs: `app/blueprints/booking.py:156`.

### B) Test coverage for newly enforced controls (previously noted lag)
- Status: **Resolved**
- Evidence:
  - New anti-forgery status tests for content save:
    - `API_tests/test_content_api.py:252` (editor cannot forge `published`)
    - `API_tests/test_content_api.py:268` (editor cannot forge `in_review`)
  - New cross-editor draft isolation tests:
    - `API_tests/test_content_api.py:287`-`API_tests/test_content_api.py:305`
  - New post-start cancel/reschedule rejection tests:
    - `API_tests/test_booking_cancellation_window.py:171`-`API_tests/test_booking_cancellation_window.py:237`
  - New participant-bound appeal test:
    - `API_tests/test_reviews_api.py:197`-`API_tests/test_reviews_api.py:220`

## 4) Final Note
- Within this follow-up scope, I did not find remaining unresolved items from the prior report chain.
- Runtime behavior is still **Manual Verification Required** under the static-only boundary.
