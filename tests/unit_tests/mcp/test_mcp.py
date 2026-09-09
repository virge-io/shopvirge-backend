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
    # product tag assignments
    "list_product_to_tags",
    "get_product_to_tag_relation_id",
    "get_product_to_tag",
    "create_product_to_tag",
    "update_product_to_tag",
    "delete_product_to_tag",
    # attributes
    "list_attributes",
    "get_attribute",
    "create_attribute",
    "update_attribute",
    "delete_attribute",
    # attribute options (used to select product attribute assignments)
    "list_attribute_options",
    "get_attribute_option",
    "create_attribute_option",
    "update_attribute_option",
    "delete_attribute_option",
    # product attribute assignments
    "add_product_attribute_options",
    "get_product_attributes",
    "product_attribute_values_replace_for_product",
    "product_attribute_values_delete",
    # revisions / trash
    "list_shop_revisions",
    "get_revision",
    "list_product_revisions",
    "get_product_revision",
    "restore_product_revision",
    "restore_product",
    "restore_category",
    "restore_category_revision",
    "restore_tag_revision",
    "restore_tag",
    "restore_attribute_revision",
    "restore_attribute",
    # shops
    "list_my_shops",
    # orders (read-only)
    "list_pending_orders",
    "list_complete_orders",
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
    from fastmcp.server.openapi import MCPType, RouteMap

    from server.mcp.server import mount_mcp  # noqa: F401 — sanity import

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


def test_update_product_tool_has_no_required_body_fields(fastapi_app: FastAPI) -> None:
    """The update_product tool must not force the LLM to send the full product.

    Required image_1..image_6 fields made the model emit `"image_6": null` for
    empty slots, which triggered malformed streamed tool JSON under Anthropic's
    fine-grained-tool-streaming beta. Only the path params may be required.
    """
    pytest.importorskip("fastmcp")
    from fastmcp import FastMCP
    from fastmcp.server.openapi import MCPType, RouteMap

    mcp = FastMCP.from_fastapi(
        app=fastapi_app,
        name="shopvirge-mcp-test",
        route_maps=[
            RouteMap(tags={AgentTag.EXPOSED.value}, mcp_type=MCPType.TOOL),
            RouteMap(mcp_type=MCPType.EXCLUDE),
        ],
    )

    tools = asyncio.run(mcp.get_tools())
    schema = tools["update_product"].parameters
    required = set(schema.get("required", []))
    assert not any(r.startswith("image_") for r in required), f"image fields still required: {required}"
    assert "translation" not in required, f"translation still required: {required}"


def test_update_category_tool_has_no_required_body_fields(fastapi_app: FastAPI) -> None:
    """The update_category tool must not force the LLM to send the full category.

    Same failure mode as update_product: required main_image/alt1_image/alt2_image
    fields made the model emit `"alt2_image": null` for empty slots, which triggered
    malformed streamed tool JSON under Anthropic's fine-grained-tool-streaming beta.
    Only the path params may be required.
    """
    pytest.importorskip("fastmcp")
    from fastmcp import FastMCP
    from fastmcp.server.openapi import MCPType, RouteMap

    mcp = FastMCP.from_fastapi(
        app=fastapi_app,
        name="shopvirge-mcp-test",
        route_maps=[
            RouteMap(tags={AgentTag.EXPOSED.value}, mcp_type=MCPType.TOOL),
            RouteMap(mcp_type=MCPType.EXCLUDE),
        ],
    )

    tools = asyncio.run(mcp.get_tools())
    schema = tools["update_category"].parameters
    required = set(schema.get("required", []))
    assert not any(r.endswith("_image") for r in required), f"image fields still required: {required}"
    assert "translation" not in required, f"translation still required: {required}"


def test_mount_mcp_is_importable() -> None:
    """The mount_mcp helper imports cleanly (catches dotted-path drift in fastmcp)."""
    pytest.importorskip("fastmcp")
    from server.mcp import mount_mcp

    assert callable(mount_mcp)
