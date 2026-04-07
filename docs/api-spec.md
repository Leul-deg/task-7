# StudioOps — HTTP API Reference

All endpoints return HTML (Jinja2 templates). When the `HX-Request: true` header is present, endpoints return HTML **fragments** for in-place HTMX DOM swaps instead of full pages.

CSRF is required on all `POST`, `PUT`, `DELETE` requests via either:
- `X-CSRFToken` request header (set automatically by the HTMX config in `base.html`)
- `csrf_token` hidden form field

---

## Auth (`/auth`)

### `GET /auth/login`
Display the login form.

**Response:** `200 OK` — `auth/login.html`

---

### `POST /auth/login`
Authenticate a user.

**Form fields:**

| Field | Type | Required |
|---|---|---|
| `identifier` | string | Yes — username or email |
| `password` | string | Yes |
| `remember` | checkbox | No |

**Responses:**
- `302` → `/` (redirects to schedule) on success
- `200` → login form with validation errors on failure
- `429` — account locked (too many failed attempts)

---

### `GET /auth/register`
Display the registration form.

**Response:** `200 OK` — `auth/register.html`

---

### `POST /auth/register`
Create a new customer account.

**Form fields:**

| Field | Type | Required |
|---|---|---|
| `username` | string | Yes — 3–80 chars, alphanumeric + underscores |
| `email` | string | Yes — valid email |
| `password` | string | Yes — min 10 chars, at least one uppercase letter and one digit |
| `confirm` | string | Yes — must match `password` |

**Responses:**
- `302` → `/schedule` on success
- `200` → registration form with errors on failure

---

### `POST /auth/logout`
End the current session.

**Responses:** `302` → `/auth/login`

---

## Booking (`/`)

### `GET /schedule`
Browse the class schedule for today.

**Query params:**

| Param | Type | Default | Description |
|---|---|---|---|
| `date` | string | today | `MM/DD/YYYY` |

**Auth:** Required

**Response:** `200 OK` — `booking/index.html`

---

### `GET /schedule/sessions/<session_id>`
Session detail card.

**Auth:** Required

**Response:** `200 OK` — full page or HTMX fragment

---

### `POST /booking/reserve`
Book a session.

**Form fields:**

| Field | Required |
|---|---|
| `session_id` | Yes |

**Auth:** Required (customer+)

**Responses:**
- `201 Created` — HTMX booking confirmation fragment
- `400` — session full, already booked, or credit too low
- `409` — duplicate confirmed reservation

---

### `POST /booking/waitlist`
Join the waitlist for a full session.

**Form fields:** `session_id`

**Responses:** `201` success, `400` error fragment

---

### `POST /booking/<reservation_id>/cancel`
Cancel a confirmed reservation.

**Responses:** `200` — status updated; credit penalty applied for late cancellation

---

### `POST /booking/<reservation_id>/reschedule`
Reschedule a reservation to another session.

**Form fields:** `new_session_id`

**Responses:** `200`, `400`

---

### `GET /booking/my-bookings` (also `GET /booking/`)
List the current user's reservations.

**Auth:** Required

**Response:** `200 OK`

---

### `GET /booking/available-sessions`
HTMX partial — list of bookable sessions (used by schedule page).

**Query params:** `date` (MM/DD/YYYY)

---

### `POST /booking/waitlist/<waitlist_id>/leave`
Leave the waitlist.

**Responses:** `200`, `404`

---

## Reviews (`/reviews`)

### `GET /reviews/`
Review overview page (recent session reviews).

**Auth:** Required

---

### `GET /reviews/new/<reservation_id>`
Render the review form for a completed reservation.

**Auth:** Required (must own the reservation)

---

### `POST /reviews`
Submit a review.

**Form fields:**

| Field | Type | Required |
|---|---|---|
| `reservation_id` | integer | Yes |
| `rating` | integer 1–5 | Yes |
| `text` | string | No |
| `tags` | string (comma-separated) | No |

**Auth:** Required — reservation must be `completed` and unreviewed

**Responses:** `201` HTMX fragment, `400` with reason

---

### `GET /reviews/session/<session_id>`
Public list of reviews for a session.

**Response:** `200 OK`

---

### `GET /reviews/my-reviews`
Current user's review history.

**Auth:** Required

---

### `PUT /reviews/<review_id>`
Edit an existing review (author only, within edit window).

**Form fields:** `rating`, `text`, `tags`

