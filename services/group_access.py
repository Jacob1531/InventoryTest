"""
group_access.py
=====================================================================
Checks whether a specific signed-in user belongs to the "basic
permissions" Entra ID group - the lowest access tier, whose members
are blocked from higher-privilege sections of the app (currently:
Database Settings). This is a deny-list, not an allow-list: everyone
has access except members of this one group.

Uses Microsoft Graph's checkMemberGroups endpoint - a single,
purpose-built call for "is this user in any of these groups" (and it
expands nested/transitive group membership automatically), rather
than fetching and paging through the user's entire group list.

Reuses the same Graph app registration/certificate as
services/notifications.py (see services/graph_auth.py) - this only
needs the GroupMember.Read.All application permission, which should
already be granted since the low-stock email feature depends on it
too (it lists a group's members the other direction).

REQUIRED ENVIRONMENT VARIABLE:
  ENTRA_BASIC_PERMISSIONS_GROUP_ID
      Object ID of the Entra ID group whose members are treated as
      the lowest access tier and blocked from restricted sections.
=====================================================================
"""
import os
import logging

from services.graph_auth import get_graph_token, request_with_retry, GRAPH_BASE, TENANT_ID, CLIENT_ID, KEY_VAULT_URL, CERT_NAME

logger = logging.getLogger(__name__)

BASIC_PERMISSIONS_GROUP_ID = os.getenv("ENTRA_BASIC_PERMISSIONS_GROUP_ID")


class GroupCheckError(Exception):
    """Raised when membership can't be reliably determined - missing
    configuration, no user ID available, or a Graph/auth failure.
    Callers should treat this as 'deny access' (fail closed), not the
    same as a confirmed 'not a member' result."""
    pass


def is_basic_permissions_user(user_object_id):
    """Returns True if the given Entra object ID belongs (directly, or
    via a nested group) to the basic-permissions group. Raises
    GroupCheckError if this can't be determined - see class docstring.

    Everything Graph-related is wrapped in one broad except below. This
    matters: get_graph_token() can raise a plain RuntimeError (cert
    load failure, MSAL failure), the network call itself can raise a
    connection/timeout error, and a malformed response can fail to
    parse as JSON - none of those are GroupCheckError on their own. If
    they weren't caught here, they'd propagate straight out as an
    unhandled 500 on whatever page triggered the check (Inventory,
    Settings, etc.) instead of failing closed the way callers expect."""
    if not BASIC_PERMISSIONS_GROUP_ID:
        raise GroupCheckError(
            "ENTRA_BASIC_PERMISSIONS_GROUP_ID is not configured."
        )
    if not all([TENANT_ID, CLIENT_ID, KEY_VAULT_URL, CERT_NAME]):
        raise GroupCheckError(
            "Missing Entra/Graph/Key Vault configuration in environment variables."
        )
    if not user_object_id:
        raise GroupCheckError("No signed-in user object ID available to check.")

    try:
        token = get_graph_token()

        url = f"{GRAPH_BASE}/users/{user_object_id}/checkMemberGroups"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        body = {"groupIds": [BASIC_PERMISSIONS_GROUP_ID]}

        resp = request_with_retry("POST", url, headers=headers, json=body)
        if not resp.ok:
            raise GroupCheckError(
                f"Graph membership check failed: {resp.status_code} {resp.text}"
            )

        matched_group_ids = resp.json().get("value", [])
    except GroupCheckError:
        raise
    except Exception as e:
        raise GroupCheckError(f"Graph membership check failed: {e}")

    return BASIC_PERMISSIONS_GROUP_ID in matched_group_ids
