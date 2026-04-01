"""
Seed CLI commands for StudioOps.

  flask seed admin  — create/verify admin user (idempotent)
  flask seed demo   — load full demo dataset (idempotent)

All other CLI commands (credit-recalc, backup-*, data-cleanup) are registered
in their respective service modules and wired up via create_app().
"""
import json
import random
from datetime import datetime, timedelta

import click
from flask import Flask

from app.extensions import db
from app.models.analytics import AnalyticsEvent, CreditHistory
from app.models.content import Content, ContentFilter
from app.models.review import Review
from app.models.studio import Reservation, Resource, StudioSession, Waitlist
from app.models.user import User
from app.services.auth_service import hash_password
from app.services.credit_service import recalculate_credit


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_or_create_user(username, email, role, password="Demo12345!", credit_score=100):
    u = User.query.filter_by(username=username).first()
    if u:
        return u, False
    u = User(
        username=username,
        email=email,
        role=role,
        password_hash=hash_password(password),
        credit_score=credit_score,
    )
    db.session.add(u)
    db.session.flush()
    return u, True


def _get_or_create_resource(name, rtype, capacity, description=None):
    r = Resource.query.filter_by(name=name).first()
    if r:
        return r, False
    r = Resource(type=rtype, name=name, capacity=capacity, description=description)
    db.session.add(r)
    db.session.flush()
    return r, True


# ── seed functions ────────────────────────────────────────────────────────────

def _seed_admin():
    u, created = _get_or_create_user(
        username="admin",
        email="admin@studioops.local",
        role="admin",
        password="Admin12345!",
    )
    db.session.commit()
    if created:
        click.echo("Admin created  → username: admin  password: Admin12345!")
    else:
        click.echo("Admin already exists.")