**Responses:** `200`, `403`, `404`

---

### `DELETE /reviews/<review_id>`
Soft-delete a review (author or admin).

**Responses:** `200`, `403`, `404`

---

### `POST /reviews/<review_id>/appeal`
File a dispute appeal on a review.

**Form fields:** `reason`

**Auth:** Required — within 5 business days of review creation

**Responses:** `201` HTMX fragment, `400` (deadline passed / ineligible)

---

## Staff (`/staff`)

All staff routes require `role in ['staff', 'admin']`.

### `GET /staff/`
Staff dashboard.

### `GET /staff/schedule`
Staff's own session schedule.

**Query params:** `start`, `end` (MM/DD/YYYY)

### `GET /staff/session/<session_id>/roster`
Attendance roster for a session.

### `POST /staff/checkin/<reservation_id>`
Check in a customer (session must have started).

**Responses:** `200` success, `400` error

### `POST /staff/no-show/<reservation_id>`
Mark a reservation as no-show.

### `GET /staff/resource-warnings`
HTMX partial — resource conflicts for upcoming sessions.

### `GET /staff/sessions`
Session management list.

### `POST /staff/sessions`
Create a new session.

**Form fields:** `title`, `room_id`, `instructor_id`, `start_time`, `end_time`, `capacity`, `equipment_ids`, `description`

### `PUT /staff/sessions/<session_id>`
Update a session.

### `POST /staff/sessions/<session_id>/delete`
Delete (deactivate) a session.

### `GET /staff/resources`
List rooms and equipment.

### `POST /staff/resources`
Create a resource (room or equipment).

### `POST /staff/resources/<resource_id>/toggle`
Toggle a resource's active state.

### `GET /staff/pending-approvals`
List reservations pending staff approval.

### `POST /staff/approve/<reservation_id>`
Approve a reservation.

### `POST /staff/deny/<reservation_id>`
Deny a reservation.

### `GET /staff/credit-dashboard`
Customer credit score summary table.

**Query params:** `status` — `all` | `Normal` | `At Risk` | `Restricted`

### `GET /staff/credit-dashboard/<user_id>`
Credit history for a specific customer.

---

## Content (`/content`)

### `GET /content/` (browse)
Published content library.

**Query params:** `category`, `type`, `q` (search)

### `GET /content/<content_id>`
View a single published content item.

### `GET /content/editor`
Editor dashboard — all content by the current editor.

**Auth:** `editor` or `admin`

### `GET /content/editor/new`
New content form.

### `GET /content/editor/<content_id>/edit`
Edit form for existing content.

### `POST /content/editor/save`
Save a draft or update.

**Form fields:** `content_id` (0 = new), `title`, `content_type`, `body`, `body_format`, `category`, `tags`, `parent_id`

### `POST /content/<content_id>/submit-review`
Submit content for editorial review.

### `POST /content/<content_id>/publish`
Publish content (admin only).

### `POST /content/<content_id>/reject`
Reject content in review.

**Form fields:** `reason`

### `GET /content/<content_id>/history`
Version history list.

### `POST /content/<content_id>/rollback/<version_id>`
Roll back to a previous version.

### `POST /content/preview`
Live preview of Markdown/rich-text body. HTMX only.

### `GET /content/categories`
Category list with counts.

### `GET /content/filters`
Content moderation filter list.

### `POST /content/filters`
Create a keyword or regex filter.

**Form fields:** `pattern`, `filter_type` (`keyword` | `regex`)

### `POST /content/filters/<filter_id>/toggle`
Toggle a filter's active state.

### `DELETE /content/filters/<filter_id>`
Delete a filter.

---

## Analytics (`/analytics`)

### `GET /analytics/`
Analytics index page. Auth: staff / admin.

### `POST /analytics/event`
Track a client-side event. No auth required.

**Form fields:**

| Field | Required |
|---|---|
| `event_type` | Yes (`page_view`, `heartbeat`, `booking_start`, `booking_complete`, `custom`) |
| `page` | No |
| `session_id` | No — browser session identifier |
| `data` | No — JSON string |

**Response:** `204 No Content`

### `POST /analytics/heartbeat`
Record a dwell-time heartbeat. No auth required.

**Form fields:** `page`, `content_id`, `session_id`

**Response:** `204 No Content`

### `POST /analytics/client-error`
Receive a client-side JS error report. CSRF exempt.

**Form fields:** `message`, `stack`, `page`

