# Unified Test Coverage + README Audit Report
**Project:** StudioOps  
**Audit Date:** 2026-04-16  
**Auditor Mode:** Strict / Evidence-based  
**Actual Test Count (collected):** 544

---

# PART 1: TEST COVERAGE AUDIT

---

## Backend Endpoint Inventory

All endpoints extracted from blueprint files + `app/__init__.py`. Prefixes resolved via `app/register_blueprint` calls (`app/__init__.py:109–116`).

### Core (`app/__init__.py`)

| # | Method | Path |
|---|---|---|
| C1 | GET | `/` |
| C2 | GET | `/media/<path:storage_path>` |
| C3 | GET | `/health` |

### Auth (`url_prefix=/auth`, `app/blueprints/auth.py`)

| # | Method | Path |
|---|---|---|
| A1 | GET | `/auth/login` |
| A2 | POST | `/auth/login` |
| A3 | POST | `/auth/logout` |
| A4 | GET | `/auth/register` |
| A5 | POST | `/auth/register` |
| A6 | GET | `/auth/change-password` |
| A7 | POST | `/auth/change-password` |

### Booking (`no prefix`, `app/blueprints/booking.py`)

| # | Method | Path |
|---|---|---|
| B1 | GET | `/schedule` |
| B2 | GET | `/schedule/sessions/<id>` |
| B3 | POST | `/booking/reserve` |
| B4 | POST | `/booking/waitlist` |
| B5 | POST | `/booking/<id>/cancel` |
| B6 | POST | `/booking/<id>/reschedule` |
| B7 | GET | `/booking/` |
| B8 | GET | `/booking/my-bookings` |
| B9 | POST | `/booking/waitlist/<id>/leave` |
| B10 | GET | `/booking/available-sessions` |

### Staff (`url_prefix=/staff`, `app/blueprints/staff.py`)

| # | Method | Path |
|---|---|---|
| S1 | GET | `/staff/` |
| S2 | GET | `/staff/schedule` |
| S3 | GET | `/staff/session/<id>/roster` |
| S4 | POST | `/staff/checkin/<id>` |
| S5 | POST | `/staff/no-show/<id>` |
| S6 | GET | `/staff/resource-warnings` |
| S7 | GET | `/staff/sessions` |
| S8 | POST | `/staff/sessions` |
| S9 | PUT/POST | `/staff/sessions/<id>` |
| S10 | POST/DELETE | `/staff/sessions/<id>/delete` |
| S11 | GET | `/staff/resources` |
| S12 | POST | `/staff/resources` |
| S13 | POST | `/staff/resources/<id>/toggle` |
| S14 | GET | `/staff/pending-approvals` |
| S15 | POST | `/staff/approve/<id>` |
| S16 | POST | `/staff/deny/<id>` |
| S17 | GET | `/staff/credit-dashboard` |
| S18 | GET | `/staff/credit-dashboard/<id>` |

### Content (`url_prefix=/content`, `app/blueprints/content.py`)

| # | Method | Path |
|---|---|---|
| CO1 | GET | `/content/index` |
| CO2 | GET | `/content/` |
| CO3 | GET | `/content/<id>` |
| CO4 | GET | `/content/editor` |
| CO5 | GET | `/content/editor/new` |
| CO6 | GET | `/content/editor/<id>/edit` |
| CO7 | POST | `/content/editor/save` |
| CO8 | POST | `/content/<id>/submit-review` |
| CO9 | POST | `/content/<id>/publish` |
| CO10 | POST | `/content/<id>/reject` |
| CO11 | GET | `/content/<id>/history` |
| CO12 | POST | `/content/<id>/rollback/<version_id>` |
| CO13 | DELETE | `/content/editor/<id>` |
| CO14 | POST | `/content/preview` |
| CO15 | GET | `/content/categories` |
| CO16 | GET | `/content/filters` |
| CO17 | POST | `/content/filters` |
| CO18 | POST | `/content/filters/<id>/toggle` |
| CO19 | DELETE | `/content/filters/<id>` |

### Reviews (`url_prefix=/reviews`, `app/blueprints/reviews.py`)

| # | Method | Path |
|---|---|---|
| R1 | GET | `/reviews/` |
| R2 | GET | `/reviews/new/<reservation_id>` |
| R3 | POST | `/reviews` |
| R4 | GET | `/reviews/session/<id>` |
| R5 | GET | `/reviews/my-reviews` |
| R6 | PUT | `/reviews/<id>` |
| R7 | DELETE | `/reviews/<id>` |
| R8 | POST | `/reviews/<id>/appeal` |

### Analytics (`url_prefix=/analytics`, `app/blueprints/analytics.py`)

