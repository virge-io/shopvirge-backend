---
title: Authentication & Authorization
description: Cognito token handling and shop access via AWS Cognito.
---

# Authentication

Authentication lives in `server/security.py` and is built on [AWS Cognito](https://aws.amazon.com/cognito/) via [`fastapi-cognito`](https://pypi.org/project/fastapi-cognito/).

## Summary

- `auth_required` is the main dependency for Cognito-backed API access.
- Two token shapes are accepted: user tokens and M2M client-credentials tokens.
- Authentication and shop authorization are separate checks.

## Token model

Three credential shapes are accepted:

1. **User tokens** — standard Cognito-issued ID/access tokens for interactive users. Validated against the configured Cognito user pool and resolved to a `client_id` / subject.
2. **M2M (machine-to-machine) tokens** — Cognito client-credentials tokens. Must carry the `/api` scope. Used by server-to-server integrations.
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
| `AWS_COGNITO_MCP_CLIENT_ID` | Expected `client_id` for MCP server tokens (accepted alongside M2M tokens when `MCP_ENABLED` is true). |
| `MCP_ENABLED` | Default `false`. Mount the [MCP server](mcp.md) at `/mcp`. |

Cognito itself — user pool, app clients, domain, groups — is managed outside this repo.

## Dependency usage

Protect an endpoint with the `auth_required()` dependency:

```python
from fastapi import Depends
from server.security import auth_required

@router.get("/protected")
def protected_route(token = Depends(auth_required)):
    ...
```

`auth_required` accepts both user and M2M tokens. For M2M-only endpoints, the handler can assert on `token.scope` inside the body.

For endpoints that require membership of the Cognito `Admins` group, use `admin_required` instead:

```python
from server.security import admin_required

@router.get("/admin-only")
def admin_route(_ = Depends(admin_required)):
    ...
```

For endpoints that should also accept API keys (currently the MCP-exposed shop CRUD routes), use `auth_required_any` instead:

```python
from server.security import auth_required_any

@router.get("/protected")
def protected_route(principal = Depends(auth_required_any)):
    # principal is either a CustomCognitoToken or an ApiKeyTable row.
    ...
```

`auth_required_any` resolves `X-API-Key` or `Authorization: Bearer sv_…` first, then falls back to Cognito.

## Shop access checks

Authentication proves *who* is calling; authorisation proves *what shop* they can touch. Shop-scoped handlers resolve the caller's `UserTable` row and check `ShopUserTable` for a link to the `shop_id` path parameter. M2M tokens with `/api` scope bypass the per-shop check (they're trusted server credentials).

## Troubleshooting

- **401 on every Cognito-protected route:** verify `AWS_COGNITO_USERPOOL_ID`, region, and client IDs in the environment. Placeholder defaults in `server/settings.py` will not work against real tokens.
- **403 on an admin route:** the user authenticated successfully but is not a member of the Cognito `Admins` group.
