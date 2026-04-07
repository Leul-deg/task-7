# StudioOps Static Audit Report (Round 2)

## 1. Verdict
- **Overall conclusion: Partial Pass**
- The previously critical issues were materially addressed (dual review model, rollback object authorization, canary staff validation, validation-copy restore path), but a few medium/low gaps remain.

## 2. Scope and Static Verification Boundary
- **Reviewed:** source code, templates, models, migrations, services, blueprints, docs, and test suites in current working directory.
- **Not reviewed:** runtime behavior, deployment behavior, browser behavior, cron/system scheduler execution, Docker runtime, DB state migration execution.
- **Intentionally not executed:** app startup, tests, Docker, external services.
- **Manual verification required:** real media access behavior, backup restore operational runbook, and UI behavior under schema-version changes.

## 3. Repository / Requirement Mapping Summary
- **Prompt core goal:** offline-first wellness studio operations with booking/waitlist/check-in/no-show, versioned content lifecycle, trusted review + appeals, and on-prem analytics/ops.
- **Mapped implementation:** booking/staff (`app/services/booking_service.py:215`, `app/services/staff_service.py:239`), content workflow (`app/services/content_service.py:226`), reviews/appeals (`app/services/review_service.py:90`), analytics/admin/ops (`app/services/analytics_service.py:86`, `app/blueprints/admin.py:139`), auth/session lockout (`app/services/auth_service.py:45`, `app/config.py:14`).

## 4. Section-by-section Review

### 1. Hard Gates

#### 1.1 Documentation and static verifiability
- **Conclusion: Partial Pass**
- **Rationale:** docs are generally strong and statically usable, but there are still documentation-to-code mismatches.
- **Evidence:** `README.md:83`, `README.md:266`, `docs/api-spec.md:54`, `app/blueprints/auth.py:100`.
- **Manual verification note:** none.

#### 1.2 Material deviation from Prompt
- **Conclusion: Pass**
- **Rationale:** implementation now matches key prompt semantics that were previously broken (dual review support, rollback authorization, staff-only canary validation, validation-copy restore path).
- **Evidence:** `app/models/review.py:29`, `migrations/versions/02bd27386083_initial_schema.py:267`, `app/blueprints/content.py:340`, `app/services/feature_flag_service.py:45`, `app/services/backup_service.py:223`.

### 2. Delivery Completeness

#### 2.1 Core explicit requirements coverage
- **Conclusion: Partial Pass**
- **Rationale:** core functional areas are implemented, including 5-business-day appeal arbitration enforcement and restore validation flow; remaining concern is broad media access control granularity.
- **Evidence:** `app/services/review_service.py:390`, `app/services/backup_service.py:267`, `app/__init__.py:153`.
- **Manual verification note:** media access policy suitability for production data isolation requires human decision.

#### 2.2 End-to-end deliverable vs partial/demo
- **Conclusion: Pass**
- **Rationale:** full application structure with migrations, role-based blueprints, services, templates, and broad tests.
- **Evidence:** `app/__init__.py:101`, `migrations/versions/02bd27386083_initial_schema.py:19`, `unit_tests/test_booking.py:1`, `API_tests/test_content_api.py:1`, `integration_tests/test_flows.py:1`.

### 3. Engineering and Architecture Quality

#### 3.1 Structure and decomposition
- **Conclusion: Pass**
- **Rationale:** layered architecture remains coherent with clear responsibilities.
- **Evidence:** `docs/design.md:11`, `app/blueprints/booking.py:16`, `app/services/booking_service.py:1`.

#### 3.2 Maintainability and extensibility
- **Conclusion: Pass**
- **Rationale:** previous rollback authorization inconsistency has been corrected at both route and service layers.
- **Evidence:** `app/blueprints/content.py:339`, `app/services/content_service.py:487`, `unit_tests/test_content.py:299`, `API_tests/test_content_api.py:300`.

### 4. Engineering Details and Professionalism

#### 4.1 Error handling, logging, validation, API design
- **Conclusion: Partial Pass**
- **Rationale:** strong baseline in validation/logging/guards; however, media endpoint authorization is coarse (authenticated-only) without object-level ownership checks.
- **Evidence:** `app/utils/middleware.py:37`, `app/utils/validators.py:25`, `app/__init__.py:156`, `app/__init__.py:171`.

