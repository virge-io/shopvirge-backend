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
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, List, Literal, Optional
from uuid import UUID

from fastapi import Header, HTTPException, Request, Security
from fastapi.param_functions import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi_cognito import CognitoAuth, CognitoSettings
from pydantic import BaseModel, Field, HttpUrl

from server.settings import app_settings, auth_settings

if TYPE_CHECKING:
    from server.db.models import ApiKeyTable

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


def user_client_ids() -> set[str]:
    """Client ids that issue *user* tokens (as opposed to M2M service tokens).

    The MCP browser-login flow has its own app client, so a token from it is
    still a person and must be scoped like one.
    """
    return {
        app_settings.AWS_COGNITO_CLIENT_ID,
        app_settings.AWS_COGNITO_MCP_CLIENT_ID,
    } - {""}


Kind = Literal["user", "m2m", "api_key"]
Via = Literal["rest", "mcp"]


@dataclass(frozen=True)
class Principal:
    """Who is calling, resolved once from whichever credential the request carried.

    ``kind`` is ``"user"`` (Cognito user token), ``"m2m"`` (Cognito service
    token) or ``"api_key"``. ``subject`` is the Cognito ``sub`` or the key's id.
    ``groups`` are the Cognito groups (users only); ``shop_id`` is set for keys.
    """

    kind: Kind
    subject: str
    groups: tuple[str, ...] = ()
    shop_id: Optional[UUID] = None
    via: Via = "rest"
    """``"mcp"`` when the call came through the MCP server, else ``"rest"``."""

    @property
    def label(self) -> Optional[str]:
        """Audit label for revision rows: ``api_key:<id>`` or ``cognito:<sub>``."""
        if self.kind == "api_key":
            return f"api_key:{self.subject}"
        return f"cognito:{self.subject}" if self.subject else None

    @property
    def is_admin(self) -> bool:
        """M2M tokens are trusted across shops; users need an admin group."""
        return self.kind == "m2m" or has_admin_group(self.groups)

    def may_touch(self, shop_id: UUID) -> bool:
        """The one shop-access rule: a key its own shop, a user its groups' shops, an admin any."""
        if self.kind == "api_key":
            return self.shop_id == shop_id
        return self.is_admin or str(shop_id) in self.groups

    @classmethod
    def from_token(cls, token: CustomCognitoToken, via: Via = "rest") -> "Principal":
        """Classify a verified Cognito token; a service token needs the ``/api`` scope."""
        # "user" must cover the whole user-client set: comparing against
        # AWS_COGNITO_CLIENT_ID alone once classified MCP app-client tokens as M2M,
        # which the admin check then trusted without the group check.
        kind: Kind
        if token.client_id in user_client_ids():
            kind = "user"
        elif token.scope.endswith("/api"):
            kind = "m2m"
        else:
            raise HTTPException(status_code=401, detail="Invalid OAuth2 scope")
        return cls(kind=kind, subject=token.cognito_id, groups=tuple(token.cognito_groups), via=via)

    @classmethod
    def from_api_key(cls, row: "ApiKeyTable", via: Via = "rest") -> "Principal":
        """A per-shop API key: may touch its own shop and nothing else."""
        return cls(kind="api_key", subject=str(row.id), shop_id=row.shop_id, via=via)


async def current_principal(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    _: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
) -> Principal:
    """The caller, from whichever credential the request carries.

    1. ``X-API-Key``, or ``Authorization: Bearer sv_…`` — a per-shop API key.
    2. Otherwise ``Authorization: Bearer <jwt>`` — a Cognito user token, or an
       M2M token carrying the ``/api`` scope.

    Authenticates only. Which routes a principal may reach is decided by the
    guards below, mounted per tier in ``server/api/api.py``.
    """
    # Lazy import — avoids a CRUD<->security cycle.
    from server.crud.crud_api_key import KEY_PLAINTEXT_PREFIX, api_key_crud

    # fastmcp forwards the MCP session header into the in-process request it makes.
    via: Via = "mcp" if request.headers.get("mcp-session-id") else "rest"

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
        return Principal.from_api_key(row, via=via)

    token = await cognito_eu.auth_required(request)
    return Principal.from_token(token, via=via)


async def require_shop(shop_id: UUID, principal: Principal = Depends(current_principal)) -> Principal:
    """Shop tiers: the ``shop_id`` in the path must be one the caller may touch, else 403.

    A key is minted for exactly one shop and a user is attached to shops via
    group membership — nothing else ties either to the path, so without this
    check swapping the path reaches another tenant's data. Same mapping
    ``GET /shops/my-shops`` reports; here it is enforced rather than advised.
    """
    if principal.may_touch(shop_id):
        return principal
    if principal.kind == "api_key":
        raise HTTPException(status_code=403, detail="API key is not valid for this shop")
    raise HTTPException(status_code=403, detail="User has no access to this shop")


async def require_cognito(principal: Principal = Depends(current_principal)) -> Principal:
    """Cognito-only tiers: an API key is refused — a key must not mint another key, for instance."""
    if principal.kind == "api_key":
        raise HTTPException(status_code=401, detail="API keys are not accepted on this route")
    return principal


async def require_admin(principal: Principal = Depends(current_principal)) -> Principal:
    """The admin tier — see :meth:`Principal.is_admin`."""
    if principal.is_admin:
        return principal
    raise HTTPException(status_code=403, detail="User is not a member of the 'Admins' group")
