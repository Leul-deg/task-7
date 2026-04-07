# StudioOps Static Audit Report

## 1. Verdict
- **Overall conclusion: Fail**
- Rationale: the delivery is substantial and mostly product-shaped, but there are material requirement and security failures: (a) the data model blocks dual-sided post-session reviews (customer + staff) for one reservation, and (b) object-level authorization is missing for content rollback, allowing cross-editor rollback.

## 2. Scope and Static Verification Boundary
- **Reviewed:** repository structure, docs, Flask entry points, blueprints, models, service layer, templates, migration schema, and test suites (`README.md:1`, `app/__init__.py:58`, `app/blueprints/*.py`, `app/services/*.py`, `app/models/*.py`, `unit_tests/*.py`, `API_tests/*.py`, `integration_tests/test_flows.py:1`).
- **Not reviewed/executed:** runtime behavior, browser interactions, DB migration execution, Docker runtime, scheduled cron execution, network behavior, and real file-serving behavior.
- **Intentionally not executed:** app start, tests, Docker, external services (per audit constraints).
- **Manual verification required:** upload/file URL serving behavior, production cron scheduling for nightly jobs/backups, and real-world forced-upgrade UX behavior.

## 3. Repository / Requirement Mapping Summary
- **Prompt core goal:** offline-first studio operations with booking/waitlist/check-in/no-show, versioned content workflow, trusted reviews + appeals, and on-prem analytics/ops controls.
- **Mapped implementation areas:** booking (`app/blueprints/booking.py:92`, `app/services/booking_service.py:215`), staff operations (`app/blueprints/staff.py:56`, `app/services/staff_service.py:239`), content/versioning (`app/blueprints/content.py:185`, `app/services/content_service.py:226`), reviews/appeals (`app/blueprints/reviews.py:57`, `app/services/review_service.py:90`), analytics/admin/ops (`app/services/analytics_service.py:86`, `app/blueprints/admin.py:139`, `app/services/ops_service.py:54`), local auth/session/lockout (`app/blueprints/auth.py:13`, `app/services/auth_service.py:45`, `app/config.py:14`).

## 4. Section-by-section Review

### 1. Hard Gates

#### 1.1 Documentation and static verifiability
- **Conclusion: Partial Pass**
- **Rationale:** setup/run/test instructions and architecture docs exist and are mostly consistent with code; however, there are material documentation inconsistencies with implemented rules.
- **Evidence:** `README.md:83`, `README.md:249`, `docs/design.md:87`, `docs/design.md:95`, `docs/api-spec.md:54`, `app/utils/validators.py:5`, `app/services/credit_service.py:5`.
- **Manual verification note:** none.

#### 1.2 Material deviation from Prompt
- **Conclusion: Fail**
- **Rationale:** the implementation contradicts key prompt semantics for reviews (both customer and staff reviewing a completed reservation) and contains cross-editor rollback authorization weakness.
- **Evidence:** `app/models/review.py:9`, `migrations/versions/02bd27386083_initial_schema.py:267`, `app/blueprints/content.py:334`, `app/services/content_service.py:478`.
- **Manual verification note:** none.

### 2. Delivery Completeness

#### 2.1 Coverage of explicitly stated core requirements
- **Conclusion: Partial Pass**
- **Rationale:** most core features are implemented (booking/waitlist/check-in/no-show/content lifecycle/reports/analytics/flags/backups), but key requirement gaps remain (dual review per completed reservation; canary intended for staff subset but not staff-validated; backup restore flow does not implement validation-copy step prior to promotion).
- **Evidence:** `app/services/booking_service.py:215`, `app/services/staff_service.py:341`, `app/services/content_service.py:326`, `app/services/review_service.py:90`, `app/models/review.py:9`, `app/services/feature_flag_service.py:64`, `app/blueprints/admin.py:453`, `app/services/backup_service.py:196`.
- **Manual verification note:** scheduler execution for nightly credit and backups is not statically provable (`README.md:220`, `app/services/credit_service.py:232`, `app/services/backup_service.py:297`).

