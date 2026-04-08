# StudioOps

A full-stack wellness studio management platform built with **Flask 3**, **HTMX 2**, **SQLAlchemy 2**, and **Tailwind CSS**. StudioOps handles bookings, credit scoring, staff operations, content management, analytics, and system observability — all from a single-page-feel UI with zero custom JavaScript outside of HTMX.

---

## Table of Contents

1. [Features](#features)
2. [Tech Stack](#tech-stack)
3. [Project Structure](#project-structure)
4. [Quick Start (Local)](#quick-start-local)
5. [Docker](#docker)
6. [Configuration](#configuration)
7. [CLI Commands](#cli-commands)
8. [User Roles](#user-roles)
9. [Running Tests](#running-tests)
10. [API Overview](#api-overview)

---

## Features

| Area | Capabilities |
|---|---|
| **Booking** | Browse schedule, reserve / cancel / reschedule sessions, waitlist with auto-promotion |
| **Credit** | Score-based system (0–200); on-time +2, late-cancel −1, no-show −3, dispute upheld −5; nightly recalc |
| **Reviews** | Post-session reviews (1–5 stars), dispute appeals with 5-business-day deadline |
| **Staff** | Roster management, check-in, no-show marking, session CRUD, resource conflict detection |
| **Content** | Draft → Review → Published workflow, version history, rollback, content filters |
| **Analytics** | Page views, booking funnel, dwell time, booking trends, monthly rollup |
| **Admin** | Appeals resolution, analytics dashboard, CSV/JSON export, feature flags, backups, diagnostics |
| **Observability** | Request logging, error rate / latency metrics, `/health` endpoint, client-error capture |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | Flask 3.1 |
| Database | SQLAlchemy 2 / SQLite (swappable via `DATABASE_URL`) |
| Migrations | Flask-Migrate (Alembic) |
| Auth | Flask-Login + Flask-WTF CSRF |
| Frontend | HTMX 2.0 + Tailwind CSS CDN |
| Server | Gunicorn (production) |
| Container | Docker + Docker Compose |
| Testing | pytest + pytest-flask |

---

## Project Structure

```
studioops/
├── app/
│   ├── __init__.py          # Application factory (create_app)
│   ├── cli.py               # flask seed admin|demo commands
│   ├── config.py            # Development / Testing / Production configs
│   ├── extensions.py        # db, login_manager, csrf, migrate singletons
│   ├── blueprints/          # auth, booking, staff, content, reviews, analytics, admin
│   ├── models/              # user, studio, content, review, analytics, ops
│   ├── services/            # Business-logic layer (one module per domain)
│   ├── utils/               # decorators, middleware, error handlers
│   ├── templates/           # Jinja2 templates + HTMX partials
│   └── static/css/          # Minimal custom CSS (Tailwind CDN handles the rest)
├── migrations/              # Alembic migration scripts
├── unit_tests/              # Service-layer unit tests (~310 tests)
├── API_tests/               # Blueprint-level HTTP tests (~36 tests)
├── integration_tests/       # End-to-end flow tests (25 tests)
├── docs/
│   ├── design.md            # Architecture and design decisions
│   └── api-spec.md          # Full HTTP endpoint reference
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh
├── requirements.txt
└── run_tests.sh
```

---

## Quick Start (Local)

### Prerequisites

- Python 3.10+
- pip

### Setup

```bash
git clone <repo-url>
cd studioops

python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt

export FLASK_APP=app
export FLASK_ENV=development

flask db upgrade                # create / migrate the database
flask seed admin                # create the admin account
flask seed demo                 # (optional) load full demo dataset
flask run
```

Open http://localhost:5000 and log in with:

| Username | Password | Role |
|---|---|---|
| `admin` | `Admin12345!` | Admin |
| `customer1`–`customer5` | `Demo12345!` | Customer (requires `flask seed demo`) |
| `alice_staff` | `Demo12345!` | Staff (requires `flask seed demo`) |
| `editor_user` | `Demo12345!` | Editor (requires `flask seed demo`) |

---

## Docker

```bash
# Optional: set a strong secret key
export SECRET_KEY="my-secure-key"

docker compose up --build
```

The app is available at http://localhost:5000. On first start, `entrypoint.sh` automatically runs `flask db upgrade` and `flask seed admin`.

To load demo data inside the container:

```bash
docker compose exec web flask seed demo
```

### Volumes

| Volume | Purpose |
|---|---|
| `studioops_db` | SQLite database file |
| `studioops_uploads` | User-uploaded content |
| `studioops_backups` | Database and file backups |
| `studioops_logs` | Application logs |

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | `change-me-in-production` | Flask session signing key — **change in production** |
| `DATABASE_URL` | `sqlite:////data/db/studioops.db` | SQLAlchemy connection string |
| `HOST_PORT` | `5000` | Host port mapped to container port 5000 |
| `GUNICORN_WORKERS` | `2` | Gunicorn worker processes |
| `GUNICORN_TIMEOUT` | `120` | Gunicorn request timeout (seconds) |

---

## Configuration

Selected by the `FLASK_ENV` environment variable:

| `FLASK_ENV` | Config class | Notes |
|---|---|---|
| `development` (default) | `DevelopmentConfig` | `DEBUG=True`, dev SQLite DB |
| `testing` | `TestingConfig` | In-memory SQLite, CSRF disabled |
| `production` | `ProductionConfig` | `DEBUG=False`, secure cookies required |

Additional settings (all accept environment-variable overrides):

```
SECRET_KEY            Flask session secret key
DATABASE_URL          Production SQLAlchemy URI
DEV_DATABASE_URL      Development SQLAlchemy URI
UPLOAD_FOLDER         Absolute path for uploads  (default: ./uploads)
LOG_DIR / LOG_FILE    Logging directory and file
MAX_LOGIN_ATTEMPTS    Lockout threshold          (default: 5)
LOCKOUT_MINUTES       Lockout window             (default: 15)
```

---

## CLI Commands

All commands require `FLASK_APP=app` in the environment.

### Seeding

```bash
flask seed admin           # Create default admin account (idempotent)
flask seed demo            # Load full demo dataset: users, sessions, reviews, content (idempotent)
```

### Credit scoring

```bash
flask credit-recalc        # Recalculate all customer credit scores
flask credit-recalc -v     # Verbose output
```

### Data retention

```bash
flask data-cleanup                  # Aggregate events >90d into monthly summaries; prune raw data
flask data-cleanup --dry-run        # Preview — no data is deleted
```

### Backups

```bash
flask backup-db                              # Copy SQLite DB to backups/
flask backup-files                           # ZIP uploads/ to backups/
flask backup-list                            # List all backup records
flask backup-restore <id>                    # Mark a backup as the restore target
flask backup-restore <id> --promote          # Apply backup (replaces live DB — destructive)
flask backup-enforce-retention               # Keep last 30 backups per type (configurable)
flask backup-enforce-retention --max-backups 10
```

#### Automated scheduling

The CLI commands above can be driven by the system cron daemon. Add entries to
`crontab -e` (substituting your actual install path and virtualenv):

```cron
# Daily database snapshot at 02:00
0 2 * * * cd /opt/studioops && venv/bin/flask backup-db && venv/bin/flask backup-enforce-retention

# Hourly uploaded-file sync
0 * * * * cd /opt/studioops && venv/bin/flask backup-files
```

Set `FLASK_APP=app` and any other required environment variables in the crontab
or in a sourced `.env` file so Flask can locate the application.

---

## User Roles

| Role | Pages accessible |
|---|---|
| `customer` | Schedule, My Bookings, Reviews |
| `staff` | All customer pages + Staff panel, analytics |
| `editor` | All customer pages + Content editor |
| `admin` | Everything — admin panel, appeals, feature flags, backups, diagnostics |

---

## Running Tests

```bash
# Run all suites (prefers Docker by default)
./run_tests.sh

# Run a specific suite
./run_tests.sh unit
./run_tests.sh api
./run_tests.sh integration

# Force local virtualenv runtime instead of Docker
STUDIOOPS_TEST_RUNTIME=local ./run_tests.sh

# Direct pytest
python3 -m pytest unit_tests/ API_tests/ integration_tests/ -v
```

**Test breakdown:**

| Suite | Count | What it covers |
|---|---|---|
| `unit_tests/` | 193 | Service functions, business logic, helpers |
| `API_tests/` | 219 | Blueprint HTTP responses, auth, HTMX partials |
| `integration_tests/` | 25 | End-to-end user flows |
| **Total** | **437** | |

---

## API Overview

All endpoints return HTML (Jinja2-rendered). HTMX requests (`HX-Request: true`) receive HTML fragments for in-place DOM swaps.

| URL prefix | Blueprint | Auth required |
|---|---|---|
| `/auth/login`, `/auth/register` | auth | No |
| `/schedule`, `/booking/*` | booking | Yes (customer+) |
| `/reviews/*` | reviews | Yes (customer+) |
| `/staff/*` | staff | Yes (staff / admin) |
| `/content/*` | content | Yes (editor / admin for writes) |
| `/analytics/*` | analytics | Partial (event tracking is public) |
| `/admin/*` | admin | Yes (admin only) |
| `/health` | core | No |

See [docs/api-spec.md](docs/api-spec.md) for the complete endpoint reference.

### Health endpoint

```bash
curl http://localhost:5000/health
# {"status": "healthy", "timestamp": "2026-01-15T10:30:00", "database": "connected"}
```

Returns HTTP 200 when healthy, 503 when the database is unreachable.
