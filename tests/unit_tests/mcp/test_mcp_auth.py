# Copyright 2026 René Dohmen <acidjunk@gmail.com>
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
"""The MCP server authenticates every request with :class:`server.mcp.auth.PrincipalVerifier`.

These run over real HTTP through the mounted server, with the real
``current_principal`` (the conftest stub is lifted) and Cognito stubbed the way
``real_auth_client`` stubs it. API keys are looked up in the database inside the
verifier, which is also what proves the database session reaches it.
"""

import contextlib
import json
import re
from typing import Any, Optional

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import server.security
from server.crud.crud_api_key import api_key_crud
from server.db import db
from server.db.models import RevisionTable, TagTable
from server.mcp.server import MCP_MOUNT_PATH, mount_mcp
from server.security import READONLY_GROUP, Principal, current_principal
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


@pytest.fixture(scope="module")
def mcp_client(mcp_app):
    """One client for the module: the MCP session manager's lifespan may only be entered once."""
    with TestClient(mcp_app) as client:
        yield client


@pytest.fixture
def mcp(mcp_app, mcp_client, monkeypatch):
    """Factory for authenticated sessions; ``cognito_token`` is what Cognito 'verifies' for a non-key bearer."""
    override = mcp_app.dependency_overrides.pop(current_principal, None)
    state: dict[str, Any] = {"token": None}

    async def _cognito(connection):
        if state["token"] is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return state["token"]

    monkeypatch.setattr(server.security.cognito_eu, "auth_required", _cognito)
    monkeypatch.setattr(app_settings, "MCP_ENABLED", True)  # current_principal consults the MCP context only then
    try:

        def _session(bearer: Optional[str] = None, cognito_token=None) -> McpSession:
            state["token"] = cognito_token
            return McpSession(mcp_client, bearer)

        yield _session
    finally:
        if override is not None:
            mcp_app.dependency_overrides[current_principal] = override


def test_no_or_bad_credentials_are_refused_before_any_mcp_processing(mcp):
    shop = make_shop(random_shop_name=True)
    revoked, revoked_plaintext = make_api_key(shop)
    api_key_crud.revoke(shop_id=shop, key_id=revoked.id)

    assert mcp().initialize() == 401
    assert mcp("sv_bogus_notakey").initialize() == 401
    assert mcp(revoked_plaintext).initialize() == 401
    assert mcp("not-a-jwt").initialize() == 401  # Cognito stub refuses when no token is set


def test_api_key_lists_every_tool_and_reaches_only_its_own_shop(mcp):
    own, other = make_shop(random_shop_name=True), make_shop(random_shop_name=True)
    _, plaintext = make_api_key(own)
    session = mcp(plaintext)

    assert session.initialize() == 200
    assert session.tools() == sorted(EXPECTED_TOOL_NAMES)
    assert not session.call("list_products", shop_id=str(own)).get("isError")
    denied = session.call("list_products", shop_id=str(other))
    assert denied.get("isError") and "403" in denied["content"][0]["text"]


def test_cognito_user_is_scoped_by_its_groups(mcp):
    own, other = make_shop(random_shop_name=True), make_shop(random_shop_name=True)
    session = mcp("a-cognito-jwt", cognito_token=_cognito_token([str(own)]))

    assert session.initialize() == 200
    mine = session.call("list_my_shops")
    assert [shop["id"] for shop in mine["structuredContent"]["shops"]] == [str(own)]
    assert not mine["structuredContent"]["is_admin"]
    denied = session.call("list_products", shop_id=str(other))
    assert denied.get("isError") and "403" in denied["content"][0]["text"]


def test_tool_call_reuses_the_mcp_principal_so_audit_says_mcp(mcp):
    """The route takes the principal from fastmcp's context: same identity, and via='mcp' for the revision."""
    shop = make_shop(random_shop_name=True)
    tag = make_tag(shop)
    row, plaintext = make_api_key(shop)
    session = mcp(plaintext)
    session.initialize()

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


