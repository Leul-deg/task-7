# StudioOps Fix Check Report - Cycle 2

## 1. Scope
- Static-only fix check for the issues listed in `audit_report-02.md`.
- Purpose: confirm that each issue from Cycle 2 is addressed and briefly describe how it was solved.
- No runtime execution was performed for this report.

## 2. Verdict
- **Pass (cycle 2 fix-check scope)**
- The issues originally listed in `audit_report-02.md` are now resolved in code/docs, and the corresponding high-risk paths are covered by targeted regression tests.

## 3. Resolved Issues From `audit_report-02.md`

### 3.1 Editorial approval workflow could be bypassed by editors
- Status: **Resolved**
- Issue: non-admin editors could previously attempt to forge privileged content states through the editor save flow.
- How it was solved: the save logic now forces non-admin editor saves back to `draft`, while publish remains controlled by the explicit review/publish workflow.
- Evidence: `app/services/content_service.py:445`, `app/services/content_service.py:522`, `API_tests/test_content_api.py:252`, `API_tests/test_content_api.py:268`

### 3.2 Unpublished content was visible to any editor
- Status: **Resolved**
- Issue: draft and in-review content access was too broad because it was available to editors outside the owning author context.
- How it was solved: unpublished content access is now restricted to the authoring editor or an admin, and the route passes the current user id into the service-layer access check.
- Evidence: `app/services/content_service.py:155`, `app/services/content_service.py:164`, `app/blueprints/content.py:119`, `API_tests/test_content_api.py:287`, `API_tests/test_content_api.py:305`

### 3.3 Booking cancellation/reschedule window was not enforced as a hard boundary
- Status: **Resolved**
- Issue: cancellation and reschedule requests could pass even after the session had already started.
- How it was solved: both cancellation and reschedule now reject requests once the session start boundary has been crossed, and regression tests verify the rejection behavior.
- Evidence: `app/services/booking_service.py:386`, `app/services/booking_service.py:535`, `API_tests/test_booking_cancellation_window.py:171`, `API_tests/test_booking_cancellation_window.py:237`

### 3.4 Appeal filing lacked participant-bound authorization
- Status: **Resolved**
- Issue: appeal creation was too permissive because it did not strictly require the filer to be a real participant in the reviewed session.
- How it was solved: the appeal service now checks whether the user is the reservation holder, the assigned instructor, or an admin before allowing the appeal to proceed.
- Evidence: `app/services/review_service.py:323`, `app/services/review_service.py:328`, `API_tests/test_reviews_api.py:197`, `API_tests/test_reviews_api.py:220`

### 3.5 Waitlist join did not require a full session
- Status: **Resolved**
- Issue: users could try to join the waitlist even when the session still had available spots.
- How it was solved: the waitlist join path now checks capacity first and rejects waitlist joins until the session is actually full.
- Evidence: `app/services/booking_service.py:603`, `app/services/booking_service.py:630`

### 3.6 Documentation-to-code mismatches reduced auditability
- Status: **Resolved**
- Issue: some docs no longer matched implementation behavior, especially around login failure responses and lightweight blueprint queries.
- How it was solved: the API spec and design docs were updated so the documented behavior now matches the auth flow and current blueprint usage.
- Evidence: `docs/api-spec.md:33`, `docs/api-spec.md:34`, `app/blueprints/auth.py:50`, `docs/design.md:23`, `app/blueprints/booking.py:156`

### 3.7 Health endpoint could disclose internal DB error details
- Status: **Resolved**
- Issue: health check failures previously risked exposing internal database exception details to callers.
- How it was solved: the health endpoint now logs the internal exception server-side and returns a generic database status externally.
- Evidence: `app/__init__.py:236`, `app/__init__.py:237`, `app/__init__.py:243`

## 4. Summary
- This file now mirrors the Cycle 2 audit list directly.
- Every issue from `audit_report-02.md` is included here and marked as resolved with a brief fix description.
