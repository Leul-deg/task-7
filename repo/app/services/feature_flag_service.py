"""
Feature flag service — flag evaluation with canary user support, CRUD, and
Jinja2 global registration.

Canary semantics:
  - is_enabled=True  → flag is on for ALL users
  - is_enabled=False, canary_staff_ids=[1,2,3] → on only for those user IDs
  - is_enabled=False, canary_staff_ids=[] → off for everyone
"""
import json
import logging
from typing import Optional

from flask import Flask

from app.extensions import db
from app.models.ops import FeatureFlag
from app.models.user import User

logger = logging.getLogger(__name__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _parse_canary_ids(raw: str | None) -> list[int]:
    try:
        ids = json.loads(raw or "[]")
        return [int(i) for i in ids if isinstance(i, (int, float, str)) and str(i).isdigit()]
    except (json.JSONDecodeError, TypeError, ValueError):
        return []


def _flag_to_dict(flag: FeatureFlag) -> dict:
    return {
        "id": flag.id,
        "name": flag.name,
        "description": flag.description,
        "is_enabled": flag.is_enabled,
        "canary_staff_ids": _parse_canary_ids(flag.canary_staff_ids),
        "created_at": flag.created_at.strftime("%m/%d/%Y %I:%M %p") if flag.created_at else None,
        "updated_at": flag.updated_at.strftime("%m/%d/%Y %I:%M %p") if flag.updated_at else None,
    }


def _validate_staff_canary_ids(canary_staff_ids: list[int] | None) -> tuple[bool, str]:
    ids = [int(i) for i in (canary_staff_ids or [])]
    if not ids:
        return True, ""

    staff_ids = {
        row[0]
        for row in db.session.query(User.id)
        .filter(User.id.in_(ids), User.role == "staff")
        .all()
    }
    invalid = sorted(i for i in ids if i not in staff_ids)
    if invalid:
        return False, f"Canary IDs must belong to staff users only. Invalid IDs: {invalid}"
    return True, ""


# ── FUNCTION 1: is_feature_enabled ───────────────────────────────────────────

def is_feature_enabled(name: str, user=None) -> bool:
    """
    Return True if the named feature flag is active for the given user.

    Logic:
      1. Flag not found → False
      2. Flag globally on (is_enabled=True) → True for all
      3. Flag globally off, canary list present → True only if user.id in list
      4. Otherwise → False
    """
    flag = FeatureFlag.query.filter_by(name=name).first()
    if not flag:
        return False

    if flag.is_enabled:
        return True

    # Canary check
    if user is not None:
        canary_ids = _parse_canary_ids(flag.canary_staff_ids)
        if canary_ids:
            try:
                return int(user.id) in canary_ids
            except (AttributeError, TypeError, ValueError):
                return False

    return False


# ── FUNCTION 2: create_flag ───────────────────────────────────────────────────

def create_flag(
    name: str,
    description: str = None,
    is_enabled: bool = False,
    canary_staff_ids: list[int] = None,
) -> dict:
    """
    Create a new feature flag.

    Returns:
        {"success": True, "flag": dict}
        {"success": False, "reason": str}
    """
    if not name or not name.strip():
        return {"success": False, "reason": "Flag name is required."}

    name = name.strip().lower().replace(" ", "_")

    if FeatureFlag.query.filter_by(name=name).first():
        return {"success": False, "reason": f"Flag '{name}' already exists."}

    ok, reason = _validate_staff_canary_ids(canary_staff_ids)
    if not ok:
        return {"success": False, "reason": reason}

    flag = FeatureFlag(
        name=name,
        description=description,
        is_enabled=is_enabled,
        canary_staff_ids=json.dumps(canary_staff_ids or []),
    )
    db.session.add(flag)
    db.session.commit()

    logger.info("FeatureFlag created: %s (enabled=%s)", name, is_enabled)
    return {"success": True, "flag": _flag_to_dict(flag)}


# ── FUNCTION 3: update_flag ───────────────────────────────────────────────────

def update_flag(
    name: str,
    is_enabled: bool = None,
    canary_staff_ids: list[int] = None,
    description: str = None,
) -> dict:
    """
    Update an existing feature flag's settings.

    Only non-None arguments are applied.

    Returns:
        {"success": True, "flag": dict}
        {"success": False, "reason": str}
    """
    flag = FeatureFlag.query.filter_by(name=name).first()
    if not flag:
        return {"success": False, "reason": f"Flag '{name}' not found."}

    if is_enabled is not None:
        flag.is_enabled = bool(is_enabled)
    if canary_staff_ids is not None:
        ok, reason = _validate_staff_canary_ids(canary_staff_ids)
        if not ok:
            return {"success": False, "reason": reason}
        flag.canary_staff_ids = json.dumps([int(i) for i in canary_staff_ids])
    if description is not None:
        flag.description = description

    db.session.commit()
    logger.info("FeatureFlag updated: %s (enabled=%s)", name, flag.is_enabled)
    return {"success": True, "flag": _flag_to_dict(flag)}


# ── FUNCTION 4: delete_flag ───────────────────────────────────────────────────

def delete_flag(name: str) -> dict:
    """
    Permanently delete a feature flag.

    Returns:
        {"success": True}
        {"success": False, "reason": str}
    """
    flag = FeatureFlag.query.filter_by(name=name).first()
    if not flag:
        return {"success": False, "reason": f"Flag '{name}' not found."}

    db.session.delete(flag)
    db.session.commit()
    logger.info("FeatureFlag deleted: %s", name)
    return {"success": True}


# ── FUNCTION 5: get_all_flags ─────────────────────────────────────────────────

def get_all_flags() -> list[dict]:
    """Return all feature flags sorted by name."""
    flags = FeatureFlag.query.order_by(FeatureFlag.name.asc()).all()
    return [_flag_to_dict(f) for f in flags]


# ── FUNCTION 6: register_jinja_global ────────────────────────────────────────

def register_jinja_global(app: Flask) -> None:
    """
    Make `is_feature_enabled(name)` available in all Jinja2 templates.

    Usage in templates:
        {% if is_feature_enabled('new_booking_ui') %}…{% endif %}
        {% if is_feature_enabled('beta_feature', current_user) %}…{% endif %}
    """
    app.jinja_env.globals["is_feature_enabled"] = is_feature_enabled
    logger.debug("is_feature_enabled registered as Jinja2 global")
