# Copyright 2026 René Dohmen <acidjunk@gmail.com>
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
"""MCP (Model Context Protocol) server exposing shop-backend operations as tools.

Mounted into the FastAPI app at ``/mcp`` when ``MCP_ENABLED=True`` (see
``server/main.py``).

Tools are **auto-generated from the FastAPI app's routes** via ``fastmcp``'s
``FastMCP.from_fastapi(app=...)``. Every REST operation tagged
``AgentTag.EXPOSED`` becomes an MCP tool with a typed parameter schema
derived from the route's pydantic models, plus the route's docstring as the
tool description.

Auth: every MCP request is authenticated by :class:`server.mcp.auth.PrincipalVerifier`
(a fastmcp ``TokenVerifier``) before any MCP processing, so an anonymous client
cannot even list tools. A tool call then reaches its route via in-process
``httpx`` over ``ASGITransport``; ``current_principal`` picks the already verified
principal up from fastmcp's access-token context, so the route's guards run
against the same principal without re-authenticating and without relying on
header forwarding.

Transport: streamable HTTP.

Pattern adapted from ``workfloworchestrator/orchestrator-core`` PR #1620.
"""

from typing import TYPE_CHECKING, Any

from fastapi import FastAPI

from server.agent_tags import AgentTag

if TYPE_CHECKING:
    from starlette.applications import Starlette

MCP_MOUNT_PATH = "/mcp"


def _advertise_resource_metadata(app: Any) -> Any:
    """Append ``resource_metadata=…`` to the MCP server's 401 ``WWW-Authenticate``.

    The URL is built from the request host so it is correct whether the client
    reaches us as ``localhost``, ``host.docker.internal`` or the public origin.
    """
    from starlette.datastructures import MutableHeaders

    async def wrapped(scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await app(scope, receive, send)
            return
        request_headers = {k.decode(): v.decode() for k, v in scope.get("headers") or []}
        host = request_headers.get("host", "")
        scheme = "https" if request_headers.get("x-forwarded-proto") == "https" else scope.get("scheme", "http")
        metadata_url = f"{scheme}://{host}/.well-known/oauth-protected-resource"

        async def send_wrapper(message: Any) -> None:
            if message["type"] == "http.response.start" and message["status"] == 401 and host:
                headers = MutableHeaders(raw=message.setdefault("headers", []))
                challenge = headers.get("www-authenticate")
                if challenge and "resource_metadata=" not in challenge:
                    headers["www-authenticate"] = f'{challenge}, resource_metadata="{metadata_url}"'
            await send(message)

        await app(scope, receive, send_wrapper)

    return wrapped


def _gate_writes(route: Any, component: Any) -> None:
    """Anything but ``GET`` writes, so it requires the ``write`` scope.

    The verifier withholds that scope from the read-only group, and fastmcp then
    hides the tool from and refuses it for such a caller.
    """
    from fastmcp.utilities.authorization import require_scopes

    if route.method != "GET":
        component.auth = require_scopes("write")


def mount_mcp(app: FastAPI) -> "Starlette":
    """Auto-generate MCP tools from ``app``'s routes, mount at ``/mcp``, return the sub-app.

    Only routes tagged with ``AgentTag.EXPOSED`` are surfaced; all other
    routes are excluded (otherwise fastmcp's default would expose every
    route in the app as a tool).

    The returned sub-app carries its own ASGI lifespan that the parent must
    enter — Starlette does not invoke a mounted sub-app's lifespan. Use
    ``mcp_app.router.lifespan_context(parent)`` from inside the parent's
    own lifespan context manager.
    """
    from fastmcp import FastMCP
    from fastmcp.server.providers.openapi import MCPType, RouteMap

    from server.mcp.auth import PrincipalVerifier

    mcp = FastMCP.from_fastapi(
        app=app,
        name="shopvirge-mcp",
        route_maps=[
            RouteMap(tags={AgentTag.EXPOSED.value}, mcp_type=MCPType.TOOL),
            RouteMap(mcp_type=MCPType.EXCLUDE),
        ],
        mcp_component_fn=_gate_writes,
        auth=PrincipalVerifier(),
    )

    mcp_app = mcp.http_app(path="/", transport="http")
    # OAuth clients (e.g. LibreChat) must be told where the protected-resource
    # metadata lives (RFC 9728). We advertise it ourselves rather than via fastmcp's
    # ``base_url`` for two reasons: fastmcp's ``TokenVerifier`` advertises a metadata
    # URL but serves nothing there (``get_routes()`` is empty), and it builds that URL
    # from a static base, whereas RFC 9728 §3.3 wants the resource to match the URL the
    # client actually used. So we derive the host from the request and point at our own
    # discovery endpoint (server/api/endpoints/system/oauth_discovery.py), which does
    # the same. (Token acceptance does not need ``base_url``; the verifier authenticates
    # the bearer directly.)
    app.mount(MCP_MOUNT_PATH, _advertise_resource_metadata(mcp_app))
    return mcp_app