| # | Method | Path |
|---|---|---|
| AN1 | GET | `/analytics/` |
| AN2 | POST | `/analytics/event` |
| AN3 | POST | `/analytics/heartbeat` |

### Admin (`url_prefix=/admin`, `app/blueprints/admin.py`)

| # | Method | Path |
|---|---|---|
| AD1 | GET | `/admin/` |
| AD2 | GET | `/admin/appeals` |
| AD3 | POST | `/admin/appeals/<id>/resolve` |
| AD4 | GET | `/admin/dashboard` |
| AD5 | GET | `/admin/reports/export` |
| AD6 | POST | `/admin/reports/generate` |
| AD7 | GET | `/admin/diagnostics` |
| AD8 | GET | `/admin/diagnostics/metrics` |
| AD9 | GET | `/admin/diagnostics/errors` |
| AD10 | GET | `/admin/diagnostics/slow` |
| AD11 | GET | `/admin/diagnostics/client-logs` |
| AD12 | GET | `/admin/alerts` |
| AD13 | POST | `/admin/alerts` |
| AD14 | POST | `/admin/alerts/<id>/toggle` |
| AD15 | DELETE | `/admin/alerts/<id>` |
| AD16 | GET | `/admin/flags` |
| AD17 | POST | `/admin/flags` |
| AD18 | POST | `/admin/flags/<name>/toggle` |
| AD19 | POST | `/admin/flags/<name>/canary` |
| AD20 | DELETE | `/admin/flags/<name>` |
| AD21 | GET | `/admin/backups` |
| AD22 | POST | `/admin/backups/db` |
| AD23 | POST | `/admin/backups/files` |
| AD24 | POST | `/admin/backups/<id>/restore` |
| AD25 | POST | `/admin/backups/enforce-retention` |

**Total endpoints: 80**

---

## API Test Mapping Table

All tests use Flask's `app.test_client()` with in-memory SQLite. No transport mocking. Business logic executes end-to-end. Classification: **True No-Mock HTTP** throughout.

