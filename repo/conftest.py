"""
Shared pytest fixtures for StudioOps.
Placed at the project root so both unit_tests/ and API_tests/ can import from it.
"""
import pytest
from datetime import datetime, timedelta

from app import create_app
from app.extensions import db as _db
from app.models.user import User
from app.models.studio import StudioSession, Reservation, Waitlist, Resource
from app.services.auth_service import hash_password


@pytest.fixture(scope="function")
def app():
    """Flask application configured for testing (in-memory SQLite, CSRF off)."""
    application = create_app("testing")
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def client(app):
    """Test client for HTTP-level tests."""
    return app.test_client()


@pytest.fixture
def ctx(app):
    """Bare application context for service-level tests."""
    with app.app_context():
        yield


@pytest.fixture
def db(app):
    with app.app_context():
        yield _db


@pytest.fixture
def sample_users(db):
    """Create test users: 1 customer, 1 staff, 1 admin."""
    customer = User(
        username="testcustomer",
        email="customer@test.com",
        role="customer",
        credit_score=100,
        password_hash=hash_password("TestPass123!"),
    )
    staff = User(
        username="teststaff",
        email="staff@test.com",
        role="staff",
        credit_score=100,
        password_hash=hash_password("TestPass123!"),
    )
    admin = User(
        username="testadmin",
        email="admin@test.com",
        role="admin",
        credit_score=100,
        password_hash=hash_password("TestPass123!"),
    )
    db.session.add_all([customer, staff, admin])
    db.session.commit()
    return {"customer": customer, "staff": staff, "admin": admin}


@pytest.fixture
def sample_room(db):
    room = Resource(type="room", name="Studio A", capacity=15)
    db.session.add(room)
    db.session.commit()
    return room


@pytest.fixture
def sample_session(db, sample_users, sample_room):
    """Create a studio session tomorrow at 10 AM."""
    tomorrow = datetime.utcnow() + timedelta(days=1)
    start = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=1)
    session = StudioSession(
        title="Morning Yoga",
        description="Relaxing morning yoga class",
        instructor_id=sample_users["staff"].id,
        room_id=sample_room.id,
        start_time=start,
        end_time=end,
        capacity=15,
        is_active=True,
    )
    db.session.add(session)
    db.session.commit()
    return session


@pytest.fixture
def completed_session_with_reservation(db, sample_users, sample_room):
    """Create a session that started 1 hour ago with a confirmed reservation."""
    start = datetime.utcnow() - timedelta(hours=1)
    session = StudioSession(
        title="Past Yoga",
        instructor_id=sample_users["staff"].id,
        room_id=sample_room.id,
        start_time=start,
        end_time=start + timedelta(hours=1),
        capacity=15,
        is_active=True,
    )
    db.session.add(session)
    db.session.commit()
    reservation = Reservation(
        user_id=sample_users["customer"].id,
        session_id=session.id,
        status="confirmed",
    )
    db.session.add(reservation)
    db.session.commit()
    return {"session": session, "reservation": reservation}


@pytest.fixture
def ended_session_with_reservation(db, sample_users, sample_room):
    """Create a session that ended 30 minutes ago with a confirmed reservation."""
    start = datetime.utcnow() - timedelta(hours=2)
    end = datetime.utcnow() - timedelta(minutes=30)
    session = StudioSession(
        title="Ended Yoga",
        instructor_id=sample_users["staff"].id,
        room_id=sample_room.id,
        start_time=start,
        end_time=end,
        capacity=15,
        is_active=True,
    )
    db.session.add(session)
    db.session.commit()
    reservation = Reservation(
        user_id=sample_users["customer"].id,
        session_id=session.id,
        status="confirmed",
    )
    db.session.add(reservation)
    db.session.commit()
    return {"session": session, "reservation": reservation}


@pytest.fixture
def login_as(client):
    """Log in as a user. Usage: login_as('testcustomer', 'TestPass123!')"""
    def _login(username, password):
        return client.post(
            "/auth/login",
            data={"identifier": username, "password": password},
            follow_redirects=True,
        )
    return _login


# ── Content fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def editor_user(db):
    from app.services.auth_service import hash_password
    editor = User(
        username="editor1",
        email="editor@test.com",
        role="editor",
        credit_score=100,
        password_hash=hash_password("TestPass123!"),
    )
    db.session.add(editor)
    db.session.commit()
    return editor


@pytest.fixture
def sample_content(db, editor_user):
    from app.models.content import Content, ContentVersion
    content = Content(
        title="Test Article",
        content_type="article",
        body="# Hello World\nThis is test content with enough words to test.",
        body_format="markdown",
        status="draft",
        author_id=editor_user.id,
        category="wellness",
        tags='["yoga", "health"]',
        current_version=1,
    )
    db.session.add(content)
    db.session.commit()
    version = ContentVersion(
        content_id=content.id,
        version_number=1,
        title=content.title,
        body=content.body,
        status="draft",
        created_by=editor_user.id,
        change_note="Initial creation",
    )
    db.session.add(version)
    db.session.commit()
    return content


@pytest.fixture
def sample_filter(db):
    from app.models.content import ContentFilter
    f = ContentFilter(pattern="badword", filter_type="keyword", is_active=True)
    db.session.add(f)
    db.session.commit()
    return f


# ── Review fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def completed_reservation(db, sample_users, sample_room):
    """Create a completed session + confirmed reservation for the customer."""
    start = datetime.utcnow() - timedelta(hours=3)
    end = start + timedelta(hours=1)
    session = StudioSession(
        title="Completed Yoga",
        instructor_id=sample_users["staff"].id,
        room_id=sample_room.id,
        start_time=start,
        end_time=end,
        capacity=15,
        is_active=True,
    )
    db.session.add(session)
    db.session.commit()
    reservation = Reservation(
        user_id=sample_users["customer"].id,
        session_id=session.id,
        status="completed",
    )
    db.session.add(reservation)
    db.session.commit()
    return {"session": session, "reservation": reservation}
