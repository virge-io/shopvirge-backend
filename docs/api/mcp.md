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

Three methods are accepted on `/mcp` and on the tagged CRUD endpoints. They are checked in this order:

1. **API key** — `X-API-Key: sv_<prefix>_<rest>` header, *or* `Authorization: Bearer sv_<prefix>_<rest>`. Recommended for headless LLM clients.
2. **Cognito JWT (M2M / service-to-service)** — `Authorization: Bearer <jwt>` with scope ending in `/api`.
3. **Cognito JWT (interactive user)** — `Authorization: Bearer <jwt>` from the Next.js app client or the MCP browser-login flow. Useful when a logged-in user drives the agent from a browser.

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

### Claude Code — browser login (Cognito Hosted UI)

The MCP server publishes OAuth discovery metadata so Claude Code can drive Cognito's Hosted UI directly. Add the server with a fixed callback port (must match the Cognito app client's whitelisted redirect URI — currently `7777`):

```bash
claude mcp add --transport http shopvirge https://api.shopvirge.com/mcp/ \
  --callback-port 7777
```

Inside Claude Code, run `/mcp` → **Authenticate**. Your browser opens the Cognito Hosted UI, you sign in with your normal credentials, and the access token lands back in Claude Code. From there every tool call carries `Authorization: Bearer <cognito-jwt>` automatically.

