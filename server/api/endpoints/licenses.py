from datetime import datetime
from http import HTTPStatus
from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter
from fastapi.param_functions import Body, Depends
from starlette.responses import Response

from server.api import deps
from server.api.deps import common_parameters
from server.api.error_handling import raise_status
from server.crud.crud_license import license_crud
from server.db.models import UserTable
from server.schemas.license import LicenseCreate, LicenseSchema, LicenseUpdate

router = APIRouter()


@router.get(
    "",
    response_model=List[LicenseSchema],
    summary="List licenses",
    description="Returns all licenses. Requires superuser privileges.",
)
def get_multi(
    response: Response,
    common: dict = Depends(common_parameters),
    current_user: UserTable = Depends(deps.get_current_active_superuser),
) -> List[LicenseSchema]:
    licenses, header_range = license_crud.get_multi(
        skip=common["skip"], limit=common["limit"], filter_parameters=common["filter"], sort_parameters=common["sort"]
    )
    response.headers["Content-Range"] = header_range
    return licenses


@router.get(
    "/{id}",
    response_model=LicenseSchema,
    summary="Get license",
    description="Retrieve a single license by its UUID. Requires superuser privileges.",
)
def get_by_id(id: UUID, current_user: UserTable = Depends(deps.get_current_active_superuser)) -> LicenseSchema:
    license = license_crud.get(id)
    if not license:
        raise_status(HTTPStatus.NOT_FOUND, f"License with id {id} not found")
    return license


@router.get(
    "/improviser/{improviser_user_id}",
    response_model=LicenseSchema,
    summary="Get license by improviser user ID",
    description="Retrieve the license associated with an external improviser user ID.",
)
def get_by_improviser_user_id(improviser_user_id: str) -> LicenseSchema:
    license = license_crud.get_by_improviser_user_id(improviser_user_id=improviser_user_id)

    if not license:
        raise_status(HTTPStatus.NOT_FOUND, f"License not found")
    return license


@router.post(
    "",
    response_model=LicenseSchema,
    status_code=HTTPStatus.CREATED,
    summary="Create license",
    description="Create a new license. Recurring licenses must not have an `end_date`. Requires superuser privileges.",
)
def create(data: LicenseCreate, current_user: UserTable = Depends(deps.get_current_active_superuser)) -> None:
    if data.is_recurring and data.end_date is not None:
        raise_status(HTTPStatus.UNPROCESSABLE_ENTITY, f"Recurring licenses cannot have an end_date")

    license = license_crud.create(obj_in=data)
    return license


@router.put(
    "/{id}",
    response_model=LicenseSchema,
    status_code=HTTPStatus.OK,
    summary="Update license",
    description="Update an existing license. Recurring licenses may not be given an `end_date`. Requires superuser privileges.",
)
def edit(id: UUID, data: LicenseUpdate, current_user: UserTable = Depends(deps.get_current_active_superuser)) -> Any:
    license = license_crud.get(id)
    if not license:
        raise_status(HTTPStatus.NOT_FOUND, f"License with id {id} not found")
    if license.is_recurring and data.end_date is not None:
        raise_status(HTTPStatus.UNPROCESSABLE_ENTITY, f"Recurring licenses cannot have an end_date")
    license = license_crud.update(db_obj=license, obj_in=data)
    return license


@router.delete(
    "/{id}",
    response_model=None,
    status_code=HTTPStatus.NO_CONTENT,
    summary="Delete license",
    description="Permanently remove a license. Requires superuser privileges.",
)
def delete(id: UUID, current_user: UserTable = Depends(deps.get_current_active_superuser)) -> None:
    return license_crud.delete(id=id)
