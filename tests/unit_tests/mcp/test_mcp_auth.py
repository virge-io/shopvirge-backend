# Copyright 2026 René Dohmen <acidjunk@gmail.com>
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
"""How a tool call is authenticated and authorised through the mounted MCP server.

The MCP transport is open: ``initialize`` and ``tools/list`` need no credential.
A tool call is authenticated by the route it reaches, because fastmcp 2.14.x
forwards the caller's ``Authorization`` header into its in-process request; the
tier guards then apply exactly as for REST. These tests run over real HTTP
through the mounted server with the real ``current_principal`` (the conftest
stub is lifted) and Cognito stubbed the way ``real_auth_client`` stubs it.
"""

import contextlib
import json
from typing import Any, Optional

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import server.security
from server.db import db
from server.db.models import RevisionTable, TagTable
from server.mcp.server import MCP_MOUNT_PATH, mount_mcp
from server.security import MCP_OPERATORS_GROUP, MCP_VIEWERS_GROUP, Principal, current_principal
from server.settings import app_settings
from tests.unit_tests.conftest import _cognito_token
from tests.unit_tests.factories.api_key import make_api_key
from tests.unit_tests.factories.shop import make_shop
from tests.unit_tests.factories.tag import make_tag
from tests.unit_tests.mcp.test_mcp import EXPECTED_TOOL_NAMES

HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def mcp_app(fastapi_app):
    """The shared test app with the MCP server mounted once, and its lifespan entered by the parent."""
    if not any(getattr(route, "path", None) == MCP_MOUNT_PATH for route in fastapi_app.routes):
        sub_app = mount_mcp(fastapi_app)

        @contextlib.asynccontextmanager
        async def lifespan(app):
            async with sub_app.router.lifespan_context(app):
                yield

        fastapi_app.router.lifespan_context = lifespan
    return fastapi_app


@pytest.fixture(scope="module")
def mcp_client(mcp_app):
    """One client for the module: the MCP session manager's lifespan may only be entered once."""
    with TestClient(mcp_app) as client:
        yield client


class McpSession:
    """A streamable-HTTP MCP client that speaks just enough JSON-RPC for these tests."""

    def __init__(self, client: TestClient, bearer: Optional[str]):
        self.client, self.bearer, self.session_id, self._id = client, bearer, None, 0

    def post(self, body: dict) -> tuple[int, Optional[dict]]:
        headers = dict(HEADERS)
        if self.bearer:
            headers["Authorization"] = f"Bearer {self.bearer}"
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        response = self.client.post(f"{MCP_MOUNT_PATH}/", json=body, headers=headers)
        self.session_id = response.headers.get("mcp-session-id", self.session_id)
        if response.status_code != 200 or not response.text:
            return response.status_code, None
        if response.headers["content-type"].startswith("text/event-stream"):
            payloads = [json.loads(line[5:]) for line in response.text.splitlines() if line.startswith("data:")]
            return response.status_code, payloads[-1] if payloads else None
        return response.status_code, response.json()

    def request(self, method: str, params: Optional[dict] = None) -> tuple[int, Optional[dict]]:
        self._id += 1
        return self.post({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}})

    def initialize(self) -> int:
        status, _ = self.request(
            "initialize",
            {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "tests", "version": "0"}},
        )
        if status == 200:
            self.post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return status

    def tools(self) -> list[str]:
        _, reply = self.request("tools/list")
        return sorted(tool["name"] for tool in reply["result"]["tools"])

    def call(self, name: str, **arguments: Any) -> dict:
        _, reply = self.request("tools/call", {"name": name, "arguments": arguments})
        return reply["result"]


def _error_text(result: dict) -> str:
    return result["content"][0]["text"] if result.get("isError") else ""


