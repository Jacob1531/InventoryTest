"""
Tests for services/group_access.py - the "basic permissions" group
check used to restrict Database Settings and order placement.

These tests never make a real network/Graph call - graph_auth's
get_graph_token() and request_with_retry() are monkeypatched, so this
runs the actual membership-check logic in group_access.py against
controlled fake responses.

Run with: pytest tests/test_group_access.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import services.group_access as group_access
from services.group_access import is_basic_permissions_user, GroupCheckError


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
def configured_group(monkeypatch):
    """Every test gets a configured group ID and valid-looking Graph
    config, so tests focus on membership/failure logic rather than
    re-triggering the "not configured" checks each time."""
    monkeypatch.setattr(group_access, "BASIC_PERMISSIONS_GROUP_ID", "basic-group-abc")
    monkeypatch.setattr(group_access, "TENANT_ID", "fake-tenant")
    monkeypatch.setattr(group_access, "CLIENT_ID", "fake-client")
    monkeypatch.setattr(group_access, "KEY_VAULT_URL", "https://fake.vault.azure.net/")
    monkeypatch.setattr(group_access, "CERT_NAME", "fake-cert")


def test_member_of_restricted_group_returns_true(monkeypatch):
    monkeypatch.setattr(group_access, "get_graph_token", lambda: "fake-token")
    monkeypatch.setattr(
        group_access, "request_with_retry",
        lambda method, url, **kwargs: _FakeResponse(True, 200, {"value": ["basic-group-abc"]}),
    )
    assert is_basic_permissions_user("user-1") is True


def test_non_member_returns_false(monkeypatch):
    monkeypatch.setattr(group_access, "get_graph_token", lambda: "fake-token")
    monkeypatch.setattr(
        group_access, "request_with_retry",
        lambda method, url, **kwargs: _FakeResponse(True, 200, {"value": []}),
    )
    assert is_basic_permissions_user("user-2") is False


def test_missing_group_id_raises_check_error(monkeypatch):
    monkeypatch.setattr(group_access, "BASIC_PERMISSIONS_GROUP_ID", None)
    with pytest.raises(GroupCheckError):
        is_basic_permissions_user("user-1")


def test_missing_user_id_raises_check_error():
    with pytest.raises(GroupCheckError):
        is_basic_permissions_user(None)


def test_graph_error_response_fails_closed(monkeypatch):
    monkeypatch.setattr(group_access, "get_graph_token", lambda: "fake-token")
    monkeypatch.setattr(
        group_access, "request_with_retry",
        lambda method, url, **kwargs: _FakeResponse(False, 403, text="Forbidden"),
    )
    with pytest.raises(GroupCheckError):
        is_basic_permissions_user("user-1")


def test_token_acquisition_failure_fails_closed_not_crashes(monkeypatch):
    """Regression test: get_graph_token() can raise a plain RuntimeError
    (cert load failure, MSAL failure) rather than GroupCheckError. This
    must still be caught and converted, not propagate as a raw
    RuntimeError - otherwise it would crash whatever page triggered the
    check (Inventory, Settings, etc.) instead of failing closed."""
    def raise_runtime_error():
        raise RuntimeError("Failed to acquire Graph token: invalid_client")
    monkeypatch.setattr(group_access, "get_graph_token", raise_runtime_error)

    with pytest.raises(GroupCheckError):
        is_basic_permissions_user("user-1")


def test_network_connection_error_fails_closed_not_crashes(monkeypatch):
    """Regression test: a genuine network failure during the request
    (not just a clean HTTP error response) must also fail closed rather
    than propagate as a raw ConnectionError."""
    monkeypatch.setattr(group_access, "get_graph_token", lambda: "fake-token")

    def raise_connection_error(method, url, **kwargs):
        raise ConnectionError("Failed to establish a new connection")
    monkeypatch.setattr(group_access, "request_with_retry", raise_connection_error)

    with pytest.raises(GroupCheckError):
        is_basic_permissions_user("user-1")


def test_malformed_json_response_fails_closed_not_crashes(monkeypatch):
    """Regression test: an unparseable response body must also fail
    closed rather than propagate as a raw ValueError."""
    monkeypatch.setattr(group_access, "get_graph_token", lambda: "fake-token")
    monkeypatch.setattr(
        group_access, "request_with_retry",
        lambda method, url, **kwargs: _FakeResponse(True, 200, bad_json=True),
    )
    with pytest.raises(GroupCheckError):
        is_basic_permissions_user("user-1")
