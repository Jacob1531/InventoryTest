"""
permissions.py
=====================================================================
Access tiers and the checks built on them. Extracted from app.py so
any blueprint can import these without importing the Flask app itself
(which would be a circular import).

    ADMIN    everything, including Hardware & Warranty
    MANAGER  everything except Hardware (the low-stock group)
    BASIC    view/add/edit inventory, imports, reports, own files only
    NONE     blocked from the app entirely

DEGRADING ON ERROR
------------------
If Graph can't be reached, the tier falls back to BASIC - NOT to NONE.
That is a deliberate availability choice: NONE blocks the whole app, so
treating an outage as NONE would mean a Graph hiccup takes the entire
system down for everyone. BASIC still denies every elevated action, so
the failure stays restrictive without being total.

NONE is reserved for a definite answer from Graph that the user is in
none of the groups.
=====================================================================
"""
from functools import wraps

from flask import g, render_template

from auth import get_user_id
from services.group_access import (GroupCheckError, TIER_ADMIN, TIER_BASIC, TIER_MANAGER,
                                   TIER_NONE, get_user_tier)

# Tiers allowed to do the things that used to be "not basic".
ELEVATED_TIERS = (TIER_ADMIN, TIER_MANAGER)


def current_tier():
    """The signed-in user's tier, resolved once per request.

    Memoised on flask.g because the nav, the page body and any route
    guard may all ask during a single request, and each miss would be
    another Graph round-trip."""
    if not hasattr(g, "_access_tier"):
        try:
            g._access_tier = get_user_tier(get_user_id())
        except GroupCheckError as e:
            # See the module docstring: degrade to BASIC, never to NONE.
            print(f"Tier check failed, degrading to BASIC: {e}")
            g._access_tier = TIER_BASIC
    return g._access_tier


def is_admin():
    return current_tier() == TIER_ADMIN


def is_elevated():
    """Manager or Admin - i.e. everything except Hardware is permitted."""
    return current_tier() in ELEVATED_TIERS


def has_any_access():
    return current_tier() != TIER_NONE


def is_basic_user():
    """True for the BASIC tier. Kept for the places that RESTRICT rather
    than permit (own-files-only, hiding PURGE from history), where the
    positive phrasing reads better than `not is_elevated()`."""
    return current_tier() == TIER_BASIC


def can_place_orders():
    """Placing, receiving and progressing orders: Manager and Admin."""
    return is_elevated()


def can_delete_files():
    """Deleting file submissions: Manager and Admin. Uploading and
    viewing stay open to Basic."""
    return is_elevated()


def can_view_hardware_warranty():
    """Hardware & Warranty is ADMIN ONLY - the one thing Manager
    deliberately doesn't get."""
    return is_admin()


def require_elevated_access(view_func):
    """Blocks Basic users from a whole section - the page and its
    sub-routes. Used by Database Settings."""
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not is_elevated():
            return render_template(
                "access_denied.html", reason="restricted_group", title="Access Denied"
            ), 403
        return view_func(*args, **kwargs)
    return wrapped


def require_admin(view_func):
    """Admin only. Used by Hardware & Warranty, which Manager is
    deliberately excluded from."""
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not is_admin():
            return render_template(
                "access_denied.html", reason="admin_only", title="Access Denied"
            ), 403
        return view_func(*args, **kwargs)
    return wrapped