#### 2.2 End-to-end deliverable vs partial/demo
- **Conclusion: Pass**
- **Rationale:** complete multi-module project with models/services/blueprints/templates/migrations/tests and product-style admin features; not a snippet-level demo.
- **Evidence:** `README.md:52`, `app/__init__.py:101`, `migrations/versions/02bd27386083_initial_schema.py:19`, `unit_tests/test_booking.py:1`, `API_tests/test_booking_api.py:1`, `integration_tests/test_flows.py:1`.
- **Manual verification note:** runtime success still requires manual run.

### 3. Engineering and Architecture Quality

#### 3.1 Structure and module decomposition
- **Conclusion: Pass**
- **Rationale:** clean layered split (blueprints/services/models/utils), app factory pattern, and route registration by domain.
- **Evidence:** `app/__init__.py:58`, `docs/design.md:11`, `app/blueprints/booking.py:16`, `app/services/booking_service.py:1`.
- **Manual verification note:** none.

#### 3.2 Maintainability and extensibility
- **Conclusion: Partial Pass**
- **Rationale:** overall maintainable, but critical authorization logic is inconsistent across content endpoints (edit/history enforce owner; rollback does not), which is a maintainability and security smell.
- **Evidence:** `app/blueprints/content.py:160`, `app/blueprints/content.py:321`, `app/blueprints/content.py:334`, `app/services/content_service.py:478`.
- **Manual verification note:** none.

### 4. Engineering Details and Professionalism

#### 4.1 Error handling, logging, validation, API design
- **Conclusion: Partial Pass**
- **Rationale:** good baseline (central decorators, validation, structured service returns, request logging, ops metrics), but material gaps exist in object-level authorization and requirement-fit constraints.
- **Evidence:** `app/utils/decorators.py:24`, `app/utils/validators.py:25`, `app/utils/middleware.py:37`, `app/services/ops_service.py:54`, `app/blueprints/content.py:334`, `app/services/content_service.py:478`.
- **Manual verification note:** file-serving path behavior cannot be fully proven statically.

#### 4.2 Product/service shape vs demo-only
- **Conclusion: Pass**
- **Rationale:** the repository is organized as a real service with migrations, backups, analytics, diagnostics, feature flags, and multi-suite tests.
- **Evidence:** `app/blueprints/admin.py:238`, `app/services/backup_service.py:294`, `app/services/feature_flag_service.py:75`, `run_tests.sh:29`.
- **Manual verification note:** none.

### 5. Prompt Understanding and Requirement Fit

#### 5.1 Business-goal and constraint alignment
- **Conclusion: Fail**
- **Rationale:** several prompt constraints are incompletely implemented or mismatched: dual trusted review actors on a completed reservation, staff-only canary subset semantics, and restore-to-validation-copy workflow before promotion.
- **Evidence:** `app/models/review.py:9`, `app/services/feature_flag_service.py:64`, `app/blueprints/admin.py:453`, `app/services/backup_service.py:196`, `app/services/backup_service.py:270`.
- **Manual verification note:** whether external infrastructure remaps upload filesystem paths to HTTP paths is unknown.

### 6. Aesthetics (frontend)

#### 6.1 Visual and interaction quality
- **Conclusion: Pass**
- **Rationale:** UI has clear hierarchy, distinct sections/cards, role-aware navigation, HTMX feedback states, and responsive layouts across major pages.
- **Evidence:** `app/templates/base.html:66`, `app/templates/booking/schedule.html:10`, `app/templates/admin/dashboard.html:36`, `app/static/css/custom.css:3`, `app/templates/content/editor_form.html:138`.
- **Manual verification note:** responsive behavior and interactive polish still require manual browser verification.

## 5. Issues / Suggestions (Severity-Rated)

### High