| ID | Method | Path | Covered | Type | Evidence |
|---|---|---|---|---|---|
| C1 | GET | `/` | No | — | No test found |
| C2 | GET | `/media/<path>` | Yes | True no-mock | `API_tests/test_content_api.py::TestMediaAccess` |
| C3 | GET | `/health` | **No** | — | No test found in any suite |
| A1 | GET | `/auth/login` | Yes | True no-mock | `test_auth_api.py::TestLoginLogout` |
| A2 | POST | `/auth/login` | Yes | True no-mock | `test_auth_api.py::TestLoginLogout::test_login_success` |
| A3 | POST | `/auth/logout` | Yes | True no-mock | `test_auth_api.py::TestLoginLogout::test_logout` |
| A4 | GET | `/auth/register` | Yes | True no-mock | `test_auth_api.py::TestRegister` |
| A5 | POST | `/auth/register` | Yes | True no-mock | `test_auth_api.py::TestRegister::test_register_success` |
| A6 | GET | `/auth/change-password` | Yes | True no-mock | `test_auth_api.py::TestChangePassword::test_change_password_page_loads_for_authenticated` |
| A7 | POST | `/auth/change-password` | Yes | True no-mock | `test_auth_api.py::TestChangePassword::test_change_password_success` |
| B1 | GET | `/schedule` | Yes | True no-mock | `test_booking_api.py::test_schedule_page_loads` |
| B2 | GET | `/schedule/sessions/<id>` | Yes | True no-mock | `test_booking_api.py::test_session_detail_page_loads` |
| B3 | POST | `/booking/reserve` | Yes | True no-mock | `test_booking_api.py::test_book_session_success` |
| B4 | POST | `/booking/waitlist` | Yes | True no-mock | `test_booking_api.py::test_join_waitlist_success` |
| B5 | POST | `/booking/<id>/cancel` | Yes | True no-mock | `test_booking_api.py::test_cancel_reservation_success` |
| B6 | POST | `/booking/<id>/reschedule` | Yes | True no-mock | `test_booking_api.py::test_reschedule_success` |
| B7 | GET | `/booking/` | Yes | True no-mock | `test_auth_api.py::TestProtectedRoutes` (redirect check) |
| B8 | GET | `/booking/my-bookings` | Yes | True no-mock | `test_booking_api.py::test_my_bookings_page` |
| B9 | POST | `/booking/waitlist/<id>/leave` | Yes | True no-mock | `test_booking_api.py::test_leave_waitlist_success` |
| B10 | GET | `/booking/available-sessions` | Yes | True no-mock | `test_booking_api.py::test_available_sessions_returns_fragment` |
| S1 | GET | `/staff/` | Yes | True no-mock | `test_auth_api.py::TestProtectedRoutes::test_staff_route_without_login` |
| S2 | GET | `/staff/schedule` | Yes | True no-mock | `test_staff_api.py::test_staff_schedule_returns_200` |
| S3 | GET | `/staff/session/<id>/roster` | Yes | True no-mock | `test_staff_api.py::test_roster_page_returns_200` |
| S4 | POST | `/staff/checkin/<id>` | Yes | True no-mock | `test_staff_api.py::test_checkin_endpoint` |
| S5 | POST | `/staff/no-show/<id>` | Yes | True no-mock | `test_staff_api.py::test_noshow_endpoint` |
| S6 | GET | `/staff/resource-warnings` | Yes | True no-mock | `test_staff_api.py::test_resource_warnings_page` |
| S7 | GET | `/staff/sessions` | **No** | — | No HTTP GET test found |
| S8 | POST | `/staff/sessions` | Yes | True no-mock | `test_staff_api.py::test_create_session_success` |
| S9 | PUT/POST | `/staff/sessions/<id>` | Yes | True no-mock | `test_staff_api.py::TestUpdateSession::test_update_title_succeeds` |
| S10 | POST/DELETE | `/staff/sessions/<id>/delete` | Yes | True no-mock | `test_staff_api.py::TestDeleteSession::test_soft_delete_marks_inactive` |
| S11 | GET | `/staff/resources` | Yes | True no-mock | `test_staff_api.py::test_resources_page_admin_access` |
| S12 | POST | `/staff/resources` | **No** | — | No direct POST /staff/resources test (toggle tests use DB setup, not HTTP create) |
| S13 | POST | `/staff/resources/<id>/toggle` | Yes | True no-mock | `test_staff_api.py::test_resource_toggle_flips_active_state` |
| S14 | GET | `/staff/pending-approvals` | Yes | True no-mock | `test_staff_api.py::test_pending_approvals_page` |
| S15 | POST | `/staff/approve/<id>` | Yes | True no-mock | `test_staff_api.py::test_approve_endpoint` |
| S16 | POST | `/staff/deny/<id>` | Yes | True no-mock | `test_staff_api.py::test_deny_endpoint` |
| S17 | GET | `/staff/credit-dashboard` | Yes | True no-mock | `test_analytics_api.py::TestCreditDashboard::test_staff_can_view` |
| S18 | GET | `/staff/credit-dashboard/<id>` | Yes | True no-mock | `test_analytics_api.py::TestCreditDashboard::test_credit_history_page` |
| CO1 | GET | `/content/index` | **No** | — | No test found |
| CO2 | GET | `/content/` | Yes | True no-mock | `test_content_api.py::TestPublicBrowse::test_browse_content_public` |
| CO3 | GET | `/content/<id>` | Yes | True no-mock | `test_content_api.py::TestPublicBrowse::test_content_view_published` |
| CO4 | GET | `/content/editor` | Yes | True no-mock | `test_content_api.py::TestEditorAccess::test_editor_dashboard_accessible_by_editor` |
| CO5 | GET | `/content/editor/new` | Yes | True no-mock | `test_content_api.py::TestEditorAccess::test_new_form_accessible_by_editor` |
| CO6 | GET | `/content/editor/<id>/edit` | Yes | True no-mock | `test_content_api.py::TestEditorAccess::test_edit_form_requires_ownership` |
| CO7 | POST | `/content/editor/save` | Yes | True no-mock | `test_content_api.py::TestSaveContent::test_create_content_success` |
| CO8 | POST | `/content/<id>/submit-review` | Yes | True no-mock | `test_content_api.py::TestWorkflowEndpoints::test_submit_for_review` |
| CO9 | POST | `/content/<id>/publish` | Yes | True no-mock | `test_content_api.py::TestWorkflowEndpoints::test_publish_content` |
| CO10 | POST | `/content/<id>/reject` | Yes | True no-mock | `test_content_api.py::TestWorkflowEndpoints::test_reject_content` |
| CO11 | GET | `/content/<id>/history` | Yes | True no-mock | `test_content_api.py::TestVersionHistory::test_version_history` |
| CO12 | POST | `/content/<id>/rollback/<ver>` | Yes | True no-mock | `test_content_api.py::TestVersionHistory::test_rollback_via_api` |
| CO13 | DELETE | `/content/editor/<id>` | Yes | True no-mock | `test_content_api.py::TestContentDeletion::test_owner_can_delete_own_content` |
| CO14 | POST | `/content/preview` | Yes | True no-mock | `test_content_api.py::TestMarkdownPreview::test_markdown_preview_endpoint` |
| CO15 | GET | `/content/categories` | Yes | True no-mock | `test_content_api.py::TestCategories::test_categories_endpoint` |
| CO16 | GET | `/content/filters` | Yes | True no-mock | `test_content_api.py::TestFilterManagement::test_filters_page_accessible_by_admin` |
| CO17 | POST | `/content/filters` | Yes | True no-mock | `test_content_api.py::TestFilterManagement::test_create_keyword_filter` |
| CO18 | POST | `/content/filters/<id>/toggle` | Yes | True no-mock | `test_content_api.py::TestFilterManagement::test_toggle_filter` |
| CO19 | DELETE | `/content/filters/<id>` | Yes | True no-mock | `test_content_api.py::TestFilterManagement::test_delete_filter` |
| R1 | GET | `/reviews/` | **No** | — | No test hits this path directly (redirect only) |
| R2 | GET | `/reviews/new/<id>` | **No** | — | No test found |
| R3 | POST | `/reviews` | Yes | True no-mock | `test_reviews_api.py::TestSubmitReview::test_submit_success` |
| R4 | GET | `/reviews/session/<id>` | Yes | True no-mock | `test_reviews_api.py::TestSessionReviewsPublic::test_returns_200` |
| R5 | GET | `/reviews/my-reviews` | Yes | True no-mock | `test_reviews_api.py::TestMyReviews::test_my_reviews_authenticated` |
| R6 | PUT | `/reviews/<id>` | **No** | — | No HTTP PUT test; unit tests only (`unit_tests/test_reviews.py:387`) |
| R7 | DELETE | `/reviews/<id>` | Yes | True no-mock | `test_reviews_api.py::TestDeleteReview::test_author_can_delete` |
| R8 | POST | `/reviews/<id>/appeal` | Yes | True no-mock | `test_reviews_api.py::TestFileAppealAPI::test_file_appeal_success` |
| AN1 | GET | `/analytics/` | **No** | — | No test found |
| AN2 | POST | `/analytics/event` | Yes | True no-mock | `test_analytics_api.py::TestTrackEvent::test_returns_204` |
| AN3 | POST | `/analytics/heartbeat` | Yes | True no-mock | `test_content_api.py::TestHeartbeat::test_heartbeat_endpoint` |
| AD1 | GET | `/admin/` | Yes | True no-mock | `test_auth_api.py::TestProtectedRoutes` (redirect/auth check) |
| AD2 | GET | `/admin/appeals` | Yes | True no-mock | `test_admin_appeals_api.py::TestAppealsDashboard::test_admin_can_access` |
| AD3 | POST | `/admin/appeals/<id>/resolve` | Yes | True no-mock | `test_admin_appeals_api.py::TestResolveAppeal::test_uphold_appeal_returns_200` |
| AD4 | GET | `/admin/dashboard` | Yes | True no-mock | `test_analytics_api.py::TestAdminDashboard::test_admin_returns_200` |
| AD5 | GET | `/admin/reports/export` | Yes | True no-mock | `integration_tests/test_flows.py::TestAnalyticsDashboardFlow` |
| AD6 | POST | `/admin/reports/generate` | Yes | True no-mock | `test_analytics_api.py::TestExportCSV::test_csv_download` |
| AD7 | GET | `/admin/diagnostics` | Yes | True no-mock | `test_ops_api.py::TestDiagnosticsRoute::test_admin_gets_200` |
| AD8 | GET | `/admin/diagnostics/metrics` | Yes | True no-mock | `test_ops_api.py::TestDiagnosticsRoute::test_metrics_partial_htmx` |
| AD9 | GET | `/admin/diagnostics/errors` | Yes | True no-mock | `test_ops_api.py::TestDiagnosticsRoute::test_errors_page_returns_200` |
| AD10 | GET | `/admin/diagnostics/slow` | Yes | True no-mock | `test_ops_api.py::TestDiagnosticsRoute::test_slow_page_returns_200` |
| AD11 | GET | `/admin/diagnostics/client-logs` | Yes | True no-mock | `test_ops_api.py::TestDiagnosticsRoute::test_client_logs_page_returns_200` |
| AD12 | GET | `/admin/alerts` | Yes | True no-mock | `test_ops_api.py::TestAlertsAPI::test_list_alerts_admin` |
| AD13 | POST | `/admin/alerts` | Yes | True no-mock | `test_ops_api.py::TestAlertsAPI::test_create_alert_htmx` |
| AD14 | POST | `/admin/alerts/<id>/toggle` | Yes | True no-mock | `test_ops_api.py::TestAlertsAPI::test_toggle_alert` |
| AD15 | DELETE | `/admin/alerts/<id>` | Yes | True no-mock | `test_ops_api.py::TestAlertsAPI::test_delete_alert` |
| AD16 | GET | `/admin/flags` | Yes | True no-mock | `test_ops_api.py::TestFlagsAPI::test_list_flags_admin` |
| AD17 | POST | `/admin/flags` | Yes | True no-mock | `test_ops_api.py::TestFlagsAPI::test_create_flag_htmx` |
| AD18 | POST | `/admin/flags/<name>/toggle` | Yes | True no-mock | `test_ops_api.py::TestFlagsAPI::test_toggle_flag` |
| AD19 | POST | `/admin/flags/<name>/canary` | **No** | — | No test found |
| AD20 | DELETE | `/admin/flags/<name>` | Yes | True no-mock | `test_ops_api.py::TestFlagsAPI::test_delete_flag` |
| AD21 | GET | `/admin/backups` | Yes | True no-mock | `test_ops_api.py::TestBackupsAPI::test_list_backups_admin` |
| AD22 | POST | `/admin/backups/db` | Yes | True no-mock | `test_ops_api.py::TestBackupsAPI::test_backup_db_in_memory_shows_error` |
| AD23 | POST | `/admin/backups/files` | **No** | — | No test found |
| AD24 | POST | `/admin/backups/<id>/restore` | Yes | True no-mock | `test_ops_api.py::TestBackupsAPI::test_restore_files_backup_marks_validated` |
| AD25 | POST | `/admin/backups/enforce-retention` | Yes | True no-mock | `test_ops_api.py::TestBackupsAPI::test_retention_endpoint_defaults_to_30` |

