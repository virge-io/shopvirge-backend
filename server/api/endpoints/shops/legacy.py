# Copyright 2026 René Dohmen <acidjunk@gmail.com>
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
"""Deprecated ``{id}`` aliases of the shop routes that were renamed to ``{shop_id}``.

The URLs never changed — ``/shops/config/<uuid>`` is the same request either
way — so this is about the OpenAPI spec: clients generated from the previous
spec use the old path templates and operation ids
(``get_config_shops_config__id__get``). Each alias is built *from* its
replacement route, so summary, response model and status code cannot drift, and
it delegates to the same handler. The replacements are registered first and
serve the requests; the aliases exist for the spec and are marked deprecated.

TODO(deprecated-id-routes): delete this module together with
``require_shop_by_id`` in ``server/security.py``, the ``legacy`` includes in
``shops/router.py`` and ``api.py``, and the ``deprecated`` exemptions in
``test_router_posture.py`` / ``test_access_matrix.py`` once clients have moved
to the ``{shop_id}`` operations.
"""

import functools
import inspect
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter
from fastapi.routing import APIRoute

from server.api.endpoints.shops import allowed_ips, config, public


def _with_id(endpoint: Callable[..., Any]) -> Callable[..., Any]:
    """The same handler, presented to FastAPI with its ``shop_id`` parameter named ``id``."""
    signature = inspect.signature(endpoint)

    @functools.wraps(endpoint)
    def call(**kwargs: Any) -> Any:
        kwargs["shop_id"] = kwargs.pop("id")
        return endpoint(**kwargs)

    call.__signature__ = signature.replace(  # type: ignore[attr-defined]
        parameters=[p.replace(name="id") if p.name == "shop_id" else p for p in signature.parameters.values()]
    )
    return call


def _mirror(source: APIRouter) -> APIRouter:
    router = APIRouter()
    for route in source.routes:
        if isinstance(route, APIRoute) and "{shop_id}" in route.path:
            router.add_api_route(
                route.path.replace("{shop_id}", "{id}"),
                _with_id(route.endpoint),
                methods=sorted(route.methods),
                response_model=route.response_model,
                status_code=route.status_code,
                summary=route.summary,
                description=route.description,
                name=route.name,
                deprecated=True,
            )
    return router


# GET /shops/{id}, /shops/config/{id}, /shops/cache-status/{id}, /shops/last-*-order/{id}
public_router = _mirror(public.router)

# PUT /shops/config/{id}; GET, POST /shops/allowed-ips/{id}; POST /shops/allowed-ips/{id}/remove
router = APIRouter()
router.include_router(_mirror(config.router))
router.include_router(_mirror(allowed_ips.router))
