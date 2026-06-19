from http import HTTPStatus
from typing import Any, List
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.param_functions import Body, Depends
from starlette.responses import Response

from server.api.deps import common_parameters
from server.api.error_handling import raise_status
from server.crud.crud_account import account_crud
from server.schemas.account import AccountCreate, AccountSchema, AccountUpdate

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get(
    "/",
    response_model=List[AccountSchema],
    summary="List accounts",
    description="Returns all customer accounts for a shop. Accounts are created automatically when an order is placed with a new customer name.",
)
def get_multi(response: Response, common: dict = Depends(common_parameters)) -> List[AccountSchema]:
    accounts, header_range = account_crud.get_multi(
        skip=common["skip"], limit=common["limit"], filter_parameters=common["filter"], sort_parameters=common["sort"]
    )
    response.headers["Content-Range"] = header_range
    return accounts


@router.get(
    "/{id}",
    response_model=AccountSchema,
    summary="Get account",
    description="Retrieve a single customer account by its UUID.",
)
def get_by_id(id: UUID) -> AccountSchema:
    account = account_crud.get(id)
    if not account:
        raise_status(HTTPStatus.NOT_FOUND, f"Account with id {id} not found")
    return account


@router.post(
    "/",
    response_model=None,
    status_code=HTTPStatus.CREATED,
    summary="Create account",
    description="Manually create a new customer account for a shop.",
)
def create(data: AccountCreate = Body(...)) -> None:
    logger.info("Saving account", data=data)
    account = account_crud.create(obj_in=data)
    return account


@router.put(
    "/{account_id}",
    response_model=None,
    status_code=HTTPStatus.CREATED,
    summary="Update account",
    description="Update an existing customer account's details.",
)
def update(*, account_id: UUID, item_in: AccountUpdate) -> Any:
    account = account_crud.get(id=account_id)
    logger.info("Updating account", data=account)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    account = account_crud.update(
        db_obj=account,
        obj_in=item_in,
    )
    return account


@router.delete(
    "/{account_id}",
    response_model=None,
    status_code=HTTPStatus.NO_CONTENT,
    summary="Delete account",
    description="Remove a customer account from a shop.",
)
def delete(account_id: UUID) -> None:
    return account_crud.delete(id=account_id)
