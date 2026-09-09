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
from typing import Any, Iterable, List, Optional
from uuid import UUID

from fastapi import Header, HTTPException, Request, Security
from fastapi.param_functions import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi_cognito import CognitoAuth, CognitoSettings, CognitoToken
from pydantic import BaseModel, Field, HttpUrl
from structlog import get_logger

from server.settings import app_settings, auth_settings

logger = get_logger(__name__)

ADMIN_GROUPS = ("Admins", "admins")


def has_admin_group(groups: Iterable[str]) -> bool:
    return any(group in ADMIN_GROUPS for group in groups)


class CustomCognitoToken(BaseModel):
    origin_jti: Optional[str] = None
    cognito_id: str = Field(alias="sub")
    event_id: Optional[str] = None
    token_use: str
    scope: str
    auth_time: int
    iss: HttpUrl
    exp: int
    iat: int
    jti: str
    client_id: str
    username: str | None = None
    cognito_groups: List[str] = Field(default_factory=list, alias="cognito:groups")

    model_config = {"populate_by_name": True}


cognito_eu = CognitoAuth(settings=CognitoSettings.from_global_settings(auth_settings), custom_model=CustomCognitoToken)

_bearer_scheme = HTTPBearer(auto_error=False)


def user_client_ids() -> set:
    """Client ids that issue *user* tokens (as opposed to M2M service tokens).

    The MCP browser-login flow has its own app client, so a token from it is
    still a person and must be scoped like one.
    """
    return {
        app_settings.AWS_COGNITO_CLIENT_ID,
        app_settings.AWS_COGNITO_MCP_CLIENT_ID,
    } - {""}


def auth_required(
    token: CognitoToken = Depends(cognito_eu.auth_required),
    _: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
):
    if token.client_id in user_client_ids():
        # No need to check scopes for user tokens
        return token

    # M2M tokens: check required scope
    if token.scope.endswith("/api"):
        return token

    raise HTTPException(status_code=401, detail="Invalid OAuth2 scope")


async def auth_required_any(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    """Accept either a Cognito JWT or a per-shop API key.

    Resolution order:
        1. ``X-API-Key`` header, if present.
        2. ``Authorization: Bearer <token>`` where ``<token>`` starts with the
           API-key prefix (``sv_``).
        3. Otherwise fall back to the standard Cognito flow.

    Returns an :class:`server.db.models.ApiKeyTable` row on API-key auth, or a
    :class:`CustomCognitoToken` on Cognito auth.

    .. warning::
       This dep authenticates but does **not** authorize: it never compares the
       key's shop to the ``shop_id`` in the path. Prefer
       :func:`auth_required_any_for_shop` on any shop-scoped route.
    """
    # Lazy import — avoids a CRUD<->security cycle.
    from server.crud.crud_api_key import KEY_PLAINTEXT_PREFIX, api_key_crud

    plaintext: Optional[str] = x_api_key
    if plaintext is None:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            candidate = auth_header[7:].strip()
            if candidate.startswith(f"{KEY_PLAINTEXT_PREFIX}_"):
                plaintext = candidate

    if plaintext is not None and plaintext.startswith(f"{KEY_PLAINTEXT_PREFIX}_"):
        row = api_key_crud.lookup_by_plaintext(plaintext)
        if row is None:
            raise HTTPException(status_code=401, detail="Invalid API key")
        return row

    # No API key supplied — defer to Cognito.
    token = await cognito_eu.auth_required(request)
    return auth_required(token)


def assert_shop_access(principal: Any, shop_id: UUID) -> Any:
    """Assert ``principal`` may act on ``shop_id``, or raise 403.

    One rule, both principal types:

    * **API key** — minted for exactly one shop, so it may only touch that shop.
    * **Cognito user** — may touch shops whose UUID is one of their groups, or
      any shop if they're in an admin group. This is the same mapping
      ``GET /shops/my-shops`` reports; here it is enforced rather than advised.

    M2M tokens carry no ``cognito:groups`` and are trusted across shops, matching
    how :func:`admin_required` already treats them. Tokens from the MCP app client
    are *users*, not M2M, so they are scoped like any other user — see
    :func:`user_client_ids`.
    """
    # Lazy import — avoids a models<->security import cycle.
    from server.db.models import ApiKeyTable

    if isinstance(principal, ApiKeyTable):
        if principal.shop_id != shop_id:
            raise HTTPException(status_code=403, detail="API key is not valid for this shop")
        return principal

    if getattr(principal, "client_id", None) not in user_client_ids():
        return principal

    groups = getattr(principal, "cognito_groups", [])
    if has_admin_group(groups) or str(shop_id) in groups:
        return principal

    raise HTTPException(status_code=403, detail="User has no access to this shop")


async def auth_required_any_for_shop(shop_id: UUID, principal: Any = Depends(auth_required_any)) -> Any:
    """Like :func:`auth_required_any`, but scopes the principal to the shop in the path.

    A per-shop ``sv_`` key is minted for exactly one shop, and a Cognito user is
    attached to shops via group membership — yet nothing else ties either to the
    ``shop_id`` path param, so without this check swapping the path reaches
    another tenant's data. See :func:`assert_shop_access` for the rule.

    Use this — not ``auth_required_any`` — on every route that reads or writes
    shop-scoped data. It works both as a router-level dependency (the ``shop_id``
    comes from the ``/shops/{shop_id}/...`` prefix) and as a per-route dependency
    for routers where ``shop_id`` sits in the route path instead (e.g. orders).
    """
    return assert_shop_access(principal, shop_id)


def shop_access_required(shop_id: UUID, token: CustomCognitoToken = Depends(auth_required)) -> Any:
    """Cognito-only counterpart of :func:`auth_required_any_for_shop`.

    For routes that must not be reachable with an API key at all — currently
    api-key management, where a key minting another key would be an escalation.
    """
    return assert_shop_access(token, shop_id)


def shop_access_required_by_id(id: UUID, token: CustomCognitoToken = Depends(auth_required)) -> Any:
    """:func:`shop_access_required` for routes whose shop id path param is ``{id}``.

    ``/shops/config/{id}`` and ``/shops/allowed-ips/{id}`` predate the ``{shop_id}``
    convention. FastAPI matches a dependency's parameter *name* against the path
    template, so those routes need a guard whose parameter is literally ``id`` —
    hence this near-duplicate. Mounted on ``shops.legacy_id_router``, which holds
    exactly those routes.

    Renaming the paths would remove the need for it, but FastAPI derives
    ``operation_id`` from the path template, so ``{id}`` -> ``{shop_id}`` renames the
    generated client symbol (``getConfigShopsConfigIdGet``) *and* its argument key —
    20 call sites across 10 files in shop-editor. That needs its own coordinated change.
    """
    return assert_shop_access(token, id)


# Marks the per-shop guards so tests can assert coverage without hardcoding names.
auth_required_any_for_shop.__shop_guard__ = True  # type: ignore[attr-defined]
shop_access_required.__shop_guard__ = True  # type: ignore[attr-defined]
shop_access_required_by_id.__shop_guard__ = True  # type: ignore[attr-defined]


def admin_required(token: CognitoToken = Depends(auth_required)):
    # M2M tokens (already validated by auth_required) are trusted as admin.
    if token.client_id != app_settings.AWS_COGNITO_CLIENT_ID:
        return token

    if has_admin_group(getattr(token, "cognito_groups", [])):
        return token

    raise HTTPException(status_code=403, detail="User is not a member of the 'Admins' group")
