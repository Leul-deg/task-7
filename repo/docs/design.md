# StudioOps — Architecture & Design

## Overview

StudioOps follows a classic **Flask application-factory** pattern with a layered architecture:

```
HTTP Request
    │
    ▼
Blueprint (route handler)   — thin: validate input, call service, render template
    │
    ▼
Service module              — business logic, pure Python functions, returns dicts
    │
    ▼
SQLAlchemy models           — ORM over SQLite (or any SQL backend via DATABASE_URL)
    │
    ▼
Database
```

Each layer has a single responsibility. Blueprints delegate business logic to the service layer; lightweight read queries (e.g. category lookups, existence checks) may appear in blueprint code for convenience. Models never contain business logic.

---

## Application Factory

`create_app(config_name)` in `app/__init__.py` wires together:

1. **Config** — `DevelopmentConfig`, `TestingConfig`, `ProductionConfig` (selected by `FLASK_ENV`)
2. **Extensions** — `db`, `login_manager`, `csrf`, `migrate` (all in `app/extensions.py`)
3. **Models** — imported for Alembic auto-discovery
4. **Blueprints** — registered with URL prefixes
5. **Middleware** — request/response logging via `app/utils/middleware.py`
6. **CLI commands** — seed, credit-recalc, data-cleanup, backup-*
7. **Jinja2 globals/filters** — `now()`, `from_json`, `dt`, `dtime`

---

## Blueprints

| Blueprint | Prefix | Owner role |
|---|---|---|
| `auth_bp` | `/auth` | Public |
| `booking_bp` | `/` | Customer+ |
| `reviews_bp` | `/reviews` | Customer+ |
| `staff_bp` | `/staff` | Staff / Admin |
| `content_bp` | `/content` | Editor / Admin |
| `analytics_bp` | `/analytics` | Partial public |
| `admin_bp` | `/admin` | Admin |

---

## HTMX Integration Pattern

All forms and interactive elements use HTMX for partial updates. The standard pattern is:

```html
<!-- Full-page form -->
<form hx-post="{{ url_for('blueprint.action') }}"
      hx-target="#result-area"
      hx-swap="innerHTML">
  <input type="hidden" name="csrf_token" value="{{ csrf_token() }}" />
  ...
</form>
```

- **CSRF**: every HTMX request includes `X-CSRFToken` via a `htmx:configRequest` listener in `base.html`; forms also include a hidden `csrf_token` field for non-HTMX fallback
- **HX-Redirect**: used by auth decorators to redirect unauthenticated HTMX requests
- **HX-Request detection**: `request.headers.get("HX-Request")` routes to partial templates; absence routes to full pages

---

## Authentication & Authorization

- **Flask-Login** manages sessions (8-hour sliding window via `PERMANENT_SESSION_LIFETIME`)
- **`login_required`** decorator: returns a 401 HTMX fragment + `HX-Redirect` header for HTMX requests; `abort(401)` for plain requests
- **`role_required(*roles)`** decorator: same pattern for 403
- **Account lockout**: `MAX_LOGIN_ATTEMPTS` failed logins within `LOCKOUT_MINUTES` lock the account

---

## Credit Scoring

```
score = clamp(100 + Σ points_from_last_90_days, 0, 200)

Event         Points
─────────────────────
on_time        +2
late_cancel    −1
no_show        −3
dispute_upheld −5
```

Status thresholds:

| Score | Status |
|---|---|
| ≥ 70 | Normal |
| ≥ 40 | At Risk |
| < 40 | Restricted |

The `flask credit-recalc` CLI runs the nightly batch job.

---

## Review Appeals

1. Customer files appeal within **5 business days** of review creation (weekends excluded)
2. Appeal record created with `deadline = created_at + 5 business days`
3. Admin resolves via `POST /admin/appeals/<id>/resolve` with `decision=upheld|rejected`
4. If upheld: review marked `resolved`, credit award (+10) logged
5. Overdue appeals are highlighted in the admin dashboard

---

## Analytics & Data Retention

**Event types**: `page_view`, `heartbeat`, `booking_start`, `booking_complete`, `custom`