**Response:** `204 No Content`

---

## Admin (`/admin`)

All admin routes require `role == 'admin'`.

### `GET /admin/`
Admin hub — links to all admin sections.

### `GET /admin/appeals`
Pending review appeals.

### `POST /admin/appeals/<appeal_id>/resolve`
Resolve an appeal.

**Form fields:** `decision` (`upheld` | `rejected`), `resolution_text`

**Response:** HTMX fragment replacing the appeal card.

### `GET /admin/dashboard`
Analytics dashboard with date range filter.

**Query params:** `start`, `end` (MM/DD/YYYY)

### `GET /admin/reports/export`
Report configuration page.

### `POST /admin/reports/generate`
Generate and download a report.

**Form fields:**

| Field | Values |
|---|---|
| `report_type` | `overview`, `trends`, `funnel`, `reviews`, `credit` |
| `format` | `csv`, `json` |
| `start`, `end` | MM/DD/YYYY |

**Response:** File download (`text/csv` or `application/json`)

---

### Diagnostics

### `GET /admin/diagnostics`
Live system health + request metrics. Auto-refreshes every 30 s via HTMX polling.

### `GET /admin/diagnostics/metrics`
HTMX partial — metrics panel only (used by auto-refresh).

### `GET /admin/diagnostics/errors`
Recent ERROR/CRITICAL log entries.

**Query params:** `limit` (default 50)

### `GET /admin/diagnostics/slow`
Slow request log.

**Query params:** `threshold` ms (default 1000)

### `GET /admin/diagnostics/client-logs`
Client-side JS error log.

---

### Alert Thresholds

### `GET /admin/alerts`
List alert thresholds.

### `POST /admin/alerts`
Create an alert threshold.

**Form fields:** `metric` (`error_rate` | `latency_p99` | `disk_usage`), `operator` (`>` `>=` `<` `<=`), `threshold_value`, `window_minutes`

**HTMX response:** Updated `<tbody>` with all rows.

### `POST /admin/alerts/<threshold_id>/toggle`
Toggle `is_active` on a threshold.

**HTMX response:** Updated `<tr>` for the row.

### `DELETE /admin/alerts/<threshold_id>`
Delete a threshold.

**Response:** `200 OK` (empty body; HTMX removes the row via `hx-swap="outerHTML"`)

---

### Feature Flags

### `GET /admin/flags`
List all feature flags.

### `POST /admin/flags`
Create a feature flag.

**Form fields:** `name`, `description`

**HTMX response:** `201 Created` with updated `<tbody>`.

### `POST /admin/flags/<name>/toggle`
Toggle `is_enabled`.

**HTMX response:** Updated `<tr>`.

### `POST /admin/flags/<name>/canary`
Update the canary user ID list.

**Form fields:** `canary_ids` — comma-separated user IDs

**HTMX response:** Updated `<tr>`.

### `DELETE /admin/flags/<name>`
Delete a feature flag.

**Response:** `200 OK`

---

### Backups

### `GET /admin/backups`
Backup management page.

### `POST /admin/backups/db`
Create a database backup.

**HTMX response:** Updated backup rows.

### `POST /admin/backups/files`
Create a file (uploads ZIP) backup.

**HTMX response:** Updated backup rows.

### `POST /admin/backups/<backup_id>/restore`
Mark a backup as the restore target (or promote it).

**Form fields:** `promote` — `"1"` to apply destructively

**HTMX response:** `partials/admin/backup_restored.html`

### `POST /admin/backups/enforce-retention`
Prune old backups.

**Form fields:** `max_backups` (default 7)

**HTMX response:** Updated backup rows.

---

## Core

### `GET /`
Root — redirects to `/schedule` (authenticated) or `/auth/login` (unauthenticated).

### `GET /health`
Health check.

**Response:** `200 OK`
```json
{"status": "healthy", "timestamp": "2026-01-15T10:30:00", "database": "connected"}
```

`503 Service Unavailable` when database is unreachable.

---

## Error Responses

| Code | Meaning |
|---|---|
| `400` | Bad request / validation error |
| `401` | Not authenticated (HTMX: fragment + `HX-Redirect`) |
| `403` | Insufficient role (HTMX: error fragment) |
| `404` | Resource not found |
| `429` | Account locked out |
| `500` | Internal server error |

All error responses are rendered from `app/templates/errors/<code>.html` or as HTMX-swappable fragments from `partials/error_fragment.html`.
