# StudioOps Fix Check Report - Cycle 1

## 1. Scope
- Static-only fix check for the issues listed in `audit_report-01.md`.
- Purpose: confirm that each issue from Cycle 1 is addressed and briefly describe how it was solved.
- No runtime execution was performed for this report.

## 2. Verdict
- **Pass (cycle 1 fix-check scope)**
- The issues originally listed in `audit_report-01.md` are now resolved in code/docs, with targeted tests added where appropriate.

## 3. Resolved Issues From `audit_report-01.md`

### 3.1 Completed reservation cannot support both customer and staff reviews
- Status: **Resolved**
- Issue: the original review model structurally blocked dual-sided reviews for a single completed reservation.
- How it was solved: the review uniqueness rule was changed from one review per reservation to one review per `(reservation_id, user_id)`, which allows both the customer and the staff member to submit their own review for the same reservation.
- Evidence: `app/models/review.py:28`, `unit_tests/test_reviews.py:158`

### 3.2 Missing object-level authorization on content rollback
- Status: **Resolved**
- Issue: rollback actions were not enforcing owner-or-admin authorization, which allowed cross-editor rollback attempts.
- How it was solved: owner/admin checks were added to both the rollback route and the rollback service logic, and negative tests were added so unauthorized rollback attempts are rejected.
- Evidence: `app/blueprints/content.py:341`, `app/services/content_service.py:498`, `unit_tests/test_content.py:299`, `API_tests/test_content_api.py:300`

### 3.3 Uploaded media paths were not safely served through an authenticated media route
- Status: **Resolved**
- Issue: uploaded media handling was previously flagged because stored paths were being used directly without a proper object-aware serving layer.
- How it was solved: the app now serves uploads through a dedicated `/media/<path>` route, validates the resolved path under the upload root, and applies object-level access checks before returning files.
- Evidence: `app/__init__.py:153`, `app/__init__.py:177`, `app/__init__.py:203`, `app/templates/content/view.html:43`, `app/templates/partials/reviews/review_card.html:52`

### 3.4 Backup restore flow did not implement validation-copy restore before promotion
- Status: **Resolved**
- Issue: the original restore flow did not provide the required restore-to-validation step before promotion to live data.
- How it was solved: restore now creates a validation copy first, marks the backup as `validated`, and requires a separate promotion step to apply the validated backup to the live database or uploads directory.
- Evidence: `app/services/backup_service.py:231`, `app/services/backup_service.py:261`, `app/services/backup_service.py:300`, `app/services/backup_service.py:315`, `unit_tests/test_ops.py:240`, `unit_tests/test_ops.py:271`

### 3.5 Canary feature targeting was not constrained to staff accounts
- Status: **Resolved**
- Issue: canary rollout IDs were originally flagged because they were not guaranteed to belong only to staff users.
- How it was solved: canary IDs are now validated against users with `role == "staff"` before a flag is created or updated, and invalid non-staff IDs are rejected.
- Evidence: `app/services/feature_flag_service.py:45`, `app/services/feature_flag_service.py:53`, `app/services/feature_flag_service.py:116`, `app/services/feature_flag_service.py:157`

### 3.6 Appeal resolution deadline was not enforced
- Status: **Resolved**
- Issue: the appeal workflow displayed a 5-business-day deadline but did not previously enforce it at resolution time.
- How it was solved: appeal resolution now checks the current time against the stored deadline and rejects overdue resolutions instead of silently allowing them.
- Evidence: `app/services/review_service.py:406`, `app/services/review_service.py:409`, `unit_tests/test_reviews.py:443`

### 3.7 Documentation contradictions with implemented security/business rules
- Status: **Resolved**
- Issue: parts of the documentation were inconsistent with the implemented password, lockout, and credit-scoring rules.
- How it was solved: the docs were aligned with the actual validators and service logic so the documented password and credit policies now match the code.
- Evidence: `docs/api-spec.md:33`, `docs/api-spec.md:54`, `docs/design.md:80`, `docs/design.md:89`, `app/utils/validators.py:5`, `app/services/credit_service.py:5`

## 4. Summary
- This file now mirrors the Cycle 1 audit list directly.
- Every issue from `audit_report-01.md` is included here and marked as resolved with a brief fix description.
