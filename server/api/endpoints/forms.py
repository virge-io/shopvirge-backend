from http import HTTPStatus
from typing import Any, Optional
from uuid import UUID

from fastapi.routing import APIRouter
from pydantic_forms.core import list_forms
from pydantic_forms.core.asynchronous import start_form

import server.forms  # noqa: F401 -- side-effect import; registers all forms

router = APIRouter()


@router.get("", response_model=list[str])
def get_forms() -> list[str]:
    """Retrieve all forms.

    Args:
        response: Response

    Returns:
        Form titles

    """
    return list_forms()


@router.post("/{form_key}", response_model=dict, status_code=HTTPStatus.CREATED)
async def new_form(
    form_key: str,
    json_data: list[dict[str, Any]],
    shop_id: Optional[UUID] = None,
    # user: OIDCUserModel or None = Depends(),  # type: ignore
) -> dict[str, UUID]:
    # Todo: determine what to do with user?
    return start_form(form_key, user_inputs=json_data, user="Just a user", extra_state={"shop_id": shop_id})