@pytest.fixture
def mcp(mcp_app, mcp_client, monkeypatch):
    """Factory for sessions; ``cognito_token`` is what Cognito 'verifies' for a non-key bearer."""
    override = mcp_app.dependency_overrides.pop(current_principal, None)
    state: dict[str, Any] = {"token": None}

    async def _cognito(connection):
        if state["token"] is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return state["token"]

    monkeypatch.setattr(server.security.cognito_eu, "auth_required", _cognito)
    monkeypatch.setattr(app_settings, "MCP_ENABLED", True)  # ``via`` is derived from the MCP context only then
    try:

        def _session(bearer: Optional[str] = None, cognito_token=None) -> McpSession:
            state["token"] = cognito_token
            session = McpSession(mcp_client, bearer)
            assert session.initialize() == 200
            return session

        yield _session
    finally:
        if override is not None:
            mcp_app.dependency_overrides[current_principal] = override


def test_transport_is_open_but_tool_calls_are_authenticated_by_the_route(mcp):
    """No credential: the whole tool list is visible, and a call fails with the route's 401."""
    shop = make_shop(random_shop_name=True)
    session = mcp()

    assert session.tools() == sorted(EXPECTED_TOOL_NAMES)
    denied = session.call("list_products", shop_id=str(shop))
    assert denied.get("isError") and "401" in _error_text(denied)


def test_api_key_bearer_is_forwarded_and_bound_to_its_shop(mcp):
    own, other = make_shop(random_shop_name=True), make_shop(random_shop_name=True)
    _, plaintext = make_api_key(own)
    session = mcp(plaintext)

    assert not session.call("list_products", shop_id=str(own)).get("isError")
    denied = session.call("list_products", shop_id=str(other))
    assert denied.get("isError") and "403" in _error_text(denied)


def test_cognito_user_is_scoped_by_its_groups(mcp):
    own, other = make_shop(random_shop_name=True), make_shop(random_shop_name=True)
    session = mcp("a-cognito-jwt", cognito_token=_cognito_token([str(own), MCP_OPERATORS_GROUP]))

    mine = session.call("list_my_shops")
    assert [shop["id"] for shop in mine["structuredContent"]["shops"]] == [str(own)]
    assert not mine["structuredContent"]["is_admin"]
    denied = session.call("list_products", shop_id=str(other))
    assert denied.get("isError") and "403" in _error_text(denied)


def test_tool_call_is_recorded_with_source_mcp(mcp):
    """``via`` comes from fastmcp's request context, so the revision row says where the write came from."""
    shop = make_shop(random_shop_name=True)
    tag = make_tag(shop)
    row, plaintext = make_api_key(shop)
    session = mcp(plaintext)

    result = session.call("delete_tag", shop_id=str(shop), tag_id=str(tag))
    assert not result.get("isError"), result

    db.session.expire_all()
    revision = (
        db.session.query(RevisionTable)
        .filter(RevisionTable.entity_type == "tag", RevisionTable.entity_id == tag)
        .order_by(RevisionTable.revision_no.desc())
        .first()
    )
    assert revision.created_by == f"api_key:{row.id}"
    assert revision.source == "mcp"


# --- MCP roles -------------------------------------------------------------------
#
# Through MCP a Cognito user needs a role: shopvirge-mcp-viewers reads, shopvirge-
# mcp-operators reads and writes, and a member of neither may do nothing at all —
# admins included. API keys and M2M tokens are not people and are not subject to it. The tool list is not filtered (the list request carries no token on this
# fastmcp version); the refusal comes from the tier guards every tool call passes
# through. REST is unaffected: the same person keeps writing through shop-editor.


def test_user_without_an_mcp_role_can_do_nothing_through_mcp(mcp):
    shop = make_shop(random_shop_name=True)
    session = mcp("a-cognito-jwt", cognito_token=_cognito_token([str(shop)]))

    for name, args in (("list_my_shops", {}), ("list_products", {"shop_id": str(shop)})):
        denied = session.call(name, **args)
        assert denied.get("isError") and "403" in _error_text(denied), name


