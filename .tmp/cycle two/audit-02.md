# StudioOps Follow-up Audit (-02)

## 1) Scope
- Static-only re-check against issues listed in `.tmp2/delivery_architecture_audit.md`.
- No runtime execution (no app start, no tests, no Docker).

## 2) Re-check Verdict
- **Overall:** Partial Pass
- **Resolved:** 6 / 7 previously reported issues
- **Still Open:** 1 issue (documentation-to-code mismatch)

## 3) Issue-by-Issue Status

### A. Previously Blocker / High

1. **Editorial approval bypass via `/content/editor/save`**
- Status: **Resolved**
- Evidence: `app/services/content_service.py:256`, `app/services/content_service.py:261`, `app/services/content_service.py:304`
- Why: non-admin saves are forced to `draft`; arbitrary status setting is blocked for editors.

2. **Unpublished content visible to any editor**
- Status: **Resolved**
- Evidence: `app/services/content_service.py:161`, `app/services/content_service.py:164`, `app/services/content_service.py:167`, `app/blueprints/content.py:119`, `app/blueprints/content.py:120`
- Why: unpublished content is now restricted to admin or author editor only, and caller passes `user_id`.

3. **Booking cancel/reschedule allowed after start**
- Status: **Resolved (for the reported loophole)**
- Evidence: `app/services/booking_service.py:383`, `app/services/booking_service.py:386`, `app/services/booking_service.py:532`, `app/services/booking_service.py:535`
- Why: cancellation/reschedule now rejects once the original session has started.
- Note: strict “12-hour hard cutoff” semantics remain a business interpretation question; current implementation allows late actions before start and marks breach.

4. **Appeal filing not participant-scoped**
- Status: **Resolved**
- Evidence: `app/services/review_service.py:318`, `app/services/review_service.py:322`, `app/services/review_service.py:328`
- Why: only session participants (or admin) can file an appeal.

### B. Previously Medium

5. **Waitlist join allowed when session not full**
- Status: **Resolved**
- Evidence: `app/services/booking_service.py:624`, `app/services/booking_service.py:627`
- Why: explicit capacity check now rejects waitlist join if direct booking is still possible.

6. **Docs/code mismatch (API/design claims vs implementation)**
- Status: **Open**
- Evidence:
  - `docs/api-spec.md:34` claims `429` for lockout, but login flow returns form errors (`app/blueprints/auth.py:50`, `app/blueprints/auth.py:57`).
  - `docs/design.md:23` claims blueprints never query DB directly, but blueprints do ORM access (example: `app/blueprints/booking.py:156`).
- Impact: reviewer/operator expectations may be incorrect.

7. **Health endpoint leaks internal DB exception text**
- Status: **Resolved**
- Evidence: `app/__init__.py:237`, `app/__init__.py:238`, `app/__init__.py:243`
- Why: exception details are logged server-side; response now uses generic `"error"`.

## 4) Additional Static Notes
- Coverage lag risk: tests do not yet clearly assert new hardening behavior (e.g., forged editor `status` save and participant-only appeal checks).
  - Evidence: no explicit new assertions found in `API_tests/test_content_api.py` (end through `API_tests/test_content_api.py:534`) and `API_tests/test_reviews_api.py` appeal section (`API_tests/test_reviews_api.py:166`).
- This is not proof of runtime failure; it is a **test coverage gap**.

## 5) Final Recommendation
- Delivery is materially improved and major security/business-flow defects are fixed.
- Before final acceptance, close the remaining documentation mismatch and add targeted tests for the newly enforced controls.