Three discovery endpoints make this work; see [OAuth discovery](#oauth-discovery-claude-code-browser-login) below for the full chain.

### Claude Desktop / Claude Code — static API key

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

`FastMCP.from_fastapi(app=…)` invokes the underlying routes via in-process `httpx` over an `ASGITransport`. That means every MCP tool call **goes through the FastAPI middleware and dependency chain** — including `auth_required_any`.

fastmcp 2.14.x's `OpenAPITool.run` auto-forwards the incoming MCP request's headers into the inner httpx call, and its default exclude list does NOT strip `authorization` or `x-api-key` — so either credential reaches the underlying route's auth dependency without extra plumbing. (Earlier revisions of this module ran a custom forwarding hook for this; it was removed when it turned out to crash the call in 2.14.x — see commit history of `server/mcp/server.py`.)

## OAuth discovery (Claude Code browser-login)

MCP clients that follow the [MCP 2025-06-18](https://modelcontextprotocol.io/) auth spec bootstrap their OAuth flow via RFC 9728 / RFC 8414 / RFC 7591. Cognito covers most of that out of the box but does **not** support Dynamic Client Registration (RFC 7591), which Claude Code's MCP SDK attempts unconditionally even when a static `client_id` is configured ([anthropics/claude-code#26675](https://github.com/anthropics/claude-code/issues/26675)).

To bridge that gap, `server/api/endpoints/oauth_discovery.py` mounts three unauthenticated endpoints at the app root:

| Path | Spec | Purpose |
|------|------|---------|
| `GET /.well-known/oauth-protected-resource` | RFC 9728 | Points clients at the authorization server (`PUBLIC_BASE_URL`). |
| `GET /.well-known/oauth-authorization-server` | RFC 8414 | Cognito's OIDC metadata stitched together with our shim's `registration_endpoint`. `issuer` deliberately matches Cognito's so token-`iss` validation succeeds client-side. |
| `POST /oauth/register` | RFC 7591 | DCR shim — ignores the body and returns `AWS_COGNITO_MCP_CLIENT_ID` verbatim. Cognito enforces the real redirect-URI allowlist at the authorize step. |

The Hosted UI base URL is resolved once at import time from Cognito's `/.well-known/openid-configuration`, so changing the user pool's Hosted UI domain in the future doesn't require a code edit.

End-to-end flow when a user clicks **Authenticate**:

1. Claude Code GETs `/.well-known/oauth-protected-resource`
2. Follows to `/.well-known/oauth-authorization-server`
3. POSTs `/oauth/register` → gets static `AWS_COGNITO_MCP_CLIENT_ID`
4. Opens Cognito Hosted UI → user signs in → redirect to `http://localhost:<callback-port>/callback`
5. Exchanges code at Cognito's `token_endpoint`
6. Calls MCP tools with `Authorization: Bearer <cognito-jwt>`

### Cognito app client setup

The pre-registered Cognito app client backs the static `client_id` the DCR shim returns. The `client_id` is non-secret (it appears in every browser URL during auth) and is deployed as `AWS_COGNITO_MCP_CLIENT_ID`.

Create it via CLI:

```bash
aws cognito-idp create-user-pool-client \
  --region eu-central-1 \
  --user-pool-id <USERPOOL_ID> \
  --client-name shopvirge-mcp \
  --no-generate-secret \
  --explicit-auth-flows ALLOW_USER_SRP_AUTH ALLOW_USER_PASSWORD_AUTH ALLOW_REFRESH_TOKEN_AUTH \
  --supported-identity-providers COGNITO \
  --callback-urls 'http://localhost:7777/callback' 'http://127.0.0.1:7777/callback' \
  --logout-urls  'http://localhost:7777/callback' 'http://127.0.0.1:7777/callback' \
  --allowed-o-auth-flows code \
  --allowed-o-auth-scopes openid email profile \
  --allowed-o-auth-flows-user-pool-client \
  --read-attributes email email_verified family_name given_name name preferred_username \
  --write-attributes email family_name given_name name preferred_username \
  --prevent-user-existence-errors ENABLED \
  --enable-token-revocation \
  --auth-session-validity 3 \
  --access-token-validity 60 \
  --id-token-validity 60 \
  --refresh-token-validity 30 \
  --token-validity-units 'AccessToken=minutes,IdToken=minutes,RefreshToken=days'
```

The CLI prints a `ClientId` — copy it into `apprunner.yaml` as `AWS_COGNITO_MCP_CLIENT_ID` and redeploy.

#### ⚠️ Managed Login branding (required step the CLI doesn't cover)

User pools created in 2024-2025 default to **Managed Login** for new app clients. Until you explicitly assign a Managed Login branding style to a new client, its Hosted UI returns `403 "Login pages unavailable"` — even from the console's own "View login page" button. **Older app clients in the same user pool keep working because they still use the legacy Hosted UI.**

There is currently no clean CLI command to assign branding. Do it once per new client via the console:

1. `Cognito → User pool → App integration → Managed login branding versions`.
2. Open the default style (create one if none exists; empty/default styling is fine).
3. Scroll to the "App clients" section and add the new MCP client. Save.
4. Re-test by hitting the "View login page" button on the client — it should now render Cognito's sign-in page instead of "Login pages unavailable".

#### Callback URLs: register both `localhost` and `127.0.0.1`

Claude Code's MCP SDK sends `http://localhost:<port>/callback` as the `redirect_uri`. The Cognito console's "Quick setup" wizard for **Mobile app** / **SPA** presets sometimes rejects `http://localhost:…` at create time but accepts `http://127.0.0.1:…`. To avoid a `redirect_uri mismatch` at sign-in, **whitelist both** variants — the CLI command above does this. If you've already created the client and only registered `127.0.0.1`, update it with `aws cognito-idp update-user-pool-client --callback-urls '<both>'`.

#### Rotation

To rotate the client, run the same `create-user-pool-client` command again with a new name, redo the Managed Login branding step, update `AWS_COGNITO_MCP_CLIENT_ID` in `apprunner.yaml`, deploy, and finally delete the old client with `aws cognito-idp delete-user-pool-client`.

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
| `AWS_COGNITO_MCP_CLIENT_ID` | `""` | Pre-registered Cognito public PKCE client returned by the DCR shim. Required for the browser-login flow. Non-secret. |
| `PUBLIC_BASE_URL` | `http://localhost:8080` | Backend's public origin. Used to build absolute URLs in the OAuth discovery documents (`resource`, `authorization_servers`, `registration_endpoint`). |

API keys themselves are stored in the `api_keys` table (migration `c1a2b3d4e5f6`) and need no env config.

## Related files

- `server/mcp/server.py` — `mount_mcp(app)`.
- `server/agent_tags.py` — the `AgentTag` enum.
- `server/security.py` — `auth_required` / `auth_required_any` dependencies.
- `server/crud/crud_api_key.py` — minting, lookup, revocation.
- `server/api/endpoints/shop_endpoints/api_keys.py` — REST management endpoints.
- `server/api/endpoints/oauth_discovery.py` — OAuth discovery + DCR shim for the browser-login flow.
- `tests/unit_tests/mcp/test_mcp.py` — verifies tag coverage and `FastMCP.from_fastapi` introspection.
