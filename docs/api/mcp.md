# MCP server

ShopVirge exposes a [**Model Context Protocol**](https://modelcontextprotocol.io/) endpoint at `/mcp` so LLM clients (Claude Desktop, Claude Code, MCP Inspector, the OpenAI Agents SDK, etc.) can manage a shop's catalog — products, categories, tags, and attributes — through a typed tool interface.

The integration follows the pattern from [`workfloworchestrator/orchestrator-core` #1620](https://github.com/workfloworchestrator/orchestrator-core/pull/1620): tools are **auto-generated from the FastAPI route table** by [`fastmcp`](https://github.com/jlowin/fastmcp). Every REST route tagged `AgentTag.EXPOSED` becomes an MCP tool whose input/output schema is derived from the route's pydantic models and whose description is the route's docstring.

## What gets exposed

Twenty tools, one per shop CRUD operation. Tool names match the route's `operation_id`:

| Resource | List | Get | Create | Update | Delete |
|----------|------|-----|--------|--------|--------|
| Products | `list_products` | `get_product` | `create_product` | `update_product` | `delete_product` |
| Categories | `list_categories` | `get_category` | `create_category` | `update_category` | `delete_category` |
| Tags | `list_tags` | `get_tag` | `create_tag` | `update_tag` | `delete_tag` |
| Attributes | `list_attributes` | `get_attribute` | `create_attribute` | `update_attribute` | `delete_attribute` |

List tools also carry `AgentTag.LARGE`, signalling to well-behaved clients that they should filter before calling.

Any route *not* tagged with `AgentTag.EXPOSED` is invisible to MCP — even though it's still served by the same REST API. Orders, accounts, prices, Stripe, shop config etc. are intentionally REST-only.

## Enabling the endpoint

Off by default. Turn it on per environment by setting:

```bash
MCP_ENABLED=true
```

When enabled, `server/main.py` calls `mount_mcp(app)` after all routers are included, mounts the sub-app at `/mcp`, and enters its lifespan from the parent FastAPI lifespan (Starlette does not run mounted sub-app lifespans automatically). The transport is **streamable HTTP**.

## Authentication

Two methods are accepted on `/mcp` and on the tagged CRUD endpoints. They are checked in this order:

1. **API key** — `X-API-Key: sv_<prefix>_<rest>` header, *or* `Authorization: Bearer sv_<prefix>_<rest>`. Recommended for headless LLM clients.
2. **Cognito JWT** — `Authorization: Bearer <jwt>`. Same flow as the regular REST API; useful when a logged-in user drives the agent from a browser.

The dual-auth dependency is `server.security.auth_required_any`. It either resolves the API key against the `api_keys` table (returning the matched row) or delegates to the existing Cognito flow (returning a `CustomCognitoToken`). Endpoints not tagged for MCP still use `auth_required` (Cognito only) — an API key cannot reach the full REST surface.

### Issuing an API key

API key management is **Cognito-only by design** — an API key cannot mint another API key.

Mint a key (one-time plaintext in the response):

```bash
curl -sX POST https://api.example.com/shops/$SHOP_ID/api-keys/ \
  -H "Authorization: Bearer $COGNITO_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "claude-desktop"}'
```

```json
{
  "id": "8fd1…",
  "name": "claude-desktop",
  "prefix": "Lk3Df-9z",
  "plaintext": "sv_Lk3Df-9z_xK8nQ…",
  "created_at": "2026-05-21T08:14:22Z",
  "last_used_at": null,
  "revoked_at": null
}
```

`plaintext` is returned **exactly once**. Store it somewhere safe; subsequent `GET /shops/{shop_id}/api-keys/` listings only return the prefix. The server stores two derived values and never the raw key: a `sha256` *fingerprint* (indexed for O(1) lookup, safe to leak in logs) and a `bcrypt` hash that the request handler bcrypt-verifies on every call. A DB dump alone cannot yield usable keys.

List keys:

```bash
curl -s https://api.example.com/shops/$SHOP_ID/api-keys/ \
  -H "Authorization: Bearer $COGNITO_ACCESS_TOKEN"
```

Revoke a key (subsequent requests with it return `401`):

```bash
curl -X DELETE https://api.example.com/shops/$SHOP_ID/api-keys/$KEY_ID \
  -H "Authorization: Bearer $COGNITO_ACCESS_TOKEN"
```

## Connecting an MCP client

### Claude Desktop / Claude Code

Add an entry to the client's MCP config (`~/.claude/mcp.json` or the Claude Desktop UI):

```json
{
  "mcpServers": {
    "shopvirge": {
      "url": "https://api.example.com/mcp/",
      "transport": "http",
      "headers": {
        "Authorization": "Bearer sv_Lk3Df-9z_xK8nQ…"
      }
    }
  }
}
```

### MCP Inspector

```bash
npx @modelcontextprotocol/inspector https://api.example.com/mcp/ \
  --header "Authorization=Bearer sv_Lk3Df-9z_xK8nQ…"
```

### Quick `curl` smoke test

```bash
curl -X POST https://api.example.com/mcp/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H "Authorization: Bearer $SV_API_KEY" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

You should see all 20 tool definitions in the response.

## How auth flows through `from_fastapi`

`FastMCP.from_fastapi(app=…)` invokes the underlying routes via in-process `httpx` over an `ASGITransport`. That means every MCP tool call **goes through the FastAPI middleware and dependency chain** — including `auth_required_any`. The only thing fastmcp does *not* do by default is forward auth headers: its `get_http_headers()` exclude list strips `authorization`.

`server/mcp/server.py` adds a small httpx request hook that re-injects both `Authorization` and `X-API-Key` on every internal call, so per-route auth fires exactly as it would over plain REST.

## Adding a new tool

1. Add `from server.agent_tags import AgentTag` to the endpoint module.
2. On the route decorator, add:
   - `tags=[AgentTag.EXPOSED]` (add `AgentTag.LARGE` too for list endpoints).
   - `operation_id="<short_snake_case>"`. **This becomes the MCP tool name** — treat it like a public API contract.
3. Switch the router-level dependency to `Depends(auth_required_any)` if you want API-key clients to reach it. (Cognito-only endpoints stay on `auth_required`.)
4. Bump `APP_VERSION` in `server/main.py` and regenerate `tests/unit_tests/openapi_snapshot.json` (see the OpenAPI drift guard).
5. Update `EXPECTED_TOOL_NAMES` in `tests/unit_tests/mcp/test_mcp.py`.

The docstring on the handler becomes the tool description — write it for an LLM, not a developer. State the *intent*, list *required* parameters, and call out side effects.

## Architecture notes

- **Pure-ASGI middleware.** `DBSessionMiddleware` in `server/db/database.py` was rewritten from `BaseHTTPMiddleware` to a pure ASGI `__call__(scope, receive, send)`. `BaseHTTPMiddleware` buffers the response body, which breaks the `StreamableHTTPSessionManager` used by `/mcp`. Any new middleware in front of `/mcp` must be pure-ASGI.
- **Lifespan composition.** `server/main.py` holds a module-level `mcp_app` that is `None` until the MCP mount runs. The parent lifespan enters `mcp_app.router.lifespan_context(app_)` only when it's set, so the boot path with `MCP_ENABLED=false` is unchanged.
- **Tool surface scoping.** `RouteMap(tags={AgentTag.EXPOSED.value}, mcp_type=MCPType.TOOL)` is followed by `RouteMap(mcp_type=MCPType.EXCLUDE)` so any route the developer forgets to tag is silently excluded — the default is *not* "expose everything."

## Settings

| Variable | Default | Purpose |
|----------|---------|---------|
| `MCP_ENABLED` | `false` | Mount `/mcp` and enter its lifespan. |

API keys themselves are stored in the `api_keys` table (migration `c1a2b3d4e5f6`) and need no env config.

## Related files

- `server/mcp/server.py` — `mount_mcp(app)` and the auth-header forwarding hook.
- `server/agent_tags.py` — the `AgentTag` enum.
- `server/security.py` — `auth_required_any` dual-auth dependency.
- `server/crud/crud_api_key.py` — minting, lookup, revocation.
- `server/api/endpoints/shop_endpoints/api_keys.py` — REST management endpoints.
- `tests/unit_tests/mcp/test_mcp.py` — verifies tag coverage and `FastMCP.from_fastapi` introspection.