1) **High — Completed reservation cannot support both customer and staff reviews**
- **Conclusion:** Fail
- **Evidence:** `app/models/review.py:9`, `migrations/versions/02bd27386083_initial_schema.py:267`, `app/services/review_service.py:122`
- **Impact:** violates prompt requirement that both customer and staff can rate after completion; second review for same reservation is structurally blocked.
- **Minimum actionable fix:** replace `unique=True` on `reservation_id` with composite uniqueness on (`reservation_id`, `user_id`) and update migration/model/tests accordingly.

2) **High — Missing object-level authorization on content rollback**
- **Conclusion:** Fail
- **Evidence:** `app/blueprints/content.py:334`, `app/services/content_service.py:478`, `app/blueprints/content.py:321`
- **Impact:** any authenticated editor can rollback content they do not own if they know IDs; unauthorized data modification risk.
- **Minimum actionable fix:** enforce owner-or-admin check in rollback route/service (same pattern as `editor_edit`/`history`) and add negative tests for cross-editor rollback attempts.

3) **High — Uploaded media paths are stored as filesystem paths and used directly in HTML without serving route**
- **Conclusion:** Suspected Risk / Manual Verification Required
- **Evidence:** `app/services/file_service.py:65`, `app/services/file_service.py:68`, `app/templates/content/view.html:43`, `app/templates/content/view.html:73`, `app/templates/partials/reviews/review_card.html:52`
- **Impact:** covers/attachments/review images may not be retrievable via HTTP, threatening core content/review media functionality.
- **Minimum actionable fix:** add explicit authenticated file-serving endpoints (e.g., `send_from_directory`) and persist URL-safe relative paths rather than raw filesystem paths.

### Medium

4) **Medium — Backup restore flow does not implement validation-copy restore before promotion**
- **Conclusion:** Partial Fail vs prompt
- **Evidence:** `app/services/backup_service.py:196`, `app/services/backup_service.py:232`, `app/services/backup_service.py:270`
- **Impact:** deviates from requirement for restore-to-validation copy before promoting to live DB.
- **Minimum actionable fix:** implement two-step restore: restore to validation DB copy, validate, then explicit promote action.

5) **Medium — Canary feature targeting is not constrained to staff accounts**
- **Conclusion:** Partial Fail vs prompt semantics
- **Evidence:** `app/blueprints/admin.py:453`, `app/services/feature_flag_service.py:64`, `app/services/feature_flag_service.py:135`
- **Impact:** canary flags can be enabled for non-staff users, violating “subset of staff accounts” control intent.
- **Minimum actionable fix:** validate canary IDs against `User.role == 'staff'` (or admin policy), reject non-staff IDs.

6) **Medium — 5-business-day arbitration SLA is displayed but not enforced**
- **Conclusion:** Partial Pass
- **Evidence:** `app/services/review_service.py:337`, `app/services/review_service.py:374`, `app/services/review_service.py:474`, `app/templates/reviews/appeals_dashboard.html:27`
- **Impact:** overdue appeals are flagged but still resolvable without SLA guard; business-policy compliance is weak.
- **Minimum actionable fix:** enforce SLA policy in `resolve_appeal` (or explicitly document allowed post-deadline behavior and escalation path).

### Low

7) **Low — Documentation contradictions with implemented security/business rules**
- **Conclusion:** Partial Fail (docs quality)
- **Evidence:** `docs/api-spec.md:54`, `app/utils/validators.py:5`, `docs/design.md:89`, `docs/design.md:95`, `app/services/credit_service.py:5`
- **Impact:** reviewers/operators may apply incorrect password and credit-scoring assumptions.
- **Minimum actionable fix:** align docs with code+prompt; include one authoritative policy table and remove contradictory values.

## 6. Security Review Summary

- **Authentication entry points — Pass**
  - Evidence: local login/register/logout routes and password hashing (`app/blueprints/auth.py:13`, `app/services/auth_service.py:9`, `app/services/auth_service.py:45`).
  - Reasoning: local username/email + password auth, lockout and session controls are implemented.

- **Route-level authorization — Pass**
  - Evidence: decorators and role checks on protected blueprints (`app/utils/decorators.py:24`, `app/blueprints/staff.py:58`, `app/blueprints/admin.py:96`, `app/blueprints/content.py:129`).
  - Reasoning: broad route boundaries are consistently protected.

