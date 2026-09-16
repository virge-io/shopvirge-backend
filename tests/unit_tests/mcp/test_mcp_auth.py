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
import re

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import server.security
from server.db import db
from server.db.models import RevisionTable, TagTable
from server.mcp.server import MCP_MOUNT_PATH, mount_mcp
from server.security import MCP_OPERATORS_GROUP, MCP_VIEWERS_GROUP, current_principal
from server.settings import app_settings
from tests.unit_tests.conftest import _cognito_token
from tests.unit_tests.factories.api_key import make_api_key
from tests.unit_tests.factories.shop import make_shop
from tests.unit_tests.factories.tag import make_tag
from tests.unit_tests.mcp.test_mcp import EXPECTED_TOOL_NAMES

HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def mcp_client(fastapi_app):
    """One client for the module: the MCP session manager's lifespan may only be entered once.

    Starlette does not run a mounted app's lifespan, so the parent enters it.
    """
    if not any(getattr(route, "path", None) == MCP_MOUNT_PATH for route in fastapi_app.routes):
        sub_app = mount_mcp(fastapi_app)

        @contextlib.asynccontextmanager
        async def lifespan(app):
            async with sub_app.router.lifespan_context(app):
                yield

        fastapi_app.router.lifespan_context = lifespan
    with TestClient(fastapi_app) as client:
        yield client


class McpSession:
    """Just enough JSON-RPC over streamable HTTP to list and call tools as one caller."""

    def __init__(self, client: TestClient, bearer: str | None):
        self.client, self.bearer, self.session_id, self._id = client, bearer, None, 0
        self._rpc(
            "initialize",
            {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}},
        )
        self._rpc("notifications/initialized", notify=True)

    def _rpc(self, method: str, params: dict | None = None, *, notify: bool = False) -> dict | None:
        body: dict = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notify:
            self._id += 1
            body["id"] = self._id
        headers = dict(HEADERS)
        if self.bearer:
            headers["Authorization"] = f"Bearer {self.bearer}"
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        response = self.client.post(f"{MCP_MOUNT_PATH}/", json=body, headers=headers)
        assert response.status_code in (200, 202), response.text  # the transport is open; 202 = notification
        self.session_id = response.headers.get("mcp-session-id", self.session_id)
        events = [json.loads(line[5:]) for line in response.text.splitlines() if line.startswith("data:")]
        return events[-1] if events else None

    def tools(self) -> list[str]:
        return sorted(tool["name"] for tool in self._rpc("tools/list")["result"]["tools"])

    def call(self, name: str, **arguments) -> dict:
        return self._rpc("tools/call", {"name": name, "arguments": arguments})["result"]


def status_of(result: dict) -> int | None:
    """The HTTP status the route answered with, taken from fastmcp's tool error; ``None`` if the call succeeded."""
    if not result.get("isError"):
        return None
    match = re.search(r"HTTP error (\d{3})", result["content"][0]["text"])
    return int(match.group(1)) if match else -1


@pytest.fixture
def mcp(mcp_client, monkeypatch):
    """Session factory; ``cognito_token`` is what Cognito 'verifies' for a bearer that is not an API key."""
    token = [None]

    async def _cognito(connection):
        if token[0] is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return token[0]

    monkeypatch.setattr(server.security.cognito_eu, "auth_required", _cognito)
    monkeypatch.setattr(app_settings, "MCP_ENABLED", True)  # ``via`` is derived from the MCP context only then
    monkeypatch.delitem(mcp_client.app.dependency_overrides, current_principal, raising=False)  # run the real one

    def _session(bearer: str | None = None, cognito_token=None) -> McpSession:
        token[0] = cognito_token
        return McpSession(mcp_client, bearer)

    return _session


def test_transport_is_open_but_tool_calls_are_authenticated_by_the_route(mcp):
    shop = make_shop(random_shop_name=True)
    session = mcp()

    assert session.tools() == sorted(EXPECTED_TOOL_NAMES)
    assert status_of(session.call("list_products", shop_id=str(shop))) == 401


