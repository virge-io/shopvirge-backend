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
from typing import List, Optional

from fastapi import Header, HTTPException, Request
from fastapi.param_functions import Depends
from fastapi_cognito import CognitoAuth, CognitoSettings, CognitoToken
from pydantic import BaseModel, Field, HttpUrl
from structlog import get_logger

from server.settings import app_settings, auth_settings

logger = get_logger(__name__)

ADMIN_GROUP = "Admins"


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


def auth_required(token: CognitoToken = Depends(cognito_eu.auth_required)):
    user_client_ids = {
        app_settings.AWS_COGNITO_CLIENT_ID,
        app_settings.AWS_COGNITO_MCP_CLIENT_ID,
    } - {""}
    if token.client_id in user_client_ids:
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
    :class:`CustomCognitoToken` on Cognito auth. Endpoints downstream of this
    dep don't typically inspect the return value (shop ownership comes from
    the path param), so the union is intentional.
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


def admin_required(token: CognitoToken = Depends(auth_required)):
    # M2M tokens (already validated by auth_required) are trusted as admin.
    if token.client_id != app_settings.AWS_COGNITO_CLIENT_ID:
        return token

    if ADMIN_GROUP in getattr(token, "cognito_groups", []):
        return token

    raise HTTPException(status_code=403, detail=f"User is not a member of the '{ADMIN_GROUP}' group")
