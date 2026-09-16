# Copyright 2026 René Dohmen <acidjunk@gmail.com>
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
"""The access matrix: who may call which route, derived from the route table.

One row per route, one column per caller kind. Every cell is a pure function of
three facts the route carries — the guards in its dependency chain, its HTTP
method and whether it is exposed as an MCP tool — combined with the fixed
semantics of the guards in ``server/security.py``. Nothing is hand-written, so
a change in how a route is mounted shows up as a diff in the page.

``docs/api/access-matrix.md`` is the committed rendering; this module is the
drift guard, and ``bin/generate_access_matrix.py`` regenerates the page.
"""

from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI
from fastapi.routing import APIRoute

from server.agent_tags import AgentTag
from server.api.api import api_router
from server.security import require_admin, require_cognito, require_shop

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_PATH = REPO_ROOT / "docs" / "api" / "access-matrix.md"

CALLERS = ("Public", "API key", "Member", "Admin", "MCP viewer", "MCP operator")
METHOD_ORDER = {"GET": 0, "POST": 1, "PUT": 2, "PATCH": 3, "DELETE": 4}

# Postures, in the order the page shows them. The unscoped tier comes first on
# purpose: those routes accept any authenticated user and do not bind to a shop.
POSTURES = (
    (
        "Authenticated, not shop-scoped",
        "Any signed-in user, not bound to a shop. Apart from per-user routes such as `my-shops`, these still need a shop in their path or an admin guard.",
    ),
    (
        "Per shop — API key or Cognito",
        "The MCP surface: a key reaches its own shop, a member their shops, an admin any.",
    ),
    ("Per shop — Cognito only", "As above, but API keys are refused (key management, accounts, uploads)."),
    ("Admin", "Cross-shop management; the `admins` group or a service token."),
    ("Public", "No credential; storefront, checkout and discovery."),
)


@dataclass(frozen=True)
class Route:
    method: str
    path: str
    guards: frozenset[str]  # subset of {"cognito", "shop", "admin"}
    tool: str | None  # MCP tool name when the route is exposed, else None

    @property
    def reads(self) -> bool:
        return self.method == "GET"

    @property
    def posture(self) -> str:
        if "admin" in self.guards:
            return POSTURES[3][0]
        if "shop" in self.guards:
            return POSTURES[2][0] if "cognito" in self.guards else POSTURES[1][0]
        if "cognito" in self.guards:
            return POSTURES[0][0]
        return POSTURES[4][0]

    def access(self, caller: str) -> str:
        """The cell: ``R``/``W`` with ``own``/``any`` scope, ``–`` for no access, ``·`` for not an MCP tool."""
        verb = "R" if self.reads else "W"
        scoped = "shop" in self.guards
        if caller.startswith("MCP"):
            if self.tool is None:
                return "·"
            if "admin" in self.guards or (caller == "MCP viewer" and not self.reads):
                return "–"
            return f"{verb} own" if scoped else verb
        if caller == "Public":
            return verb if not self.guards else "–"
        if caller == "API key":
            if "cognito" in self.guards or "admin" in self.guards:
                return "–"
            return f"{verb} own" if scoped else verb
        if caller == "Member":
            if "admin" in self.guards:
                return "–"
            return f"{verb} own" if scoped else verb
        return f"{verb} any" if scoped else verb  # Admin


def _guards(dependant) -> frozenset[str]:
    found, stack = set(), [dependant]
    while stack:
        for sub in stack.pop().dependencies:
            if sub.call is require_cognito:
                found.add("cognito")
            elif sub.call is require_shop:
                found.add("shop")
            elif sub.call is require_admin:
                found.add("admin")
            stack.append(sub)
    return frozenset(found)


def routes() -> list[Route]:
    """Every route in the API, minus the dev-only mail-test route, so the page is independent of ``.env``."""
    app = FastAPI()
    app.include_router(api_router)
    found = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or route.path.startswith("/mail-test"):
            continue
        exposed = AgentTag.EXPOSED.value in [str(getattr(t, "value", t)) for t in route.tags]
        for method in route.methods - {"HEAD", "OPTIONS"}:
            found.append(Route(method, route.path, _guards(route.dependant), route.operation_id if exposed else None))
    return sorted(found, key=lambda r: (r.path, METHOD_ORDER.get(r.method, 9)))


def render(found: list[Route] | None = None) -> str:
    found = routes() if found is None else found
    out = [
        "---",
        "title: Access matrix",
        "description: Who may call which route, derived from the route table.",
        "---",
        "",
        "# Access matrix",
        "",
        "Generated from the route table by `bin/generate_access_matrix.py`; a test fails when this page is stale.",
        "One row per route: the REST columns and the MCP columns describe the same route, reached two ways.",
        "",
        "| Cell | Meaning |",
        "|---|---|",
        "| `R` / `W` | the route reads / writes (its HTTP method) and this caller may call it |",
        "| `own` / `any` | shop-scoped: only the caller's own shop(s) / every shop |",
        "| `–` | no access |",
        "| `·` | not an MCP tool |",
        "",
        "| Caller | Who |",
        "|---|---|",
        "| Public | no credential |",
        "| API key | a per-shop `sv_` key; bound to the shop it was minted for |",
        "| Member | a signed-in user attached to a shop (Cognito group = shop id) |",
        "| Admin | the `admins` group, or a service (M2M) token |",
        "| MCP viewer / operator | a member calling through the MCP server with that role: viewers read, operators read and write. Without a role a user may do nothing through MCP, admins included |",
        "",
    ]
    for title, blurb in POSTURES:
        rows = [r for r in found if r.posture == title]
        if not rows:
            continue
        out += [
            f"## {title}",
            "",
            blurb,
            "",
            "| Method | Path | MCP tool | " + " | ".join(CALLERS) + " |",
            "|---|---|---|" + "---|" * len(CALLERS),
        ]
        for r in rows:
            cells = " | ".join(r.access(c) for c in CALLERS)
            out.append(f"| {r.method} | `{r.path}` | {r.tool or ''} | {cells} |")
        out.append("")
    return "\n".join(out)


def test_access_matrix_page_is_in_sync():
    assert DOC_PATH.read_text() == render(), (
        "docs/api/access-matrix.md is stale: uv run python bin/generate_access_matrix.py"
    )


def test_every_route_has_a_posture():
    assert {r.posture for r in routes()} <= {title for title, _ in POSTURES}