---

## Coverage Summary

| Metric | Count |
|---|---|
| Total endpoints | 80 |
| Endpoints with HTTP tests | 69 |
| Endpoints with TRUE no-mock HTTP tests | 69 |
| Uncovered endpoints | 11 |

**HTTP Coverage: 86.25%**  
**True No-Mock API Coverage: 86.25%**

### Uncovered Endpoints (11)

| Endpoint | Severity | Notes |
|---|---|---|
| GET `/` (app root) | Low | Trivial redirect; low risk |
| GET `/health` | **High** | Documented in README as primary verification; no test at any level |
| GET `/content/index` | Low | Alias redirect to `/content/` |
| GET `/reviews/` | Low | Redirect to `/reviews/my-reviews`; not directly tested |
| GET `/reviews/new/<id>` | Medium | Review eligibility form; key UX path; no test at any level |
| PUT `/reviews/<id>` | **High** | Update review; unit-tested only; no HTTP-level test |
| GET `/analytics/` | Medium | Staff analytics index; no test |
| POST `/staff/resources` | Medium | Resource creation; no direct HTTP test |
| GET `/staff/sessions` | Medium | Admin session list page (GET); only POST tested |
| POST `/admin/flags/<name>/canary` | Medium | Canary flag assignment; no HTTP test |
| POST `/admin/backups/files` | Medium | File backup trigger; symmetric with tested `backups/db` |