# --- mcp-read-only ---------------------------------------------------------------
#
# Membership of READONLY_GROUP means: through MCP, reads only. The verifier withholds
# the "write" scope, write tools carry require_scopes("write"), so fastmcp hides them
# on tools/list and refuses them on tools/call as unknown; require_shop refuses the
# write again underneath. REST is unaffected: the same person keeps writing through
# shop-editor.


def _read_tools(app) -> set[str]:
    """Every exposed GET route's tool name — what a read-only caller must see, and only that."""
    from fastapi.routing import APIRoute

    from server.agent_tags import AgentTag

    return {
        route.operation_id
        for route in app.routes
        if isinstance(route, APIRoute) and AgentTag.EXPOSED.value in (route.tags or []) and route.methods == {"GET"}
    }


def test_read_only_user_sees_only_read_tools_and_cannot_write(mcp, mcp_app):
    shop = make_shop(random_shop_name=True)
    tag = make_tag(shop)
    session = mcp("a-cognito-jwt", cognito_token=_cognito_token([str(shop), READONLY_GROUP]))
    session.initialize()

    assert set(session.tools()) == _read_tools(mcp_app)
    assert not session.call("list_tags", shop_id=str(shop)).get("isError")
    denied = session.call("delete_tag", shop_id=str(shop), tag_id=str(tag))
    assert denied.get("isError") and "Unknown tool" in denied["content"][0]["text"]
    assert TagTable.query.filter_by(id=tag).first() is not None


def test_read_only_wins_over_admin_through_mcp(mcp):
    shop = make_shop(random_shop_name=True)
    tag = make_tag(shop)
    session = mcp("a-cognito-jwt", cognito_token=_cognito_token(["admins", READONLY_GROUP]))
    session.initialize()

    assert not session.call("list_tags", shop_id=str(shop)).get("isError")  # admin: any shop, reads
    denied = session.call("delete_tag", shop_id=str(shop), tag_id=str(tag))
    assert denied.get("isError") and "Unknown tool" in denied["content"][0]["text"]
    assert TagTable.query.filter_by(id=tag).first() is not None


def test_read_only_applies_only_through_mcp(as_cognito_user):
    """The same group member writes through REST as before."""
    shop = make_shop(random_shop_name=True)
    tag = make_tag(shop)
    client = as_cognito_user([str(shop), READONLY_GROUP])

    assert client.delete(f"/shops/{shop}/tags/{tag}").status_code == 204


def test_route_guard_is_the_floor_for_a_read_only_mcp_principal(fastapi_app):
    """Even with the middleware out of the picture, require_shop refuses the write."""
    shop = make_shop(random_shop_name=True)
    tag = make_tag(shop)
    saved = fastapi_app.dependency_overrides.get(current_principal)
    fastapi_app.dependency_overrides[current_principal] = lambda: Principal(
        kind="user", subject="5678", groups=(str(shop), READONLY_GROUP), via="mcp"
    )
    try:
        client = TestClient(fastapi_app)
        assert client.delete(f"/shops/{shop}/tags/{tag}").status_code == 403
        assert client.get(f"/shops/{shop}/tags/").status_code == 200
    finally:
        fastapi_app.dependency_overrides[current_principal] = saved


# --- OAuth discovery ------------------------------------------------------------
#
# An OAuth client (e.g. LibreChat) needs the 401 to point it at the protected-resource
# metadata, per RFC 9728. mount_mcp wraps the server to advertise our own discovery
# endpoint, host-derived so it is correct from inside a container.


def test_anonymous_401_advertises_protected_resource_metadata(mcp_client):
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}},
    }
    r = mcp_client.post(f"{MCP_MOUNT_PATH}/", json=init, headers=HEADERS)
    assert r.status_code == 401
    challenge = r.headers.get("www-authenticate", "")
    match = re.search(r'resource_metadata="([^"]+)"', challenge)
    assert match, challenge

    # the advertised URL must resolve and name this server as the resource
    path = "/" + match.group(1).split("/", 3)[3]
    meta = mcp_client.get(path)
    assert meta.status_code == 200
    body = meta.json()
    assert body["resource"].rstrip("/").endswith("/mcp")
    assert body["authorization_servers"]