#### 4.2 Product/service maturity
- **Conclusion: Pass**
- **Rationale:** includes observability, diagnostics, feature flags, backup retention/promote flows, and multi-suite testing.
- **Evidence:** `app/blueprints/admin.py:238`, `app/services/ops_service.py:54`, `app/services/backup_service.py:249`.

### 5. Prompt Understanding and Requirement Fit

#### 5.1 Business goal and constraint fit
- **Conclusion: Partial Pass**
- **Rationale:** major fit is strong and prior mismatches are fixed; residual concerns are secondary (media isolation policy and minor docs/UI consistency).
- **Evidence:** `app/services/review_service.py:390`, `app/services/feature_flag_service.py:53`, `app/services/backup_service.py:223`, `app/templates/base.html:100`, `app/blueprints/admin.py:141`.

### 6. Aesthetics (frontend)

#### 6.1 Visual and interaction quality
- **Conclusion: Pass**
- **Rationale:** clear visual hierarchy, HTMX interactions, responsive structure, and status cues remain solid.
- **Evidence:** `app/templates/base.html:66`, `app/templates/booking/schedule.html:10`, `app/templates/admin/dashboard.html:36`, `app/static/css/custom.css:33`.

## 5. Issues / Suggestions (Severity-Rated)

### Medium

1) **Medium — Media endpoint uses authentication-only access without object-level authorization**
- **Conclusion:** Partial Fail / Security risk
- **Evidence:** `app/__init__.py:153`, `app/__init__.py:156`, `app/__init__.py:171`
- **Impact:** any authenticated user can request any upload-root file path if known; weak per-user/per-object isolation for sensitive uploads.
- **Minimum actionable fix:** enforce ownership/visibility checks before `send_file` (resolve object by storage path and verify role/ownership/session eligibility).

### Low

2) **Low — Documentation mismatch: register success redirect differs from implementation**
- **Conclusion:** Partial Fail (docs consistency)
- **Evidence:** `docs/api-spec.md:58`, `app/blueprints/auth.py:100`
- **Impact:** reviewer/operator confusion during static verification.
- **Minimum actionable fix:** update API spec to reflect redirect to schedule (or adjust code if login-page redirect is preferred policy).

3) **Low — README test counts are stale vs current test suite size**
- **Conclusion:** Partial Fail (docs accuracy)
- **Evidence:** `README.md:268`, `README.md:269`, AST static recount (unit 191, API 205, integration 25).
- **Impact:** undermines confidence in documentation accuracy.
- **Minimum actionable fix:** refresh suite counts and totals in README.

4) **Low — Staff navigation exposes Analytics link that targets admin-only dashboard**
- **Conclusion:** Partial Fail (UI/role consistency)
- **Evidence:** `app/templates/base.html:95`, `app/templates/base.html:100`, `app/blueprints/admin.py:141`
- **Impact:** staff users may hit 403 from visible nav item.
- **Minimum actionable fix:** link staff to `/analytics/` (if intended) or hide admin dashboard link from non-admin users.

## 6. Security Review Summary

- **authentication entry points — Pass**
  - Evidence: `app/blueprints/auth.py:13`, `app/services/auth_service.py:45`, `app/utils/validators.py:25`.
  - Reasoning: local auth, lockout, and password policy are implemented.

- **route-level authorization — Pass**
  - Evidence: `app/utils/decorators.py:24`, `app/blueprints/staff.py:58`, `app/blueprints/admin.py:96`, `app/blueprints/content.py:129`.

- **object-level authorization — Partial Pass**
  - Evidence: rollback protection now present (`app/blueprints/content.py:340`, `app/services/content_service.py:487`), but media endpoint lacks per-object authorization (`app/__init__.py:156`).

- **function-level authorization — Pass**
  - Evidence: staff check-in/no-show enforcement and booking ownership checks (`app/services/staff_service.py:268`, `app/services/booking_service.py:365`).

- **tenant / user data isolation — Partial Pass**
  - Evidence: many ownership checks exist (`app/services/review_service.py:559`, `app/services/booking_service.py:366`), but upload retrieval remains broad (`app/__init__.py:153`).

- **admin / internal / debug protection — Pass**
  - Evidence: admin diagnostics/flags/backups are role-protected (`app/blueprints/admin.py:238`, `app/blueprints/admin.py:402`, `app/blueprints/admin.py:484`).