---

## API Test Classification

**All 544 collected tests are either True No-Mock HTTP or Non-HTTP unit tests.**

- **True No-Mock HTTP:** All files in `API_tests/` and `integration_tests/` — Flask `test_client()`, real app, in-memory SQLite, real business logic.
- **Non-HTTP (unit):** All files in `unit_tests/` — direct service function calls, no HTTP layer.
- **HTTP with mocking:** None detected.

---

## Mock Detection

| Location | Usage | Verdict |
|---|---|---|
| `unit_tests/test_auth.py:7` | `from unittest.mock import patch` imported but no `@patch` or `with patch` applied in any test function | Not applied — safe |
| `unit_tests/test_ops.py:247,281` | `monkeypatch.setattr(backup_service, "_backup_dir", ...)` | Filesystem path only; business logic unaffected — acceptable |
| `API_tests/test_ops_api.py:365,400` | Same `_backup_dir` monkeypatch | Filesystem path only — acceptable |
| `unit_tests/test_config.py:16–30` | `monkeypatch.delenv/setenv("SECRET_KEY")` | Environment variable only — acceptable |

**No service, controller, or transport-layer mocking found anywhere.**

---

## Unit Test Summary

| File | Services / Modules Covered |
|---|---|
| `unit_tests/test_analytics.py` (37 tests) | `analytics_service`, `credit_service`, `data_retention_service` |
| `unit_tests/test_auth.py` (20 tests) | `auth_service` (authenticate, register, hash/verify, lockout, change_password) |
| `unit_tests/test_booking.py` (23 tests) | `booking_service` (reserve, cancel, reschedule, waitlist, conflict detection) |
| `unit_tests/test_config.py` (7 tests) | `app/config.py` (ProductionConfig._validate, config class defaults) |
| `unit_tests/test_content.py` (44 tests) | `content_service`, `file_service`, `content_filter_service` |
| `unit_tests/test_ops.py` (29 tests) | `ops_service`, `feature_flag_service`, `backup_service` |
| `unit_tests/test_reviews.py` (37 tests) | `review_service` (submit, update, delete, appeal, eligibility) |
| `unit_tests/test_staff.py` (24 tests) | `staff_service` (checkin, no-show, roster, resource conflicts, session CRUD) |

