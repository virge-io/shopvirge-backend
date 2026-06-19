from http import HTTPStatus
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.param_functions import Body, Depends
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from server.crud.crud_early_access import early_access_crud
from server.schemas.early_access import EarlyAccessCreate
from server.security import CustomCognitoToken, auth_required

# Set up structured logging with structlog
logger = structlog.get_logger(__name__)

# Create the API router
router = APIRouter()


@router.post("/", response_model=None, status_code=HTTPStatus.CREATED)
def create(data: EarlyAccessCreate = Body(...), current_user: CustomCognitoToken = Depends(auth_required)) -> Any:
    try:
        logger.info("Saving early access", data=data)
        early_access = early_access_crud.create(obj_in=data)
        return early_access

    except ValidationError as ve:
        # Log the validation error
        logger.error("Validation error occurred", error=str(ve), data=data)
        # Raise 422 for incorrect input format
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail="Incorrect input format or missing fields in the request.",
        )

    except IntegrityError as ie:
        # Log the duplicate entry error
        logger.error("Duplicate entry error", error=str(ie), data=data)
        # Raise 409 for duplicate entry (e.g., unique constraint violation)
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail="Duplicate entry. The record already exists.",
        )

    except RequestValidationError as rve:
        # Log the 400 Bad Request error
        logger.error("Bad request error", error=str(rve), data=data)
        # Raise 400 for bad requests (malformed or incomplete data)
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="Malformed request or invalid data.",
        )

    except Exception as e:
        # Log the unexpected error
        logger.error("Unexpected error occurred", error=str(e), data=data)
        # Raise 500 for unexpected errors
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}",
        )
