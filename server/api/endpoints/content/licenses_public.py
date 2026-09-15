from http import HTTPStatus

from fastapi import APIRouter

from server.api.error_handling import raise_status
from server.crud.crud_license import license_crud
from server.schemas.license import LicenseSchema

router = APIRouter()


@router.get(
    "/improviser/{improviser_user_id}",
    response_model=LicenseSchema,
    summary="Get license by improviser user ID",
    description="Retrieve the license associated with an external improviser user ID.",
)
def get_by_improviser_user_id(improviser_user_id: str) -> LicenseSchema:
    license = license_crud.get_by_improviser_user_id(improviser_user_id=improviser_user_id)

    if not license:
        raise_status(HTTPStatus.NOT_FOUND, "License not found")
    return license
