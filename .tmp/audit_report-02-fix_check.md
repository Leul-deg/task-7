# StudioOps Fix Check Report - Cycle 2

## 1. Scope
- Static-only fix check for the second audit cycle.
- Purpose: document the issues that were fixed in this cycle and briefly explain how they were solved.
- No runtime execution was performed for this report.

## 2. Verdict
- **Pass (cycle 2 fix-check scope)**
- The items carried into this cycle were resolved through documentation updates and targeted regression tests.

## 3. Fixes Completed In This Cycle

### 3.1 Documentation-to-code mismatch
- Issue: the documentation no longer matched the real implementation in a few important places, especially around login failure behavior and blueprint query guidance.
- Fix: the docs were updated so the API spec now matches the actual auth response behavior, and the design docs now reflect the lightweight blueprint reads used in the codebase.
- Evidence: `docs/api-spec.md:32`, `docs/api-spec.md:34`, `app/blueprints/auth.py:50`, `docs/design.md:23`, `app/blueprints/booking.py:156`

### 3.2 Missing regression tests for newly enforced content workflow rules
- Issue: the hardening for content workflow rules existed, but there were no targeted tests proving editors could not forge privileged status transitions.
- Fix: new API tests were added to verify that editors cannot directly force content into `published` or `in_review` through the save endpoint.
- Evidence: `API_tests/test_content_api.py:252`, `API_tests/test_content_api.py:268`

### 3.3 Missing regression tests for cross-editor draft isolation
- Issue: the new unpublished-content access restriction needed explicit coverage so future regressions would be caught.
- Fix: new API tests were added to confirm that one editor cannot view another editor's draft while valid author/admin access still works.
- Evidence: `API_tests/test_content_api.py:287`, `API_tests/test_content_api.py:305`

### 3.4 Missing regression tests for post-start cancel/reschedule rejection
- Issue: the booking window hardening needed dedicated tests to prove cancel/reschedule requests are rejected once the protected time boundary is crossed.
- Fix: new API tests were added for both cancel and reschedule behavior after session start, including checks that reservation state is preserved on rejection.
- Evidence: `API_tests/test_booking_cancellation_window.py:171`, `API_tests/test_booking_cancellation_window.py:237`

### 3.5 Missing regression tests for participant-bound appeal authorization
- Issue: the new appeal authorization rule needed explicit coverage so non-participants could not silently regain access through future changes.
- Fix: new API tests were added to verify that non-participants are rejected while legitimate participants such as instructors can still file appeals.
- Evidence: `API_tests/test_reviews_api.py:197`, `API_tests/test_reviews_api.py:220`

## 4. Summary
- This file is intentionally a fix summary for Cycle 2 only.
- It focuses on what was fixed and how it was solved, rather than discussing unresolved items.