- **Object-level authorization — Fail**
  - Evidence: rollback endpoint/service lack ownership check (`app/blueprints/content.py:334`, `app/services/content_service.py:478`) while similar endpoints do enforce ownership (`app/blueprints/content.py:160`, `app/blueprints/content.py:321`).
  - Reasoning: inconsistent object checks allow cross-object mutation.

- **Function-level authorization — Partial Pass**
  - Evidence: strong checks in booking/staff operations (`app/services/booking_service.py:365`, `app/services/staff_service.py:268`), but missing in rollback service.
  - Reasoning: mostly implemented, with one critical exception.

- **Tenant / user data isolation — Partial Pass**
  - Evidence: owner checks exist for booking cancellation/reschedule and review edit/delete (`app/services/booking_service.py:366`, `app/services/review_service.py:559`), but rollback bypass exists (`app/services/content_service.py:478`).
  - Reasoning: user isolation is generally present but broken in one high-risk path.

- **Admin / internal / debug protection — Pass**
  - Evidence: admin diagnostics/flags/backups guarded by admin role (`app/blueprints/admin.py:238`, `app/blueprints/admin.py:402`, `app/blueprints/admin.py:484`).
  - Reasoning: sensitive operational endpoints are role-protected.

## 7. Tests and Logging Review

- **Unit tests — Pass**
  - Evidence: broad service tests for booking/content/reviews/analytics/ops (`unit_tests/test_booking.py:1`, `unit_tests/test_content.py:1`, `unit_tests/test_reviews.py:1`, `unit_tests/test_analytics.py:1`, `unit_tests/test_ops.py:1`).

- **API / integration tests — Pass (with gaps)**
  - Evidence: route-level tests across auth/booking/content/reviews/staff/admin plus end-to-end flow classes (`API_tests/test_auth_api.py:1`, `API_tests/test_booking_api.py:1`, `API_tests/test_content_api.py:1`, `integration_tests/test_flows.py:150`).
  - Gap: no negative tests for cross-editor rollback authorization.

- **Logging categories / observability — Pass**
  - Evidence: server/client log capture, request metrics, alerts, diagnostics pages (`app/utils/middleware.py:37`, `app/models/ops.py:36`, `app/services/ops_service.py:54`, `app/blueprints/admin.py:238`).

- **Sensitive-data leakage risk in logs/responses — Partial Pass**
  - Evidence: middleware logs method/path/status/latency (not credentials) (`app/utils/middleware.py:64`), but client-error endpoint stores arbitrary client messages/stacks (`app/utils/middleware.py:94`).
  - Risk: potential inadvertent client-side sensitive data in logged stack traces.

## 8. Test Coverage Assessment (Static Audit)

### 8.1 Test Overview
- Unit tests exist: `unit_tests/` with service-focused coverage (`unit_tests/test_booking.py:1`, `unit_tests/test_reviews.py:1`).
- API/integration tests exist: `API_tests/` and `integration_tests/test_flows.py` (`README.md:266`, `integration_tests/test_flows.py:1`).
- Framework: pytest + pytest-flask (`requirements.txt:11`, `requirements.txt:12`).
- Test entry points documented: `run_tests.sh` and direct pytest (`README.md:249`, `run_tests.sh:32`).

### 8.2 Coverage Mapping Table

