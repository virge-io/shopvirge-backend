# Copyright 2026 René Dohmen <acidjunk@gmail.com>
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
"""Authentication for the MCP server, built on fastmcp's own auth hooks.

:class:`PrincipalVerifier` is a fastmcp ``TokenVerifier``: fastmcp calls it with
the bearer token of every MCP request (``initialize`` and ``tools/list``
included) and refuses the request with 401 when it returns ``None``. It runs
:func:`server.security.authenticate`, so the MCP surface accepts exactly the
credentials the REST API accepts — an ``sv_`` API key or a Cognito token — with
exactly the same checks.

The verified :class:`~server.security.Principal` travels in the access token's
claims. :func:`server.security.current_principal` reads it back from there when
a tool call reaches a route, so routes no longer depend on fastmcp forwarding
the ``Authorization`` header into its in-process request.

The token's ``scopes`` say what the caller may do through MCP: ``read`` for
everyone, ``write`` unless the principal is in the read-only group. Write tools
carry ``require_scopes("write")`` (see ``server/mcp/server.py``), and fastmcp
itself then hides them from and refuses them for a read-only caller.
"""

from fastapi import HTTPException
from fastmcp.server.auth import AccessToken, TokenVerifier
from starlette.requests import HTTPConnection

from server.security import authenticate


def _connection_with_bearer(token: str) -> HTTPConnection:
    """A minimal ASGI connection carrying only the bearer, for the Cognito verifier."""
    return HTTPConnection({"type": "http", "headers": [(b"authorization", f"Bearer {token}".encode())]})


class PrincipalVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            principal = await authenticate(_connection_with_bearer(token), via="mcp")
        except HTTPException:
            return None
        scopes = ["read"] if principal.is_readonly else ["read", "write"]
        return AccessToken(token=token, client_id=principal.subject, scopes=scopes, claims=principal.claims())