### Modules NOT Directly Unit-Tested

| Module | Coverage Status |
|---|---|
| `app/utils/decorators.py` (`login_required`, `role_required`) | Covered indirectly via API tests; no isolated unit test |
| `app/utils/middleware.py` (request logging, latency tracking) | No direct unit test |
| `app/cli.py` (`seed admin`, `seed demo`) | `credit-recalc` and `data-cleanup` verified via `test_analytics_api.py::TestCreditRecalcCLI`; seed commands untested |

---

## API Observability Check

**Strong (request + response + DB state verified):**
- `test_booking_api.py::test_book_session_success` — POST with `session_id`, 201, DB query for confirmed Reservation
- `test_reviews_api.py::TestSubmitReview::test_submit_success` — POST with body, 201, DB query for Review (`rating==5, status=="active"`)
- `test_admin_appeals_api.py::test_uphold_appeal_deducts_dispute_credit` — POST resolve, DB query for CreditHistory (`points==-5`)
- `test_ops_api.py::TestDiagnosticsRoute::test_client_logs_excludes_server_entries` — inserts two log entries, asserts one absent and one present
- `test_staff_api.py::TestDeleteSession::test_reservations_survive_soft_delete` — soft delete, queries Reservation for survival

**Weak (status-code-only, no content check):**
- `test_staff_api.py::test_resources_page_admin_access` — 200 only
- `test_staff_api.py::test_resource_warnings_page` — 200 only
- `test_content_api.py::TestCategories::test_categories_endpoint` — 200 only
- `test_booking_api.py::test_available_sessions_returns_fragment` — 200 only
- `test_analytics_api.py::TestAdminDashboard::test_date_range_filter` — 200 only

---

## Test Quality & Sufficiency

**Success paths:** All major CRUD operations covered. Confirmed for: booking, cancellation, waitlist, checkin, no-show, review submission, content editorial workflow, appeal resolution, alert CRUD, flag CRUD, backup restore, session update/soft-delete, resource toggle.

**Failure cases:** Well covered. Duplicate booking → 409 + message body; invalid rating → 400 + bounds message; content filter rejection → 400 + keyword in body; wrong-user cancel → 403 + message.

**Edge cases covered:** Waitlist position compaction, booking conflict exact boundary (end==start → no conflict), credit floor/cap, 12h cancellation breach window, `enforce_retention` type separation, ProductionConfig SECRET_KEY validation.

**Auth/permissions:** Comprehensive. Every admin-only route tested with non-admin (→ 302/403). Object-level authorization tested (other-user reservation cancel, non-owner checkin, non-owner content delete, non-owner rollback).

**`run_tests.sh`:** Docker-first (default `TEST_RUNTIME=docker`). Hard-fails with actionable message when Docker unavailable. Local fallback is explicit opt-in only. **COMPLIANT.**

---

## End-to-End Assessment

**Project type:** Fullstack (server-rendered HTML + HTMX). No browser-based E2E tests (no Playwright/Cypress). HTMX fragment rendering is validated via `HX-Request: true` headers in API tests — appropriate substitute for this architecture. `integration_tests/test_flows.py` covers 7 multi-step user flows (booking, review+appeal, content editorial, analytics, waitlist promotion, password change, admin operations). This partially compensates for the absence of true browser E2E.

---

## Tests Check

| Check | Result |
|---|---|
| Docker-based test runner | PASS — `run_tests.sh` defaults to Docker |
| No local runtime dependency | PASS — hard error if Docker unavailable |
| Real app bootstrapped in API tests | PASS — `app.test_client()` throughout |
| No service/controller mocking | PASS — confirmed by grep |
| DB state verified in API tests | PASS (majority) — 5 weak status-only tests remain |
| Auth enforcement tested | PASS — all role boundaries have tests |
| Integration flows present | PASS — 7 flows in `integration_tests/test_flows.py` |

---

## Test Coverage Score

**Score: 92 / 100**

### Score Rationale