| Requirement / Risk Point | Mapped Test Case(s) | Key Assertion / Fixture / Mock | Coverage Assessment | Gap | Minimum Test Addition |
|---|---|---|---|---|---|
| Local auth + lockout policy | `API_tests/test_auth_api.py:197` | lockout after max attempts and locked message (`API_tests/test_auth_api.py:211`) | basically covered | exact 15-min expiry behavior not time-advanced in API tests | add time-freeze test for unlock after lockout window |
| Booking conflict/capacity/waitlist | `unit_tests/test_booking.py:62`, `unit_tests/test_booking.py:94`, `API_tests/test_booking_api.py:94` | conflict action and waitlist status codes (`unit_tests/test_booking.py:91`, `API_tests/test_booking_api.py:111`) | sufficient | race/concurrency not covered | add transactional duplicate/capacity concurrency test |
| 12h cancellation/reschedule breach scoring | `API_tests/test_booking_cancellation_window.py:71`, `unit_tests/test_booking.py:140` | breach flag + `late_cancel` points (`API_tests/test_booking_cancellation_window.py:90`, `API_tests/test_booking_cancellation_window.py:101`) | sufficient | none major | optional boundary test at exactly 12h |
| Staff check-in / no-show authorization | `unit_tests/test_staff.py:233`, `API_tests/test_staff_api.py:61` | unauthorized no-show/checkin rejected (`API_tests/test_staff_api.py:61`) | basically covered | object-level checks for all staff actions could be broader | add explicit cross-instructor roster/checkin denial tests for each route |
| Content workflow + versioning + rollback happy path | `unit_tests/test_content.py:132`, `unit_tests/test_content.py:242`, `API_tests/test_content_api.py:275` | status transitions and rollback success (`unit_tests/test_content.py:261`) | basically covered | missing unauthorized rollback test | add API + service tests: other editor rollback must 403/fail |
| Review eligibility (completed only) + duplicate guard | `unit_tests/test_reviews.py:56`, `API_tests/test_reviews_api.py:111`, `integration_tests/test_flows.py:256` | duplicate blocked and non-completed rejected (`API_tests/test_reviews_api.py:124`, `integration_tests/test_flows.py:271`) | basically covered | dual-review-per-reservation requirement not tested | add test allowing both customer+staff reviews on same reservation |
| Appeal flow + admin resolution auth | `API_tests/test_admin_appeals_api.py:101`, `API_tests/test_admin_appeals_api.py:142`, `unit_tests/test_reviews.py:281` | non-admin blocked and status changes (`API_tests/test_admin_appeals_api.py:150`, `unit_tests/test_reviews.py:291`) | basically covered | SLA/deadline enforcement absent | add overdue appeal resolution policy test |
| Analytics funnel + heartbeat tracking | `API_tests/test_booking_analytics.py:30`, `API_tests/test_content_api.py:327`, `unit_tests/test_analytics.py:286` | event counts and heartbeat dedup assertions (`API_tests/test_booking_analytics.py:35`, `unit_tests/test_analytics.py:287`) | sufficient | anonymous UV semantics not asserted | add UV test including anonymous session identifiers |
| Object-level auth on rollback (high risk) | only positive rollback tests `API_tests/test_content_api.py:275` | no negative authorization assertion found | missing | severe defect can remain undetected | add negative tests for cross-editor rollback via API and service |

### 8.3 Security Coverage Audit
- **Authentication:** basically covered (login success/failure/lockout in `API_tests/test_auth_api.py:117`, `API_tests/test_auth_api.py:197`).
- **Route authorization:** covered across staff/admin/content routes (`API_tests/test_staff_api.py:15`, `API_tests/test_ops_api.py:35`, `API_tests/test_content_api.py:70`).
- **Object-level authorization:** insufficient; rollback path not negatively tested (`API_tests/test_content_api.py:275` only happy path).
- **Tenant/data isolation:** partially covered (booking cancel-other-user denied in `API_tests/test_booking_api.py:56`), but not comprehensive for content rollback.
- **Admin/internal protection:** covered (`API_tests/test_ops_api.py:35`, `API_tests/test_admin_appeals_api.py:150`).

### 8.4 Final Coverage Judgment
- **Partial Pass**
- Major happy paths and many failure paths are covered, but critical object-level authorization around rollback is untested; severe defects can pass the suite.

## 9. Final Notes
- This audit is strictly static and evidence-based; no runtime claims are made.
- Highest-priority remediation is: fix rollback object authorization and fix review model constraints for dual-sided completed-reservation reviews.
- After fixes, add targeted negative security tests before re-acceptance.
