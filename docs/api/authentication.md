---
title: Authentication & Authorization
description: Cognito token handling and shop access via AWS Cognito.
---

# Authentication

Authentication lives in `server/security.py` and is built on [AWS Cognito](https://aws.amazon.com/cognito/) via [`fastapi-cognito`](https://pypi.org/project/fastapi-cognito/).

## Summary

- `current_principal` is the single authentication dependency; `require_shop`, `require_cognito` and `require_admin` are the guards mounted per tier.
- Three credential shapes are accepted: user tokens, M2M client-credentials tokens, and per-shop API keys.
- **Both** the web app client and the MCP app client issue *user* tokens. Only a token from neither is treated as M2M.
- Authentication and shop authorization are separate checks.

## Token model

Three credential shapes are accepted:

1. **User tokens** — standard Cognito-issued ID/access tokens for interactive users. Validated against the configured Cognito user pool and resolved to a `client_id` / subject. A token counts as a user token when its `client_id` is in `user_client_ids()` — that is, either `AWS_COGNITO_CLIENT_ID` (the web app client) or `AWS_COGNITO_MCP_CLIENT_ID` (the MCP app client). User tokens are not scope-gated; they carry `cognito:groups`.
2. **M2M (machine-to-machine) tokens** — Cognito client-credentials tokens, i.e. anything whose `client_id` is *not* a user client id. Must carry the `/api` scope. Used by server-to-server integrations.
3. **API keys** — per-shop bearer tokens issued from `/shops/{shop_id}/api-keys/`. Accepted **only** on routes that opt in (currently the MCP-exposed CRUD surface for products / categories / tags / attributes). See the [MCP server](mcp.md) page for issuance and usage.

The `CustomCognitoToken` model wraps the jose-decoded JWT and exposes the subject, scopes, and groups in a uniform shape.

## Configuration

All auth settings come from environment variables loaded by `server/settings.py`:

| Variable | Purpose |
|----------|---------|
| `AWS_COGNITO_USERPOOL_ID` | User pool the tokens are issued from. |
| `AWS_COGNITO_REGION` | AWS region of the user pool. |
| `AWS_COGNITO_CLIENT_ID` | Expected `aud` for user tokens. |
| `AWS_COGNITO_M2M_CLIENT_ID` | Expected `client_id` for M2M tokens. |
| `AWS_COGNITO_MCP_CLIENT_ID` | `client_id` of the MCP app client. `Principal.from_token` treats tokens from it as **user** tokens, not M2M. |
| `MCP_ENABLED` | Default `false`. Mount the [MCP server](mcp.md) at `/mcp`. |

Cognito itself — user pool, app clients, domain, groups — is managed outside this repo.

## Dependency usage

Routes are guarded by the tier they are mounted on in `server/api/api.py`: `require_cognito` for Cognito-only tiers, `require_shop` for shop-scoped tiers, `require_admin` for the admin tier. A handler only declares the caller when it needs it, and then receives a `Principal`, never the raw token:

```python
from fastapi import Depends
from server.security import Principal, current_principal

@router.get("/protected")
def protected_route(principal: Principal = Depends(current_principal)):
    ...  # principal.kind is "user", "m2m" or "api_key"; principal.subject is the sub or key id
```

`current_principal` accepts user tokens, M2M tokens with the `/api` scope, and API keys. For M2M-only behaviour, the handler can check `principal.kind == "m2m"` inside the body.

Endpoints that require membership of the Cognito `admins` group (or the legacy `Admins` casing) go on the `admin` tier, which mounts `require_cognito` and `require_admin`:

```python
from server.security import require_admin, require_cognito

admin = APIRouter(dependencies=[Depends(require_cognito), Depends(require_admin)])
```

Endpoints that should also accept API keys (the MCP-exposed shop CRUD routes) go on a tier that mounts `require_shop` without `require_cognito`. `current_principal` resolves `X-API-Key` or `Authorization: Bearer sv_…` first, then falls back to Cognito; `principal.shop_id` is set for keys.

## Shop access

Authentication proves *who* is calling. Which shops they can touch is determined by their **Cognito group membership**:

- Members of the `admins` group, or the legacy `Admins` group, can access every shop.
- All other users can only access shops whose UUID matches one of their Cognito group names. A user is given access to a shop by adding them to a Cognito group named after that shop's UUID.

`GET /shops/my-shops` (also exposed as the `list_my_shops` MCP tool) returns the list of accessible shops and a `can_write` flag. MCP agents are expected to call this first. The individual shop-scoped endpoints do not re-enforce this check on every request — they rely on the caller having already resolved their shop access via `my-shops`.

## Troubleshooting

- **401 on every Cognito-protected route:** verify `AWS_COGNITO_USERPOOL_ID`, region, and client IDs in the environment. Placeholder defaults in `server/settings.py` will not work against real tokens.
- **403 on an admin route:** the user authenticated successfully but is not a member of the Cognito `admins` or legacy `Admins` group.