**Rate limiting** (enforced in service layer):
- `page_view`: deduplicated if same `session_id` + `page` within 5 seconds
- `heartbeat`: deduplicated if same `session_id` within 14 seconds

**Data retention** (`flask data-cleanup`):
1. Aggregate raw events older than 90 days into `MonthlyAnalyticsSummary`
2. Delete raw `AnalyticsEvent` rows older than 90 days
3. Delete `MonthlyAnalyticsSummary` rows older than 13 months

---

## Observability

### Request logging (`app/utils/middleware.py`)

Every server request creates a `LogEntry` with:
- `request_id` (UUID, propagated via `flask.g`)
- `level`, `source` (`"server"`)
- `endpoint`, `method`, `status_code`, `latency_ms`

### Client-error capture

`base.html` includes an IIFE that catches:
- `window.error` (uncaught JS errors)
- `unhandledrejection` (unhandled promise rejections)
- `htmx:responseError` (HTMX non-2xx responses)

All sent to `POST /analytics/client-error` → `LogEntry(source="client")`.

### Alert thresholds (`admin/alerts`)

`ops_service.check_alerts()` evaluates `AlertThreshold` records against live metrics:
- `error_rate` — `get_request_metrics().error_rate`
- `latency_p99` — `get_request_metrics().p99_latency_ms`
- `disk_usage` — `get_system_health().disk.used_pct`

---

## Feature Flags

Stored in `FeatureFlag` table. Evaluation:

1. Flag not found → `False`
2. `is_enabled=True` → `True` for everyone
3. `is_enabled=False`, `canary_staff_ids=[1,2,3]` → `True` only for those user IDs
4. Otherwise → `False`

Available in Jinja2 templates via `is_feature_enabled(name)` global.

---

## Backup Service

| Command | What it does |
|---|---|
| `backup-db` | `shutil.copy2` of the SQLite file → `backups/db_backup_<ts>.sqlite` |
| `backup-files` | ZIP of `uploads/` → `backups/files_backup_<ts>.zip` |
| `backup-restore <id>` | Validates file exists, marks status `"restored"` |
| `backup-restore <id> --promote` | `engine.dispose()` → save safety copy → overwrite live DB |

---

## Database Models

| Model | Table | Notes |
|---|---|---|
| `User` | `users` | Roles: customer / staff / editor / admin |
| `LoginAttempt` | `login_attempts` | Failed/successful login history |
| `Resource` | `resources` | Rooms and equipment |
| `StudioSession` | `studio_sessions` | Classes with instructor + room |
| `Reservation` | `reservations` | Booking state machine |
| `Waitlist` | `waitlist` | Ordered queue per session |
| `CheckIn` | `check_ins` | Staff-recorded attendance |
| `Content` | `content` | Articles, chapters, books |
| `ContentVersion` | `content_versions` | Immutable version snapshots |
| `ContentAttachment` | `content_attachments` | File uploads (SHA-256 dedup) |
| `ContentFilter` | `content_filters` | Keyword/regex moderation rules |
| `Review` | `reviews` | Post-session ratings |
| `ReviewImage` | `review_images` | Attached media |
| `Appeal` | `appeals` | Dispute records |
| `AnalyticsEvent` | `analytics_events` | Raw event stream |
| `CreditHistory` | `credit_history` | Per-event credit deltas |
| `MonthlyAnalyticsSummary` | `monthly_analytics_summaries` | Aggregated rollup |
| `FeatureFlag` | `feature_flags` | Toggle records |
| `Backup` | `backups` | Backup metadata |
| `LogEntry` | `log_entries` | Server + client log entries |
| `AlertThreshold` | `alert_thresholds` | Metric alert configuration |

---

## Testing Strategy

| Suite | Scope | Fixtures |
|---|---|---|
| `unit_tests/` | Service functions in isolation | In-memory SQLite via `db` fixture |
| `API_tests/` | Blueprint HTTP responses | `client` fixture (full app) |
| `integration_tests/` | End-to-end user flows | Same app + dedicated flow fixtures |

All tests use `scope="function"` fixtures so each test gets a fresh in-memory database.

CSRF is disabled in `TestingConfig`. HTMX requests are simulated by passing `headers={"HX-Request": "true"}`.
