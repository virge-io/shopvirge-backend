from http import HTTPStatus
from typing import Any, List
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.param_functions import Body, Depends
from starlette.responses import Response

from server.api.deps import common_parameters
from server.crud.crud_faq import faq_crud
from server.db.models import UserTable
from server.schemas.faq import FaqCreate, FaqCreated, FaqSchema, FaqUpdate, FaqUpdated
from server.security import auth_required

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.get(
    "/",
    response_model=List[FaqSchema],
    summary="List FAQ entries",
    description="Returns all FAQ question/answer entries. Supports pagination, filtering, and sorting.",
)
def get_multi(
    response: Response,
    common: dict = Depends(common_parameters),
) -> List[FaqSchema]:
    faqs, header_range = faq_crud.get_multi(
        skip=common["skip"],
        limit=common["limit"],
        filter_parameters=common["filter"],
        sort_parameters=common["sort"],
    )
    response.headers["Content-Range"] = header_range
    return faqs


@router.get(
    "/{id}",
    response_model=FaqSchema,
    summary="Get FAQ entry",
    description="Retrieve a single FAQ entry by its UUID.",
)
def get_by_id(id: UUID) -> FaqSchema:
    faq = faq_crud.get(id)
    if not faq:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=f"FAQ with id {id} not found")
    return faq


@router.post(
    "/",
    response_model=FaqCreated,
    status_code=HTTPStatus.CREATED,
    summary="Create FAQ entry",
    description="Add a new FAQ question and answer. Requires authentication. Returns 409 if a FAQ with the same question already exists.",
)
def create(data: FaqCreate = Body(...), current_user: UserTable = Depends(auth_required)) -> Any:

    logger.info("Creating FAQ entry", data=data)

    existing_faq = faq_crud.get_by_question(question=data.question)
    if existing_faq:
        logger.error("FAQ question already exists", question=data.question)
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail="A FAQ entry with this question already exists.",
        )

    faq = faq_crud.create(obj_in=data)
    return faq


@router.put(
    "/{faq_id}",
    response_model=FaqUpdated,
    status_code=HTTPStatus.CREATED,
    summary="Update FAQ entry",
    description="Update an existing FAQ entry's question, answer, or category. Returns 409 if another entry already uses the same question.",
)
def update(*, faq_id: UUID, item_in: FaqUpdate, current_user: UserTable = Depends(auth_required)) -> FaqUpdated:

    faq = faq_crud.get(faq_id)
    if not faq:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="FAQ entry not found")

    duplicate = faq_crud.get_duplicate_question(question=item_in.question, faq_id=faq_id)

    if duplicate:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail="Another FAQ entry with the same question already exists.",
        )

    faq = faq_crud.update(db_obj=faq, obj_in=item_in)

    updated_faq = FaqUpdated(
        id=faq.id,
        question=faq.question,
        answer=faq.answer,
        category=faq.category,
    )

    return updated_faq


@router.delete(
    "/{faq_id}",
    response_model=None,
    status_code=HTTPStatus.NO_CONTENT,
    summary="Delete FAQ entry",
    description="Remove a FAQ entry. Requires authentication.",
)
def delete(faq_id: UUID, current_user: UserTable = Depends(auth_required)) -> None:
    return faq_crud.delete(id=faq_id)