| Category | Weight | Points | Notes |
|---|---|---|---|
| HTTP endpoint coverage (69/80 = 86%) | 25 pts | 22 | 11 endpoints uncovered; 7 are trivial redirects or low-severity |
| True no-mock API testing | 20 pts | 20 | Zero service/transport mocking confirmed |
| Test depth (assertions beyond status code) | 20 pts | 18 | Strong majority; 5 status-only tests noted |
| Unit test completeness | 20 pts | 19 | All 14 service modules covered; middleware/CLI seeds not directly unit-tested |
| Edge cases & failure paths | 15 pts | 13 | Strong; PUT /reviews HTTP missing; /health 503 path untested |
| **Total** | **100** | **92** | |

### Key Gaps (Priority Order)

1. **`GET /health` — zero tests** (`app/__init__.py:230`). README documents this as the primary verification curl command. Both the 200 (healthy) and 503 (DB unreachable) paths are untested.

2. **`PUT /reviews/<id>` — no HTTP test** (`app/blueprints/reviews.py:166`). `update_review()` is tested at unit level (`unit_tests/test_reviews.py:387–420`) but the route-level auth enforcement, content-filter re-evaluation, and response format are not verified via HTTP.

3. **`POST /admin/backups/files` — no test** (`app/blueprints/admin.py:511`). Symmetric with the tested `POST /admin/backups/db`. Filesystem ZIP operation is untested at HTTP level.

4. **`GET /reviews/new/<id>` — no test** (`app/blueprints/reviews.py:57`). The review eligibility form page is a key user path between completing a session and submitting a review; eligibility checks at HTTP level are unverified.

5. **`GET /staff/sessions` — no test** (`app/blueprints/staff.py:230`). Admin session list (GET) is untested; only creation (POST) is covered.

6. **`POST /admin/flags/<name>/canary` — no test** (`app/blueprints/admin.py:448`). Canary flag management has service-level tests but no HTTP-level test.

7. **5 weak API tests** (status-code-only): `test_resources_page_admin_access`, `test_resource_warnings_page`, `test_categories_endpoint`, `test_available_sessions_returns_fragment`, `test_date_range_filter`.

### Confidence & Assumptions

- Endpoint count (80) derived from static `grep -n "bp\.route"` on all 8 blueprint files plus `app/__init__.py`.
- Routes registered with multiple methods (e.g., `methods=["PUT", "POST"]`) counted as one entry since they share a handler.
- `GET /` and redirect-only routes are included in the uncovered count but weighted low.
- `run_tests.sh` assessed from source; not executed.
- README test counts are compared against `pytest --collect-only` output (544).

---

# PART 2: README AUDIT

---

## Project Type Detection

**Detected type: Fullstack Web (server-rendered)**  
Source: `README.md:3` — *"A full-stack wellness studio management platform built with Flask 3, HTMX 2..."*  
Applies: Docker `docker-compose up` required, URL + port required, demo credentials required for all roles.

---

## README Location

`/home/leul/Documents/task-7/repo/README.md` — **EXISTS. PASS.**

---

## Hard Gate Assessment

### Gate 1: Formatting
**PASS.** Clean GitHub-flavored Markdown. Table of Contents with anchor links (`README.md:7–19`). Section headers are consistent (H2 throughout). Tables properly formatted. No broken syntax detected.

---

### Gate 2: Startup Instructions — Docker
**PASS.**  
`README.md:128`:
```bash
docker compose up --build
```
Includes optional `SECRET_KEY` export. `entrypoint.sh` runs `flask db upgrade` + `flask seed admin` automatically on first container start — no manual DB setup required.

---

### Gate 3: Access Method
**PASS.**  
`README.md:130`: *"The app is available at http://localhost:5000."*  
Port 5000 explicitly stated. `HOST_PORT` environment variable documented (`README.md:153`) for customization.

---

### Gate 4: Verification Method
**PARTIAL PASS.**  
`README.md:297–300`:
```bash
curl http://localhost:5000/health
# {"status": "healthy", "timestamp": "...", "database": "connected"}
```
Curl example for health endpoint is present. No UI walkthrough (login → dashboard) provided. For an HTML-rendering app, this is the minimum acceptable verification path, but it is incomplete without a browser login example. **Flagged as medium priority.**

---

### Gate 5: Environment Rules (Docker path)
**PASS.** Docker path requires only `docker compose up --build`. No `npm install`, `pip install`, `apt-get`, or manual DB migration in the Docker workflow.

**VIOLATION (Local path only):** `README.md:95–107` instructs:
```bash
python3 -m venv venv
pip install -r requirements.txt
flask db upgrade
flask seed admin
```
Manual `pip install` and `flask db upgrade` in the "Quick Start (Local)" section. This section is secondary to Docker but explicitly present and will be followed by contributors. **Flagged as medium priority.**

---

