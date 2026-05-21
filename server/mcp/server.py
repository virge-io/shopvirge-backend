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

Auth: ``from_fastapi`` invokes routes via in-process ``httpx`` over
``ASGITransport``, which goes through the FastAPI middleware + dependency
chain so the existing ``Depends(auth_required_any)`` on each route fires
normally when the LLM calls the corresponding MCP tool. We just need to
forward the incoming MCP request's auth headers (``Authorization`` for
Cognito JWT or API key, ``X-API-Key`` for the API key alternative) into
that inner httpx call, which fastmcp does NOT do by default — its
``get_http_headers()`` default exclude list strips ``authorization``.

Transport: streamable HTTP.

Pattern adapted from ``workfloworchestrator/orchestrator-core`` PR #1620.
"""

from typing import TYPE_CHECKING

import httpx
from fastapi import FastAPI

from server.agent_tags import AgentTag

if TYPE_CHECKING:
    from starlette.applications import Starlette

MCP_MOUNT_PATH = "/mcp"

_FORWARDED_AUTH_HEADERS = ("authorization", "x-api-key")


async def _forward_auth_header(request: httpx.Request) -> None:
    """Httpx request hook: forward the incoming MCP request's auth headers.

    fastmcp's ``OpenAPITool.run`` already auto-forwards request headers, but
    its default exclude list strips ``authorization`` (see
    ``fastmcp.server.dependencies.get_http_headers``). We re-add it — plus
    ``X-API-Key`` — so the route's ``Depends(auth_required_any)`` can
    validate either a bearer token or an API key.
    """
    from fastmcp.server.dependencies import get_http_headers

    auth_headers = get_http_headers(include=set(_FORWARDED_AUTH_HEADERS))
    for key, value in auth_headers.items():
        if key not in request.headers:
            request.headers[key] = value


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
    from fastmcp.server.openapi import MCPType, RouteMap

    mcp = FastMCP.from_fastapi(
        app=app,
        name="shopvirge-mcp",
        route_maps=[
            RouteMap(tags={AgentTag.EXPOSED.value}, mcp_type=MCPType.TOOL),
            RouteMap(mcp_type=MCPType.EXCLUDE),
        ],
        httpx_client_kwargs={"event_hooks": {"request": [_forward_auth_header]}},
    )

    mcp_app = mcp.http_app(path="/", transport="http")
    app.mount(MCP_MOUNT_PATH, mcp_app)
    return mcp_app
