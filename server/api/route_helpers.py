# Copyright 2024 René Dohmen <acidjunk@gmail.com>
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Helpers that replace per-route plumbing in ``server/api/endpoints``.

Two idioms recurred across the endpoint layer: fetch-then-404 (over seventy
sites, in two different exception styles) and paginate-then-set-``Content-Range``
(nineteen copies of the same block). Both collapse to one call here.
"""

from http import HTTPStatus
from typing import Any, List, Optional, TypeVar
from uuid import UUID

from starlette.responses import Response

from server.api.deps import PageParams
from server.api.error_handling import raise_status
from server.crud.base import CRUDBase
from server.db.database import BaseModel

T = TypeVar("T")
ModelT = TypeVar("ModelT", bound=BaseModel)


def get_or_404(obj: Optional[T], detail: str) -> T:
    """Narrow an ``Optional`` lookup result; ``None`` becomes a problem-detail 404.

    Also what makes ``obj.attr`` type-check afterwards: mypy sees the ``NoReturn``
    and drops ``None`` from the type.
    """
    if obj is None:
        raise_status(HTTPStatus.NOT_FOUND, detail)
    return obj


def list_page(
    crud: CRUDBase[ModelT, Any, Any],
    page: PageParams,
    response: Response,
    *,
    shop_id: Optional[UUID] = None,
    query: Any = None,
) -> List[ModelT]:
    """Run a filtered, sorted, paginated list and set ``Content-Range`` on ``response``.

    ``shop_id`` scopes the list to one shop; ``query`` supplies a pre-built base
    query for routes that join or filter beyond what the CRUD does on its own.
    """
    if shop_id is not None:
        items, content_range = crud.get_multi_by_shop_id(
            shop_id=shop_id,
            skip=page.skip,
            limit=page.limit,
            filter_parameters=page.filter,
            sort_parameters=page.sort,
            query_parameter=query,
        )
    else:
        items, content_range = crud.get_multi(
            skip=page.skip,
            limit=page.limit,
            filter_parameters=page.filter,
            sort_parameters=page.sort,
            query_parameter=query,
        )
    response.headers["Content-Range"] = content_range
    return items