def test_viewer_can_read_but_not_write_through_mcp(mcp):
    shop = make_shop(random_shop_name=True)
    tag = make_tag(shop)
    session = mcp("a-cognito-jwt", cognito_token=_cognito_token([str(shop), MCP_VIEWERS_GROUP]))

    assert not session.call("list_my_shops").get("isError")
    assert not session.call("list_tags", shop_id=str(shop)).get("isError")
    denied = session.call("delete_tag", shop_id=str(shop), tag_id=str(tag))
    assert denied.get("isError") and "403" in _error_text(denied)
    assert TagTable.query.filter_by(id=tag).first() is not None


def test_operator_can_read_and_write_through_mcp(mcp):
    shop = make_shop(random_shop_name=True)
    tag = make_tag(shop)
    session = mcp("a-cognito-jwt", cognito_token=_cognito_token([str(shop), MCP_OPERATORS_GROUP]))

    assert not session.call("list_tags", shop_id=str(shop)).get("isError")
    assert not session.call("delete_tag", shop_id=str(shop), tag_id=str(tag)).get("isError")
    assert TagTable.query.filter_by(id=tag).first() is None


def test_admin_who_is_a_viewer_reads_any_shop_but_cannot_write(mcp):
    shop = make_shop(random_shop_name=True)
    tag = make_tag(shop)
    session = mcp("a-cognito-jwt", cognito_token=_cognito_token(["admins", MCP_VIEWERS_GROUP]))

    assert not session.call("list_tags", shop_id=str(shop)).get("isError")  # admin: any shop, reads
    denied = session.call("delete_tag", shop_id=str(shop), tag_id=str(tag))
    assert denied.get("isError") and "403" in _error_text(denied)
    assert TagTable.query.filter_by(id=tag).first() is not None


def test_admin_without_an_mcp_group_can_do_nothing_through_mcp(mcp):
    shop = make_shop(random_shop_name=True)
    tag = make_tag(shop)
    session = mcp("a-cognito-jwt", cognito_token=_cognito_token(["admins"]))

    for name, args in (("list_my_shops", {}), ("list_tags", {"shop_id": str(shop)})):
        denied = session.call(name, **args)
        assert denied.get("isError") and "403" in _error_text(denied), name
    assert session.call("delete_tag", shop_id=str(shop), tag_id=str(tag)).get("isError")
    assert TagTable.query.filter_by(id=tag).first() is not None


def test_mcp_roles_do_not_apply_to_rest(as_cognito_user):
    """A viewer, and a user with no MCP role, both write through REST as before."""
    shop = make_shop(random_shop_name=True)
    for groups in ([str(shop), MCP_VIEWERS_GROUP], [str(shop)]):
        tag = make_tag(shop)
        client = as_cognito_user(groups)
        assert client.delete(f"/shops/{shop}/tags/{tag}").status_code == 204, groups


def test_the_tier_guards_are_where_the_mcp_role_rule_lives(fastapi_app):
    """Drive the guards directly with MCP principals: viewer reads only, no-role gets nothing."""
    shop = make_shop(random_shop_name=True)
    tag = make_tag(shop)
    saved = fastapi_app.dependency_overrides.get(current_principal)
    client = TestClient(fastapi_app)
    try:
        fastapi_app.dependency_overrides[current_principal] = lambda: Principal(
            kind="user", subject="5678", groups=(str(shop), MCP_VIEWERS_GROUP), via="mcp"
        )
        assert client.delete(f"/shops/{shop}/tags/{tag}").status_code == 403
        assert client.get(f"/shops/{shop}/tags/").status_code == 200

        fastapi_app.dependency_overrides[current_principal] = lambda: Principal(
            kind="user", subject="5678", groups=(str(shop),), via="mcp"
        )
        assert client.get(f"/shops/{shop}/tags/").status_code == 403
        assert client.get("/shops/my-shops").status_code == 403
    finally:
        if saved is not None:
            fastapi_app.dependency_overrides[current_principal] = saved
