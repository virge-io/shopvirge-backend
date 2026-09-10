import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from server.security import Principal, has_admin_group, require_admin
from server.settings import app_settings


@pytest.mark.parametrize("group", ["Admins", "admins"])
def test_has_admin_group_accepts_supported_casing(group):
    assert has_admin_group([group]) is True


def test_has_admin_group_rejects_other_groups():
    assert has_admin_group(["users"]) is False


def _token(client_id, groups=(), scope="https://virge/api"):
    return SimpleNamespace(client_id=client_id, cognito_groups=list(groups), scope=scope, cognito_id="sub-1")


@pytest.fixture
def cognito_client_ids(monkeypatch):
    monkeypatch.setattr(app_settings, "AWS_COGNITO_CLIENT_ID", "web-client")
    monkeypatch.setattr(app_settings, "AWS_COGNITO_MCP_CLIENT_ID", "mcp-client")


@pytest.mark.parametrize("client_id", ["web-client", "mcp-client"])
def test_admin_required_rejects_user_token_without_admin_group(cognito_client_ids, client_id):
    """Both app clients issue *user* tokens, so both must face the group check.

    Regression: the admin check compared only against AWS_COGNITO_CLIENT_ID, so a
    token from the MCP app client fell into the "must be M2M, trust it" branch
    and reached admin routes without being in the admins group.
    """
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(require_admin(Principal.from_token(_token(client_id, groups=["users"]))))
    assert exc_info.value.status_code == 403


@pytest.mark.parametrize("client_id", ["web-client", "mcp-client"])
@pytest.mark.parametrize("group", ["Admins", "admins"])
def test_admin_required_accepts_user_token_in_admin_group(cognito_client_ids, client_id, group):
    principal = Principal.from_token(_token(client_id, groups=[group]))
    assert asyncio.run(require_admin(principal)) is principal


def test_admin_required_trusts_m2m_token(cognito_client_ids):
    """An M2M token has no cognito:groups; Principal.from_token already scope-gated it."""
    principal = Principal.from_token(_token("some-m2m-client"))
    assert asyncio.run(require_admin(principal)) is principal


def test_service_token_without_api_scope_is_refused(cognito_client_ids):
    with pytest.raises(HTTPException) as exc_info:
        Principal.from_token(_token("some-m2m-client", scope="openid"))
    assert exc_info.value.status_code == 401
