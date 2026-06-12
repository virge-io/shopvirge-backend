# Copyright 2026 René Dohmen <acidjunk@gmail.com>
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
"""OAuth discovery endpoints + Cognito-compatible DCR shim for the MCP server.

Claude Code's MCP SDK follows the MCP 2025-06-18 / RFC 9728 / RFC 8414 /
RFC 7591 chain to bootstrap auth against an HTTP MCP server:

1. ``GET  /.well-known/oauth-protected-resource``     -> RFC 9728 metadata
2. ``GET  /.well-known/oauth-authorization-server``   -> RFC 8414 metadata
3. ``POST <registration_endpoint>``                   -> RFC 7591 DCR
4. PKCE authorization-code flow against ``authorization_endpoint`` +
   ``token_endpoint``

Cognito provides 1 & 4 out of the box (via the user pool's OIDC discovery
doc and Hosted UI), but it does NOT support RFC 7591 DCR — and Claude Code
attempts DCR unconditionally even when configured with a static client_id
(see anthropics/claude-code#26675). This module bridges that gap:

* Mounts the two well-known docs at our backend's root with values
  stitched from Cognito's OIDC discovery + the pre-registered MCP
  app-client id (``AWS_COGNITO_MCP_CLIENT_ID``).
* Mounts ``/oauth/register`` as a DCR shim — ignores the request body
  and returns the static MCP client_id, so Claude Code thinks it
  registered and proceeds straight to PKCE.

The discovery doc's ``issuer`` field intentionally matches Cognito's
issuer (``https://cognito-idp.<region>.amazonaws.com/<userpool-id>``),
not our backend URL. This violates RFC 8414 §3.3 strictly (the issuer
should equal the URL where the doc is served), but MCP clients prioritize
token-``iss`` matching during validation, and Cognito-issued tokens carry
the Cognito issuer. Without this mismatch, tokens fail client-side
validation.
"""

import time
from typing import Any

from fastapi import APIRouter, Body, Request, status
from fastapi.responses import JSONResponse

from server.settings import app_settings

router = APIRouter()

# Default scopes the shim hands back in the DCR response. The user pool's
# Hosted UI must allow these; see ``aws cognito-idp create-user-pool-client
# --allowed-o-auth-scopes`` in the setup docs.
_DEFAULT_SCOPES = ("openid", "email", "profile")


def _cognito_issuer() -> str:
    return (
        f"https://cognito-idp.{app_settings.AWS_COGNITO_REGION}.amazonaws.com/"
        f"{app_settings.AWS_COGNITO_USERPOOL_ID}"
    )


def _hosted_ui_base() -> str:
    # The Hosted UI domain is configurable per user pool and cannot be
    # derived from the userpool id alone. We pull it from Cognito's OIDC
    # discovery doc once at import time so the values stay in lockstep
    # with whatever the user pool actually advertises.
    return _HOSTED_UI_BASE


def _fetch_hosted_ui_base() -> str:
    """Resolve the Hosted UI base URL from Cognito's OIDC discovery doc.

    Pulled once at import time. If the lookup fails (offline tests, no
    DNS) we fall back to a placeholder — the well-known endpoints will
    still serve, but the URLs they advertise won't work for a real
    browser login. Production deployments always have outbound network.
    """
    import json
    import urllib.request

    url = f"{_cognito_issuer()}/.well-known/openid-configuration"
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            doc = json.loads(resp.read())
        return doc["authorization_endpoint"].rsplit("/oauth2/", 1)[0]
    except Exception:
        return "https://example.invalid"


_HOSTED_UI_BASE = _fetch_hosted_ui_base()


@router.get(
    "/.well-known/oauth-protected-resource",
    include_in_schema=False,
)
def oauth_protected_resource(request: Request) -> dict[str, Any]:
    """RFC 9728 — tell MCP clients where to find the authorization server.

    The ``resource`` MUST equal the URL the client used to reach this server
    (RFC 9728 §3.3).  We derive it from the incoming request so the value is
    correct whether the client hits us as localhost:8080 or
    host.docker.internal:8080 or any other alias.
    """
    base = f"{request.url.scheme}://{request.url.netloc}"
    return {
        "resource": f"{base}/mcp/",
        "authorization_servers": [base],
        "bearer_methods_supported": ["header"],
        "scopes_supported": list(_DEFAULT_SCOPES),
    }


@router.get(
    "/.well-known/oauth-authorization-server",
    include_in_schema=False,
)
def oauth_authorization_server(request: Request) -> dict[str, Any]:
    """RFC 8414 — Cognito's OIDC doc, plus our DCR shim's registration endpoint.

    ``issuer`` deliberately matches Cognito's issuer (not our backend host)
    so token-``iss`` validation succeeds client-side. See module docstring.
    """
    hosted = _hosted_ui_base()
    base = f"{request.url.scheme}://{request.url.netloc}"
    return {
        "issuer": _cognito_issuer(),
        "authorization_endpoint": f"{hosted}/oauth2/authorize",
        "token_endpoint": f"{hosted}/oauth2/token",
        "jwks_uri": f"{_cognito_issuer()}/.well-known/jwks.json",
        "registration_endpoint": f"{base}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": list(_DEFAULT_SCOPES),
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "revocation_endpoint": f"{hosted}/oauth2/revoke",
        "userinfo_endpoint": f"{hosted}/oauth2/userInfo",
    }


@router.post(
    "/oauth/register",
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
def oauth_register_shim(body: dict[str, Any] = Body(default_factory=dict)) -> JSONResponse:
    """RFC 7591 DCR shim — always returns the pre-registered MCP client_id.

    Cognito doesn't support DCR. Claude Code's MCP SDK attempts it
    unconditionally; we return a fixed registration response so the SDK
    proceeds to PKCE with our static client.

    The request body is ignored beyond echoing back the client's
    ``redirect_uris`` (so the SDK sees what it expects). The real
    redirect-URI allowlist is enforced by Cognito at the
    ``authorization_endpoint`` step.
    """
    redirect_uris = body.get("redirect_uris") or ["http://localhost:7777/callback"]
    response = {
        "client_id": app_settings.AWS_COGNITO_MCP_CLIENT_ID,
        "client_id_issued_at": int(time.time()),
        "client_name": body.get("client_name", "shopvirge-mcp"),
        "redirect_uris": redirect_uris,
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": " ".join(_DEFAULT_SCOPES),
    }
    return JSONResponse(content=response, status_code=status.HTTP_201_CREATED)
