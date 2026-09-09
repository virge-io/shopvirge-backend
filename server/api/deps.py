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
"""Pagination / filter / sort query parameters shared by every list endpoint.

Two forms coexist while the endpoint layer is refactored file by file:

* :func:`common_parameters` — the original resource-agnostic dependency. It
  returns a plain dict and its ``filter`` description can't say which keys are
  valid, because that depends on the model.
* :func:`page_params_for` — a factory taking the CRUD, so the generated
  description lists the model's real filterable keys and the dependency returns
  a typed :class:`PageParams`. Use it (with ``route_helpers.list_page``) on any
  route you touch.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Dict, List, Optional, Union

from fastapi.param_functions import Query

if TYPE_CHECKING:
    from server.crud.base import CRUDBase

_FILTER_SYNTAX = (
    "This filter can accept search query's like `key:value` and will split on the `:`. If it "
    "detects more than one `:`, or does not find a `:` it will search for the string in all columns."
)
_SORT_SYNTAX = (
    "The sort will accept parameters like `col:ASC` or `col:DESC` and will split on the `:`. "
    "If it does not find a `:` it will sort ascending on that column."
)


async def common_parameters(
    skip: int = 0,
    limit: int = 100,
    filter: List[str] = Query(None, description=_FILTER_SYNTAX),
    sort: List[str] = Query(None, description=_SORT_SYNTAX),
) -> Dict[str, Union[List[str], int]]:
    """Resource-agnostic form; prefer :func:`page_params_for` on routes being refactored."""
    return {"skip": skip, "limit": limit, "filter": filter, "sort": sort}


@dataclass(frozen=True)
class PageParams:
    skip: int = 0
    limit: int = 100
    filter: Optional[List[str]] = None
    sort: Optional[List[str]] = None


def page_params_for(crud: "CRUDBase[Any, Any, Any]") -> Callable[..., Coroutine[Any, Any, PageParams]]:
    """Build the typed pagination dependency for one resource.

    The inner function keeps the parameter names and descriptions of
    :func:`common_parameters`, so switching a route over leaves the OpenAPI spec
    byte-identical.
    """

    async def page_params(
        skip: int = 0,
        limit: int = 100,
        filter: List[str] = Query(None, description=_FILTER_SYNTAX),
        sort: List[str] = Query(None, description=_SORT_SYNTAX),
    ) -> PageParams:
        return PageParams(skip=skip, limit=limit, filter=filter, sort=sort)

    return page_params
