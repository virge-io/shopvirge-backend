# Copyright 2026 René Dohmen <acidjunk@gmail.com>
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
"""Per-shop API key management.

These endpoints are Cognito-only (``auth_required``) by design — an API key
must not be able to mint another API key. Keys returned from ``POST`` carry
a one-time ``plaintext`` field; subsequent ``GET`` listings expose only the
prefix.
"""

from http import HTTPStatus
from typing import List
from uuid import UUID

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException

from server.crud.crud_api_key import api_key_crud
from server.schemas.api_key import ApiKeyCreate, ApiKeyCreated, ApiKeyRead
from server.security import CustomCognitoToken, auth_required

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.post(
    "/",
    response_model=ApiKeyCreated,
    status_code=HTTPStatus.CREATED,
    summary="Mint a new API key for the shop",
)
def mint(
    shop_id: UUID,
    data: ApiKeyCreate = Body(...),
    token: CustomCognitoToken = Depends(auth_required),
) -> ApiKeyCreated:
    """Mint a new API key. The plaintext is returned exactly once.

    Store it somewhere safe — it cannot be retrieved again. If lost, revoke
    and mint a new one.
    """
    created_by_sub = getattr(token, "cognito_id", None)
    row, plaintext = api_key_crud.mint(shop_id=shop_id, name=data.name, created_by_sub=created_by_sub)
    return ApiKeyCreated(
        id=row.id,
        name=row.name,
        prefix=row.prefix,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        revoked_at=row.revoked_at,
        plaintext=plaintext,
    )


@router.get(
    "/",
    response_model=List[ApiKeyRead],
    summary="List API keys for the shop",
)
def list_keys(
    shop_id: UUID,
    _: CustomCognitoToken = Depends(auth_required),
) -> List[ApiKeyRead]:
    rows = api_key_crud.list_by_shop(shop_id)
    return [ApiKeyRead.model_validate(r) for r in rows]


@router.delete(
    "/{key_id}",
    status_code=HTTPStatus.NO_CONTENT,
    summary="Revoke an API key",
)
def revoke(
    shop_id: UUID,
    key_id: UUID,
    _: CustomCognitoToken = Depends(auth_required),
) -> None:
    row = api_key_crud.revoke(shop_id=shop_id, key_id=key_id)
    if row is None:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="API key not found")
    return None