def test_api_key_bearer_is_forwarded_and_bound_to_its_shop(mcp):
    own, other = make_shop(random_shop_name=True), make_shop(random_shop_name=True)
    _, plaintext = make_api_key(own)
    session = mcp(plaintext)

    assert status_of(session.call("list_products", shop_id=str(own))) is None
    assert status_of(session.call("list_products", shop_id=str(other))) == 403


def test_cognito_user_is_scoped_by_its_groups(mcp):
    own, other = make_shop(random_shop_name=True), make_shop(random_shop_name=True)
    session = mcp("a-cognito-jwt", cognito_token=_cognito_token([str(own), MCP_OPERATORS_GROUP]))

    mine = session.call("list_my_shops")
    assert [shop["id"] for shop in mine["structuredContent"]["shops"]] == [str(own)]
    assert not mine["structuredContent"]["is_admin"]
    assert status_of(session.call("list_products", shop_id=str(other))) == 403


def test_tool_call_is_recorded_with_source_mcp(mcp):
    """``via`` comes from fastmcp's request context, so the revision row says where the write came from."""
    shop = make_shop(random_shop_name=True)
    tag = make_tag(shop)
    row, plaintext = make_api_key(shop)

    assert status_of(mcp(plaintext).call("delete_tag", shop_id=str(shop), tag_id=str(tag))) is None

    db.session.expire_all()
    revision = (
        db.session.query(RevisionTable)
        .filter(RevisionTable.entity_type == "tag", RevisionTable.entity_id == tag)
        .order_by(RevisionTable.revision_no.desc())
        .first()
    )
    assert revision.created_by == f"api_key:{row.id}"
    assert revision.source == "mcp"


# Through MCP a Cognito user needs a role: shopvirge-mcp-viewers reads, shopvirge-mcp-operators
# reads and writes, and a member of neither may do nothing at all — admins included. API keys
# and M2M tokens are not people and are not subject to it. The tool list is not filtered (the
# list request carries no token on this fastmcp version); the refusal comes from the tier guards
# every tool call passes through: require_cognito (list_my_shops) and require_shop (the rest).
# "{shop}" below stands for the caller's own shop-UUID group.
@pytest.mark.parametrize(
    ("groups", "read", "write"),
    [
        pytest.param(["{shop}"], 403, 403, id="no-mcp-group"),
        pytest.param(["admins"], 403, 403, id="admin-without-mcp-group"),
        pytest.param(["{shop}", MCP_VIEWERS_GROUP], None, 403, id="viewer"),
        pytest.param(["admins", MCP_VIEWERS_GROUP], None, 403, id="admin-who-is-a-viewer"),
        pytest.param(["{shop}", MCP_OPERATORS_GROUP], None, None, id="operator"),
    ],
)
def test_mcp_role_decides_what_a_user_may_do(mcp, groups, read, write):
    shop = make_shop(random_shop_name=True)
    tag = make_tag(shop)
    session = mcp("a-cognito-jwt", cognito_token=_cognito_token([g.format(shop=shop) for g in groups]))

    assert status_of(session.call("list_my_shops")) == read
    assert status_of(session.call("list_tags", shop_id=str(shop))) == read
    assert status_of(session.call("delete_tag", shop_id=str(shop), tag_id=str(tag))) == write
    assert (TagTable.query.filter_by(id=tag).first() is None) == (write is None)


def test_mcp_roles_do_not_apply_to_rest(as_cognito_user):
    """A viewer, and a user with no MCP role, both write through REST as before."""
    shop = make_shop(random_shop_name=True)
    for groups in ([str(shop), MCP_VIEWERS_GROUP], [str(shop)]):
        tag = make_tag(shop)
        assert as_cognito_user(groups).delete(f"/shops/{shop}/tags/{tag}").status_code == 204, groups