## 7. Tests and Logging Review

- **Unit tests — Pass**
  - Evidence: expanded service tests, including newly added dual-review and rollback-ownership checks (`unit_tests/test_reviews.py:158`, `unit_tests/test_content.py:299`).

- **API / integration tests — Pass (risk-focused gaps remain)**
  - Evidence: API test added for cross-editor rollback denial (`API_tests/test_content_api.py:300`) and broad role/flow coverage elsewhere.

- **Logging categories / observability — Pass**
  - Evidence: request logs + ops metrics + diagnostics (`app/utils/middleware.py:61`, `app/services/ops_service.py:54`, `app/blueprints/admin.py:238`).

- **Sensitive-data leakage risk in logs / responses — Partial Pass**
  - Evidence: client-error endpoint stores raw message/stack slices (`app/utils/middleware.py:94`, `app/utils/middleware.py:97`); potentially contains sensitive client-side data.

## 8. Test Coverage Assessment (Static Audit)

### 8.1 Test Overview
- Test frameworks: `pytest`, `pytest-flask` (`requirements.txt:11`, `requirements.txt:12`).
- Test entry points documented (`README.md:249`, `run_tests.sh:32`).
- Static AST recount: unit 191, API 205, integration 25 tests.

### 8.2 Coverage Mapping Table

| Requirement / Risk Point | Mapped Test Case(s) | Key Assertion / Fixture / Mock | Coverage Assessment | Gap | Minimum Test Addition |
|---|---|---|---|---|---|
| Dual-sided trusted reviews after completion | `unit_tests/test_reviews.py:158` | customer + instructor both create review successfully | sufficient | API-level equivalent not explicit | add API test for both actors via endpoints |
| Rollback object-level auth | `unit_tests/test_content.py:299`, `API_tests/test_content_api.py:300` | non-owner editor rollback rejected | sufficient | none major | optional admin-override rollback test |
| Staff-only canary eligibility | `unit_tests/test_ops.py:200` | customer ID rejected for canary list | basically covered | API-level check for `/admin/flags/<name>/canary` invalid IDs | add admin endpoint test for invalid staff IDs |
| Validation-copy-before-promote backup flow | code implements (`app/services/backup_service.py:223`, `app/services/backup_service.py:267`) | restore sets validated; promote requires validated | insufficient | no direct tests for new validated/promote path | add unit tests for `restore_backup` creating validation copy and `promote_restore` guard |
| Appeal 5-business-day arbitration enforcement | `app/services/review_service.py:390` logic present | deadline check rejects overdue resolutions | insufficient | no explicit overdue resolve test | add unit/API test with expired deadline => failure |
| Auth lockout/session protections | `API_tests/test_auth_api.py:197` | lockout after configured failed attempts | basically covered | exact timeout-unlock path not validated | add time-controlled unlock test |
| Booking 12h breach behavior | `API_tests/test_booking_cancellation_window.py:71` | breach flag + late_cancel points | sufficient | edge boundary at exactly 12h not explicit | add exact-boundary test |
| Upload/media access authorization | no direct media route tests found (`grep` no `/media/` test) | N/A | missing | media object-level controls could regress unnoticed | add API tests for unauthorized/non-owner media fetch behavior |

### 8.3 Security Coverage Audit
- **authentication:** covered well by auth API tests (`API_tests/test_auth_api.py:117`, `API_tests/test_auth_api.py:197`).
- **route authorization:** covered across staff/admin/content/review routes (`API_tests/test_staff_api.py:15`, `API_tests/test_ops_api.py:35`, `API_tests/test_content_api.py:74`).
- **object-level authorization:** improved and now tested for rollback; media object-level authorization remains untested/missing.
- **tenant/data isolation:** partially covered for bookings/reviews; upload retrieval isolation not covered.
- **admin/internal protection:** covered by admin route access tests (`API_tests/test_admin_appeals_api.py:150`, `API_tests/test_ops_api.py:35`).

### 8.4 Final Coverage Judgment
- **Partial Pass**
- Core flows and recent security fixes are covered better than before, but important residual risks (media access control and backup validation/promotion behavior) lack focused tests.

## 9. Final Notes
- The major previously reported defects are fixed with strong static evidence.
- Remaining work is mostly around tightening data isolation at media retrieval and aligning docs/UI consistency.
- No runtime success claims are made in this audit.