def _seed_demo():
    click.echo("Seeding demo data …")
    now = datetime.utcnow()

    # ── Users ──────────────────────────────────────────────────────────────────
    staff_specs = [
        ("alice_staff",  "alice@studioops.local",  "staff"),
        ("bob_staff",    "bob@studioops.local",     "staff"),
        ("carol_staff",  "carol@studioops.local",   "staff"),
    ]
    staff_users = [_get_or_create_user(*spec)[0] for spec in staff_specs]

    customer_users = [
        _get_or_create_user(
            f"customer{i}", f"customer{i}@example.com", "customer",
            credit_score=random.choice([80, 90, 100, 110]),
        )[0]
        for i in range(1, 6)
    ]

    editor_user, _ = _get_or_create_user("editor_user", "editor@studioops.local", "editor")
    db.session.flush()

    # ── Resources ─────────────────────────────────────────────────────────────
    rooms = [
        _get_or_create_resource("Studio A",       "room",      20, "Main floor yoga space")[0],
        _get_or_create_resource("Studio B",        "room",      15, "Mid-size practice room")[0],
        _get_or_create_resource("Rooftop Space",   "room",      10, "Open-air rooftop studio")[0],
    ]
    equipment = [
        _get_or_create_resource("Yoga Mats (×20)",  "equipment", 1)[0],
        _get_or_create_resource("Sound System",      "equipment", 1)[0],
        _get_or_create_resource("Foam Rollers (×10)","equipment", 1)[0],
    ]
    db.session.flush()

    # ── Studio sessions ───────────────────────────────────────────────────────
    session_specs = [
        # Past (completed window)
        ("Morning Flow",          staff_users[0], rooms[0], now - timedelta(days=7,  hours=2), 90),
        ("Power Yoga",            staff_users[1], rooms[1], now - timedelta(days=5,  hours=3), 60),
        ("Beginner Breathwork",   staff_users[2], rooms[2], now - timedelta(days=3,  hours=4), 45),
        ("Sunset Stretch",        staff_users[0], rooms[0], now - timedelta(days=1,  hours=5), 60),
        # Upcoming
        ("Noon Vinyasa",          staff_users[1], rooms[0], now + timedelta(days=1,  hours=2), 75),
        ("Weekend Restore",       staff_users[2], rooms[1], now + timedelta(days=3,  hours=3), 90),
        ("Meditation Lab",        staff_users[0], rooms[2], now + timedelta(days=5,  hours=1), 60),
        ("Dynamic Pilates",       staff_users[1], rooms[0], now + timedelta(days=7,  hours=2), 60),
        ("Stress Relief Flow",    staff_users[2], rooms[2], now + timedelta(days=10, hours=4), 75),
    ]

    sessions = []
    for title, instructor, room, start, dur in session_specs:
        s = StudioSession.query.filter_by(
            title=title, instructor_id=instructor.id
        ).first()
        if not s:
            s = StudioSession(
                title=title,
                instructor_id=instructor.id,
                room_id=room.id,
                start_time=start,
                end_time=start + timedelta(minutes=dur),
                capacity=room.capacity,
                equipment_ids=json.dumps([equipment[0].id]),
                is_active=True,
            )
            db.session.add(s)
        sessions.append(s)

    db.session.flush()
    past_sessions     = sessions[:4]
    upcoming_sessions = sessions[4:]

    # ── Reservations ──────────────────────────────────────────────────────────
    # Cycle past reservation statuses for variety
    _status_cycle = ["completed", "completed", "canceled", "no_show", "completed"]
    past_reservations = []

    for ci, customer in enumerate(customer_users):
        for si, sess in enumerate(past_sessions):
            existing = Reservation.query.filter_by(
                user_id=customer.id, session_id=sess.id
            ).first()
            if existing:
                past_reservations.append(existing)
                continue
            status = _status_cycle[(ci + si) % len(_status_cycle)]
            res = Reservation(
                user_id=customer.id,
                session_id=sess.id,
                status=status,
            )
            db.session.add(res)
            past_reservations.append(res)

    # Upcoming: first 3 customers confirm first 2 upcoming sessions
    for customer in customer_users[:3]:
        for sess in upcoming_sessions[:2]:
            if not Reservation.query.filter_by(
                user_id=customer.id, session_id=sess.id
            ).first():
                db.session.add(Reservation(
                    user_id=customer.id,
                    session_id=sess.id,
                    status="confirmed",
                ))

    # Waitlist: last 2 customers on the 3rd upcoming session
    for pos, customer in enumerate(customer_users[3:], start=1):
        if not Waitlist.query.filter_by(
            user_id=customer.id, session_id=upcoming_sessions[2].id
        ).first():
            db.session.add(Waitlist(
                user_id=customer.id,
                session_id=upcoming_sessions[2].id,
                position=pos,
            ))

    db.session.flush()

    # ── Credit history ────────────────────────────────────────────────────────
    _credit_map = {
        "completed": ("on_time",     +5),
        "canceled":  ("late_cancel", -10),
        "no_show":   ("no_show",     -20),
    }
    for res in past_reservations:
        if res.status in _credit_map:
            event_type, points = _credit_map[res.status]
            if not CreditHistory.query.filter_by(
                user_id=res.user_id, reference_id=res.id
            ).first():
                db.session.add(CreditHistory(
                    user_id=res.user_id,
                    event_type=event_type,
                    points=points,
                    reference_id=res.id,
                ))

    db.session.flush()

    # ── Reviews ───────────────────────────────────────────────────────────────
    _review_texts = [
        "Absolutely loved this session — the instructor was brilliant!",
        "Great pace and a wonderful atmosphere. Highly recommend.",
        "Really helpful for my practice. Will definitely be back.",
        "Good session overall, though a little crowded.",
        "Knowledgeable instructor and a spotlessly clean space.",
        "Challenging but rewarding. Exactly what I needed.",
        "The breathwork segment was especially valuable.",
        "Perfect length and a great mix of strength and flexibility.",
    ]
    completed_res = [r for r in past_reservations if r.status == "completed"]
    for idx, res in enumerate(completed_res[:8]):
        if not Review.query.filter_by(reservation_id=res.id).first():
            db.session.add(Review(
                reservation_id=res.id,
                user_id=res.user_id,
                rating=random.choice([3, 4, 4, 5, 5]),
                tags=json.dumps(["yoga", "wellness"]),
                text=_review_texts[idx % len(_review_texts)],
                status="active",
                reviewer_role="customer",
            ))

    db.session.flush()

    # ── Content ───────────────────────────────────────────────────────────────
    _content_specs = [
        ("Introduction to Yoga",               "article", "yoga",        "published"),
        ("Advanced Breathing Techniques",       "article", "breathwork",  "published"),
        ("Studio Etiquette Guide",              "article", "guide",       "published"),
        ("Wellness Programme Overview",         "book",    "wellness",    "published"),
        ("Mindfulness for Beginners",           "article", "mindfulness", "published"),
        ("Draft: New Meditation Curriculum",    "chapter", "meditation",  "draft"),
    ]
    for title, ctype, category, status in _content_specs:
        if not Content.query.filter_by(title=title).first():
            pub_at = now - timedelta(days=random.randint(1, 30)) if status == "published" else None
            db.session.add(Content(
                title=title,
                content_type=ctype,
                body=f"<p>Body content for <strong>{title}</strong>.</p>",
                body_format="richtext",
                status=status,
                author_id=editor_user.id,
                category=category,
                tags=json.dumps([category, "studioops"]),
                published_at=pub_at,
            ))

    # ── Content filters ───────────────────────────────────────────────────────
    for pattern, ftype in [
        ("spam",           "keyword"),
        ("offensive",      "keyword"),
        (r"\b(hate|abuse)\b", "regex"),
    ]:
        if not ContentFilter.query.filter_by(pattern=pattern).first():
            db.session.add(ContentFilter(pattern=pattern, filter_type=ftype, is_active=True))

    # ── Analytics events ──────────────────────────────────────────────────────
    _pages = ["/schedule", "/booking", "/reviews", "/content/browse", "/admin"]
    for customer in customer_users:
        sid = f"demo-{customer.username}"
        for page in _pages[:3]:
            db.session.add(AnalyticsEvent(
                event_type="page_view",
                user_id=customer.id,
                session_id=sid,
                page=page,
                data="{}",
                ip_address="127.0.0.1",
                user_agent="DemoSeeder/1.0",
            ))
        db.session.add(AnalyticsEvent(
            event_type="booking_start",
            user_id=customer.id,
            session_id=sid,
            page="/booking",
            data="{}",
        ))
        db.session.add(AnalyticsEvent(
            event_type="booking_complete",
            user_id=customer.id,
            session_id=sid,
            page="/booking",
            data="{}",
        ))

    db.session.commit()

    # ── Recalculate credit scores ─────────────────────────────────────────────
    for customer in customer_users:
        recalculate_credit(customer.id)

    click.echo("Demo data seeded successfully!")
    click.echo(f"  Users     → 3 staff, 5 customers (customer1–5), 1 editor")
    click.echo(f"  Resources → {len(rooms)} rooms, {len(equipment)} equipment items")
    click.echo(f"  Sessions  → {len(past_sessions)} past, {len(upcoming_sessions)} upcoming")
    click.echo(f"  Reviews, credit history, content, analytics events added.")
    click.echo(f"  Credentials: <username> / Demo12345!")


# ── registration ──────────────────────────────────────────────────────────────

def register_seed_cli(app: Flask) -> None:
    """Register flask seed <target> CLI commands."""

    @app.cli.command("seed")
    @click.argument("target", type=click.Choice(["admin", "demo"]))
    def seed_cmd(target: str):
        """Seed the database.

        \b
        Targets:
          admin  Create the default admin account (idempotent)
          demo   Load a full demo dataset: users, sessions, reviews, content
        """
        if target == "admin":
            _seed_admin()
        else:
            _seed_demo()
