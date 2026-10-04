"""
group_access.py
=====================================================================
Resolves which Entra ID groups the signed-in user belongs to, and from
that their ACCESS TIER.

Four tiers, highest wins when someone is in more than one group:

    ADMIN    - everything, including Hardware & Warranty
    MANAGER  - everything except Hardware (the low-stock group)
    BASIC    - limited: no orders, no Database Settings, no Hardware,
               sees only their own files
    NONE     - in none of the groups; blocked from the app entirely

All three groups are checked in a SINGLE Graph call -
checkMemberGroups takes a list of group ids and returns the subset the
user belongs to - so three tiers cost no more round-trips than one did.

Reuses the app registration/certificate from services/graph_auth.py
and needs only GroupMember.Read.All, which is already granted.

REQUIRED ENVIRONMENT VARIABLES:
  ENTRA_ADMIN_GROUP_ID              highest tier
  ENTRA_LOW_STOCK_GROUP_ID          manager tier (also the low-stock
                                    email recipients)
  ENTRA_BASIC_PERMISSIONS_GROUP_ID  lowest functional tier
=====================================================================
"""
import os
import logging

from services.graph_auth import get_graph_token, request_with_retry, GRAPH_BASE, TENANT_ID, CLIENT_ID, KEY_VAULT_URL, CERT_NAME

logger = logging.getLogger(__name__)

ADMIN_GROUP_ID = os.getenv("ENTRA_ADMIN_GROUP_ID")
MANAGER_GROUP_ID = os.getenv("ENTRA_LOW_STOCK_GROUP_ID")
BASIC_PERMISSIONS_GROUP_ID = os.getenv("ENTRA_BASIC_PERMISSIONS_GROUP_ID")

TIER_ADMIN = "ADMIN"
TIER_MANAGER = "MANAGER"
TIER_BASIC = "BASIC"
TIER_NONE = "NONE"

# Ranked, highest first - membership of several groups resolves to the
# most privileged.
TIER_ORDER = [TIER_ADMIN, TIER_MANAGER, TIER_BASIC, TIER_NONE]

TIER_LABELS = {
    TIER_ADMIN: "Administrator",
    TIER_MANAGER: "Manager",
    TIER_BASIC: "Basic",
    TIER_NONE: "No access",
}


class GroupCheckError(Exception):
    """Raised when membership can't be determined - missing config, no
    user id, or a Graph/auth failure. Callers decide how to degrade; see
    permissions.py, which drops to BASIC rather than locking everyone
    out during a Graph outage."""
    pass


def _configured_groups():
    """The configured (tier, group_id) pairs, highest tier first. Groups
    left unset are skipped rather than treated as empty, so a partially
    configured deployment still works for the tiers that ARE set up."""
    pairs = [
        (TIER_ADMIN, ADMIN_GROUP_ID),
        (TIER_MANAGER, MANAGER_GROUP_ID),
        (TIER_BASIC, BASIC_PERMISSIONS_GROUP_ID),
    ]
    return [(tier, gid) for tier, gid in pairs if gid]


def tier_from_matches(matched_ids):
    """Given the group ids Graph says the user belongs to, returns their
    tier. Pure, so the precedence rules are testable without Graph."""
    matched = set(matched_ids or [])
    for tier, group_id in _configured_groups():
        if group_id in matched:
            return tier
    return TIER_NONE


def get_user_tier(user_object_id):
    """The signed-in user's access tier, via one Graph call covering all
    configured groups. Raises GroupCheckError if it can't be determined."""
    configured = _configured_groups()
    if not configured:
        raise GroupCheckError(
            "No access groups configured (set ENTRA_ADMIN_GROUP_ID, "
            "ENTRA_LOW_STOCK_GROUP_ID and/or ENTRA_BASIC_PERMISSIONS_GROUP_ID)."
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
        # All configured groups in ONE request.
        body = {"groupIds": [gid for _, gid in configured]}

        resp = request_with_retry("POST", url, headers=headers, json=body)
        if not resp.ok:
            raise GroupCheckError(
                f"Graph membership check failed: {resp.status_code} {resp.text}"
            )

        matched = resp.json().get("value", [])
    except GroupCheckError:
        raise
    except Exception as e:
        # get_graph_token raises plain RuntimeError, the request can raise
        # connection errors, and a malformed body can fail to parse - none
        # of which are GroupCheckError on their own. Without this they'd
        # escape as an unhandled 500 on whatever page triggered the check.
        raise GroupCheckError(f"Graph membership check failed: {e}")

    return tier_from_matches(matched)
