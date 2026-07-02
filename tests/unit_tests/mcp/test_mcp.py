# Copyright 2026 René Dohmen <acidjunk@gmail.com>
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
"""Tests for the MCP (Model Context Protocol) server integration.

These tests verify that:

1. The agent-tagged shop CRUD routes carry ``AgentTag.EXPOSED`` and have
   stable ``operation_id`` values that map 1:1 to the MCP tool names.
2. ``FastMCP.from_fastapi`` introspects the FastAPI app's routes, derives
   input schemas from their pydantic models, and produces exactly the tools
   we expect via ``RouteMap`` tag-based filtering.

Pattern adapted from ``workfloworchestrator/orchestrator-core`` PR #1620.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI

from server.agent_tags import AgentTag

# All tool names must match the ``operation_id`` on each tagged route.
EXPECTED_TOOL_NAMES = {
    # products
    "list_products",
    "get_product",
    "create_product",
    "update_product",
    "delete_product",
    # categories
    "list_categories",
    "get_category",
    "create_category",
    "update_category",
    "delete_category",
    # tags
    "list_tags",
    "get_tag",
    "create_tag",
    "update_tag",
    "delete_tag",
    # attributes
    "list_attributes",
    "get_attribute",
    "create_attribute",
    "update_attribute",
    "delete_attribute",
    # revisions / trash
    "list_shop_revisions",
    "get_revision",
    "list_product_revisions",
    "get_product_revision",
    "restore_product_revision",
    "restore_product",
    "restore_category",
    # shops
    "list_my_shops",
}


def _agent_tagged_routes(app: FastAPI) -> dict[str, str]:
    """Return ``{operation_id: path}`` for every route tagged ``AgentTag.EXPOSED``."""
    out: dict[str, str] = {}
    for route in app.routes:
        tags = getattr(route, "tags", None) or []
        if AgentTag.EXPOSED.value in tags or AgentTag.EXPOSED in tags:
            op_id = getattr(route, "operation_id", None)
            path = getattr(route, "path", "")
            assert op_id, f"agent-exposed route {path!r} is missing operation_id"
            out[op_id] = path
    return out


def test_all_expected_routes_carry_agent_tag(fastapi_app: FastAPI) -> None:
    """Every expected MCP tool name has a route tagged ``AgentTag.EXPOSED``."""
    found = _agent_tagged_routes(fastapi_app)
    assert (
        set(found) == EXPECTED_TOOL_NAMES
    ), f"missing: {EXPECTED_TOOL_NAMES - set(found)}, extra: {set(found) - EXPECTED_TOOL_NAMES}"


def test_fastmcp_introspects_all_expected_tools(fastapi_app: FastAPI) -> None:
    """``FastMCP.from_fastapi`` produces exactly the expected tools from the tagged routes."""
    pytest.importorskip("fastmcp")
    from fastmcp import FastMCP

    from server.mcp.server import mount_mcp  # noqa: F401 — sanity import

    try:
        from fastmcp.server.openapi import MCPType, RouteMap
    except ImportError:  # pragma: no cover — older fastmcp module path
        from fastmcp.server.providers.openapi import MCPType, RouteMap  # type: ignore[no-redef]

    mcp = FastMCP.from_fastapi(
        app=fastapi_app,
        name="shopvirge-mcp-test",
        route_maps=[
            RouteMap(tags={AgentTag.EXPOSED.value}, mcp_type=MCPType.TOOL),
            RouteMap(mcp_type=MCPType.EXCLUDE),
        ],
    )

    tools = asyncio.run(mcp.get_tools())
    tool_names = set(tools.keys())
    assert (
        tool_names == EXPECTED_TOOL_NAMES
    ), f"missing: {EXPECTED_TOOL_NAMES - tool_names}, extra: {tool_names - EXPECTED_TOOL_NAMES}"


def test_mount_mcp_is_importable() -> None:
    """The mount_mcp helper imports cleanly (catches dotted-path drift in fastmcp)."""
    pytest.importorskip("fastmcp")
    from server.mcp import mount_mcp

    assert callable(mount_mcp)
