"""
Tests for services/group_access.py - resolving an Entra user's ACCESS
TIER from their group memberships.

Four tiers: ADMIN > MANAGER > BASIC > NONE. All three groups are
checked in a single Graph call; these tests cover the precedence rules
and the failure paths without touching the network.

Run with: pytest tests/test_group_access.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import services.group_access as group_access
from services.group_access import (GroupCheckError, TIER_ADMIN, TIER_BASIC, TIER_MANAGER,
                                   TIER_NONE, get_user_tier, tier_from_matches)


class _FakeResponse:
    def __init__(self, ok, status_code, json_data=None, text="", bad_json=False):
        self.ok = ok
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("not valid json")
        return self._json


@pytest.fixture(autouse=True)
def configured_groups(monkeypatch):
    monkeypatch.setattr(group_access, "ADMIN_GROUP_ID", "admin-gid")
    monkeypatch.setattr(group_access, "MANAGER_GROUP_ID", "manager-gid")
    monkeypatch.setattr(group_access, "BASIC_PERMISSIONS_GROUP_ID", "basic-gid")
    monkeypatch.setattr(group_access, "TENANT_ID", "t")
    monkeypatch.setattr(group_access, "CLIENT_ID", "c")
    monkeypatch.setattr(group_access, "KEY_VAULT_URL", "https://v/")
    monkeypatch.setattr(group_access, "CERT_NAME", "n")


# ---- precedence (pure) --------------------------------------------------

def test_admin_group_gives_admin():
    assert tier_from_matches(["admin-gid"]) == TIER_ADMIN


def test_manager_group_gives_manager():
    assert tier_from_matches(["manager-gid"]) == TIER_MANAGER


def test_basic_group_gives_basic():
    assert tier_from_matches(["basic-gid"]) == TIER_BASIC


def test_no_groups_gives_none():
    assert tier_from_matches([]) == TIER_NONE


def test_unrecognised_group_is_ignored():
    assert tier_from_matches(["some-other-group"]) == TIER_NONE


def test_highest_tier_wins_admin_over_manager():
    assert tier_from_matches(["manager-gid", "admin-gid"]) == TIER_ADMIN


def test_highest_tier_wins_admin_over_basic():
    assert tier_from_matches(["basic-gid", "admin-gid"]) == TIER_ADMIN


def test_highest_tier_wins_manager_over_basic():
    assert tier_from_matches(["basic-gid", "manager-gid"]) == TIER_MANAGER


def test_all_three_groups_resolves_to_admin():
    assert tier_from_matches(["basic-gid", "manager-gid", "admin-gid"]) == TIER_ADMIN


# ---- the Graph call -----------------------------------------------------

def test_all_groups_checked_in_a_single_request(monkeypatch):
    """Three tiers must not cost three round-trips."""
    calls = []

    def capture(method, url, **kwargs):
        calls.append(kwargs.get("json"))
        return _FakeResponse(True, 200, {"value": ["manager-gid"]})

    monkeypatch.setattr(group_access, "get_graph_token", lambda: "tok")
    monkeypatch.setattr(group_access, "request_with_retry", capture)

    assert get_user_tier("user-1") == TIER_MANAGER
    assert len(calls) == 1
    assert set(calls[0]["groupIds"]) == {"admin-gid", "manager-gid", "basic-gid"}


def test_user_in_no_group_resolves_to_none(monkeypatch):
    monkeypatch.setattr(group_access, "get_graph_token", lambda: "tok")
    monkeypatch.setattr(
        group_access, "request_with_retry",
        lambda m, u, **k: _FakeResponse(True, 200, {"value": []}),
    )
    assert get_user_tier("user-1") == TIER_NONE


def test_only_configured_groups_are_queried(monkeypatch):
    """A partially configured deployment should still work for the tiers
    that ARE set up, rather than failing outright."""
    monkeypatch.setattr(group_access, "MANAGER_GROUP_ID", None)
    calls = []

    def capture(method, url, **kwargs):
        calls.append(kwargs.get("json"))
        return _FakeResponse(True, 200, {"value": []})

    monkeypatch.setattr(group_access, "get_graph_token", lambda: "tok")
    monkeypatch.setattr(group_access, "request_with_retry", capture)

    get_user_tier("user-1")
    assert set(calls[0]["groupIds"]) == {"admin-gid", "basic-gid"}


# ---- failure paths ------------------------------------------------------

def test_no_groups_configured_raises(monkeypatch):
    monkeypatch.setattr(group_access, "ADMIN_GROUP_ID", None)
    monkeypatch.setattr(group_access, "MANAGER_GROUP_ID", None)
    monkeypatch.setattr(group_access, "BASIC_PERMISSIONS_GROUP_ID", None)
    with pytest.raises(GroupCheckError):
        get_user_tier("user-1")


def test_missing_user_id_raises():
    with pytest.raises(GroupCheckError):
        get_user_tier(None)


def test_graph_error_response_raises(monkeypatch):
    monkeypatch.setattr(group_access, "get_graph_token", lambda: "tok")
    monkeypatch.setattr(
        group_access, "request_with_retry",
        lambda m, u, **k: _FakeResponse(False, 403, text="Forbidden"),
    )
    with pytest.raises(GroupCheckError):
        get_user_tier("user-1")


def test_token_failure_becomes_a_group_check_error(monkeypatch):
    """get_graph_token raises plain RuntimeError; unconverted it would
    escape as an unhandled 500 on whatever page triggered the check."""
    def boom():
        raise RuntimeError("cert expired")
    monkeypatch.setattr(group_access, "get_graph_token", boom)
    with pytest.raises(GroupCheckError):
        get_user_tier("user-1")


def test_network_failure_becomes_a_group_check_error(monkeypatch):
    monkeypatch.setattr(group_access, "get_graph_token", lambda: "tok")

    def boom(method, url, **kwargs):
        raise ConnectionError("no route to host")
    monkeypatch.setattr(group_access, "request_with_retry", boom)
    with pytest.raises(GroupCheckError):
        get_user_tier("user-1")


def test_malformed_response_becomes_a_group_check_error(monkeypatch):
    monkeypatch.setattr(group_access, "get_graph_token", lambda: "tok")
    monkeypatch.setattr(
        group_access, "request_with_retry",
        lambda m, u, **k: _FakeResponse(True, 200, bad_json=True),
    )
    with pytest.raises(GroupCheckError):
        get_user_tier("user-1")