### Gate 6: Demo Credentials
**PASS.**  
`README.md:111–117`:

| Username | Password | Role |
|---|---|---|
| `admin` | `Admin12345!` | Admin |
| `customer1`–`customer5` | `Demo12345!` | Customer |
| `alice_staff` | `Demo12345!` | Staff |
| `editor_user` | `Demo12345!` | Editor |

All four roles documented. Notes that customer/staff/editor require `flask seed demo`. **PASS.**

---

## Engineering Quality

| Area | Verdict | Notes |
|---|---|---|
| Tech stack clarity | **Strong** | Full table at `README.md:39–48`: Flask 3.1, SQLAlchemy 2, HTMX 2, Tailwind, Gunicorn, Docker, pytest |
| Architecture explanation | **Weak** | Project structure tree present (`README.md:54–79`); no service-layer diagram or explanation of blueprint/service/model separation |
| Testing instructions | **Adequate** | `./run_tests.sh` with suite options documented; test breakdown table present but counts are **stale** (437 stated vs 544 actual) |
| Security/roles | **Strong** | Role capabilities table; `SECRET_KEY` warning; `ProductionConfig` behavior noted |
| Workflows | **Strong** | CLI commands for seeding, credit recalc, data cleanup, backups, cron scheduling examples |
| Presentation quality | **Good** | Well-organized, scannable sections; could link to `docs/api-spec.md` earlier |

---

## High Priority Issues

1. **Stale test counts** (`README.md:69,271–274`): States "~36 tests" for API suite, 193 for unit, 25 for integration, 437 total. Actual collected count is **544** (pytest --collect-only output). This misinforms contributors and reviewers about the project's test maturity.

2. **`GET /health` is the stated verification method but has zero tests** (cross-referenced from coverage audit). A README that directs users to verify via `curl /health` while the endpoint has no automated test creates a documentation-reality gap.

---

## Medium Priority Issues

1. **Local Quick Start section instructs `pip install` and manual DB migration** (`README.md:95–107`). This violates the Docker-first environment rule for contributors following the local path. The section should either be removed, replaced with a Docker-only path, or clearly labeled as unsupported/unofficial.

2. **No browser-based verification walkthrough**. The curl example only confirms the health endpoint. A one-step "Log in at http://localhost:5000 with admin/Admin12345! → navigate to /admin/dashboard" would confirm the full application stack is functional.

3. **No architecture overview inline**. The README defers to `docs/design.md` (referenced at `README.md:73`) but provides no brief inline explanation of the service-layer pattern or HTMX interaction model. New contributors must locate and read an external document to understand the codebase structure.

---

## Low Priority Issues

1. **`docs/api-spec.md` referenced once with no description** (`README.md:293`). A brief description ("full endpoint reference with request/response schemas") would reduce friction.

2. **Crontab example hardcodes `/opt/studioops`** (`README.md:227–228`). Should note this is an example path requiring substitution.

3. **`GUNICORN_WORKERS` default is 2** (`README.md:154`). README does not note the standard formula (`2 * num_cpus + 1`) or warn that 2 workers is insufficient for production load.

---

## Hard Gate Failures

| Gate | Status | Notes |
|---|---|---|
| README exists at repo root | PASS | `/README.md` present |
| Clean markdown formatting | PASS | Valid GFM |
| `docker compose up` present | PASS | `README.md:128` |
| URL + port documented | PASS | `http://localhost:5000` |
| Verification method present | PASS (partial) | curl `/health` example present; no UI flow |
| No manual installs in Docker path | PASS | Docker path is clean |
| Demo credentials — all roles | PASS | All 4 roles with username/password |

**No hard gate failures on the primary Docker path.**

---

## README Verdict

**PARTIAL PASS**

The Docker startup path is complete and compliant. All credentials are documented. The README is production-presentable. It fails partial compliance on:

- **Stale test count figures** (states 437, actual 544) — actively misleads reviewers
- **Local Quick Start violates environment rules** (`pip install`, `flask db upgrade` present)
- **Verification method is minimal** (curl only; no UI login flow)
- **Architecture explanation deferred entirely to external file** (no inline overview)

---

# Final Summary

| Audit | Result |
|---|---|
| **Test Coverage Score** | **92 / 100** |
| **README Verdict** | **PARTIAL PASS** |

### Top 3 Cross-Audit Remediation Items

1. **Add `GET /health` test** — closes the highest-severity coverage gap and validates the README's stated verification method simultaneously.
2. **Correct README test counts** — change "~36 tests / 193 / 25 / 437" to the actual values derived from `pytest --collect-only`.
3. **Add HTTP test for `PUT /reviews/<id>`** — the only endpoint with service-level unit coverage but no API-level route test.
