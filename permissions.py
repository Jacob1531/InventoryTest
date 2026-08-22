"""
permissions.py
=====================================================================
Shared permission checks used across blueprints. Extracted from app.py
during the blueprint refactor so that any blueprint can import them
without importing the Flask app object itself (which would create a
circular import: app -> blueprints -> app).

All checks FAIL CLOSED - any error determining group membership is
treated as "denied" rather than "allowed". See the individual
docstrings for the reasoning.
=====================================================================
"""
from functools import wraps

from flask import render_template

from auth import get_user_id
from services.group_access import is_basic_permissions_user, GroupCheckError


def require_elevated_access(view_func):
    """Blocks members of the "basic permissions" Entra ID group from an
    entire section - both the page itself and its sub-routes. Currently
    used by Database Settings (and its threshold/purge sub-routes) and
    Hardware & Warranty. Fails CLOSED: if membership can't be reliably
    determined - missing config, Graph error, no user ID - access is
    denied rather than silently allowed. That's a deliberate choice: the
    failure mode of "the restricted group gets in anyway" is worse than
    "everyone is temporarily blocked until the check works again"."""
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        try:
            is_basic_permissions = is_basic_permissions_user(get_user_id())
        except GroupCheckError as e:
            print(f"Elevated-access check failed for {view_func.__name__}, denying access: {e}")
            return render_template("access_denied.html", reason="check_failed", title="Access Denied"), 403

        if is_basic_permissions:
            return render_template("access_denied.html", reason="restricted_group", title="Access Denied"), 403

        return view_func(*args, **kwargs)
    return wrapped


def can_place_orders():
    """True if the signed-in user is allowed to place orders - i.e. NOT a
    member of the basic-permissions group. Unlike Database Settings, this
    doesn't block viewing anything, only the ability to create a new
    order; Orders, Inventory, and Low Stock stay fully viewable either
    way. Fails CLOSED, same reasoning as Database Settings: any error
    checking membership is treated as 'cannot place orders'."""
    try:
        return not is_basic_permissions_user(get_user_id())
    except GroupCheckError as e:
        print(f"Order-placement permission check failed, denying: {e}")
        return False


def can_delete_files():
    """True if the signed-in user is allowed to delete file submissions -
    i.e. NOT a member of the basic-permissions group. Uploading and
    viewing Files stay open to everyone; only the destructive delete
    action is gated. Fails CLOSED, same reasoning as the other
    permission checks."""
    try:
        return not is_basic_permissions_user(get_user_id())
    except GroupCheckError as e:
        print(f"File-deletion permission check failed, denying: {e}")
        return False


def can_view_hardware_warranty():
    """True if the signed-in user is allowed to see the Hardware &
    Warranty dashboard card at all - i.e. NOT a member of the
    basic-permissions group. Unlike can_place_orders/can_delete_files
    (which gate one action within an otherwise-visible section), this
    controls whether the card renders at all - matching Database
    Settings' pattern where restricted users can't view the section,
    not just act within it. The actual page itself is separately
    enforced by @require_elevated_access, so this check existing only
    controls the dashboard card's visibility, not real access."""
    try:
        return not is_basic_permissions_user(get_user_id())
    except GroupCheckError as e:
        print(f"Hardware & Warranty visibility check failed, denying: {e}")
        return False
