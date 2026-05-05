from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic.networks import EmailStr
from starlette.responses import Response

from server.api import deps
from server.api.deps import common_parameters
from server.crud.crud_user import user_crud
from server.db.models import UserTable
from server.schemas import User, UserCreate, UserUpdate
from server.settings import app_settings
from server.utils.auth import send_new_account_email

router = APIRouter()


@router.get(
    "/",
    summary="List users",
    description="Retrieve all users. Requires superuser privileges. Supports pagination, filtering, and sorting.",
)
def get_multi(
    response: Response,
    common: dict = Depends(common_parameters),
    current_user: UserTable = Depends(deps.get_current_active_superuser),
) -> Any:
    users, header_range = user_crud.get_multi(
        skip=common["skip"],
        limit=common["limit"],
        filter_parameters=common["filter"],
        sort_parameters=common["sort"],
    )
    response.headers["Content-Range"] = header_range
    return users


@router.post(
    "/",
    response_model=User,
    summary="Create user",
    description="Create a new user account. Returns 400 if a user with the same email already exists. Sends a welcome email when SMTP is configured.",
)
def create(
    *,
    user_in: UserCreate,
    current_user: UserTable = Depends(deps.get_current_active_superuser),
) -> Any:
    user = user_crud.get_by_email(email=user_in.email)
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this username already exists in the system.",
        )
    user = user_crud.create(obj_in=user_in)
    if app_settings.EMAILS_ENABLED and user_in.email:
        send_new_account_email(email_to=user_in.email, username=user_in.email, password=user_in.password)
    return user


@router.put(
    "/me",
    response_model=User,
    summary="Update current user",
    description="Update the currently authenticated user's own password, full name, or email address.",
)
def update_user_me(
    *,
    password: str = Body(None),
    full_name: str = Body(None),
    email: EmailStr = Body(None),
    current_user: UserTable = Depends(deps.get_current_active_user),
) -> Any:
    current_user_data = jsonable_encoder(current_user)
    user_in = UserUpdate(**current_user_data)
    if password is not None:
        user_in.password = password
    if full_name is not None:
        user_in.full_name = full_name
    if email is not None:
        user_in.email = email
    user = user_crud.update(db_obj=current_user, obj_in=user_in)
    return user


# @router.get("/me", response_model=UserTable)
@router.get(
    "/me",
    response_model=User,
    summary="Get current user",
    description="Returns the profile of the currently authenticated user.",
)
def get_user_me(
    current_user: UserTable = Depends(deps.get_current_active_user),
) -> Any:
    return current_user


# TODO remove me?
# @router.post("/open", response_model=schemas.User)
# def create_user_open(
#     *,
#     db: Session = Depends(deps.get_db),
#     password: str = Body(...),
#     email: EmailStr = Body(...),
#     full_name: str = Body(None),
# ) -> Any:
#     """
#     Create new user without the need to be logged in.
#     """
#     if not settings.USERS_OPEN_REGISTRATION:
#         raise HTTPException(
#             status_code=403,
#             detail="Open user registration is forbidden on this server",
#         )
#     user = crud.user.get_by_email(db, email=email)
#     if user:
#         raise HTTPException(
#             status_code=400,
#             detail="The user with this username already exists in the system",
#         )
#     user_in = schemas.UserCreate(password=password, email=email, full_name=full_name)
#     user = crud.user.create(db, obj_in=user_in)
#     return user


@router.get(
    "/{user_id}",
    response_model=User,
    summary="Get user",
    description="Retrieve a specific user by their integer ID. Regular users can only retrieve their own record; superusers can retrieve any user.",
)
def get_by_id(
    user_id: int,
    current_user: UserTable = Depends(deps.get_current_active_user),
) -> Any:
    user = user_crud.get(id=user_id)
    if user == current_user:
        return user
    if not user_crud.is_superuser(current_user):
        raise HTTPException(status_code=400, detail="The user doesn't have enough privileges")
    return user


@router.put(
    "/{user_id}",
    response_model=User,
    summary="Update user",
    description="Update a user by their integer ID. Requires superuser privileges.",
)
def update(
    *,
    user_id: int,
    user_in: UserUpdate,
    current_user: UserTable = Depends(deps.get_current_active_superuser),
) -> Any:
    user = user_crud.get(id=user_id)
    if not user:
        raise HTTPException(
            status_code=404,
            detail="The user with this username does not exist in the system",
        )
    user = user_crud.update(db_obj=user, obj_in=user_in)
    return user
