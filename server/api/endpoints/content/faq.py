from http import HTTPStatus
from uuid import UUID

import structlog
from fastapi import APIRouter
from fastapi.param_functions import Body

from server.api.deps import page_params_for
from server.api.error_handling import raise_status
from server.api.route_helpers import get_or_404
from server.crud.crud_faq import faq_crud
from server.db.models import FaqTable
from server.schemas.faq import FaqCreate, FaqCreated, FaqUpdate, FaqUpdated

logger = structlog.get_logger(__name__)

# Two routers, one auth posture each; the guard is declared at the mount in
# ``server/api/api.py``:
#
#   public_router   reads — the FAQ is public content     none
#   router          writes                                auth_required
router = APIRouter()

faq_page_params = page_params_for(faq_crud)


def _faq_or_404(faq_id: UUID, detail: str | None = None) -> FaqTable:
    return get_or_404(faq_crud.get(faq_id), detail or f"FAQ with id {faq_id} not found")


@router.post(
    "/",
    response_model=FaqCreated,
    status_code=HTTPStatus.CREATED,
    summary="Create FAQ entry",
    description="Add a new FAQ question and answer. Requires authentication. Returns 409 if a FAQ with the same question already exists.",
)
def create(data: FaqCreate = Body(...)) -> FaqTable:
    logger.info("Creating FAQ entry", data=data)

    if faq_crud.get_by_question(question=data.question):
        logger.error("FAQ question already exists", question=data.question)
        raise_status(HTTPStatus.CONFLICT, "A FAQ entry with this question already exists.")

    return faq_crud.create(obj_in=data)


@router.put(
    "/{faq_id}",
    response_model=FaqUpdated,
    status_code=HTTPStatus.CREATED,
    summary="Update FAQ entry",
    description="Update an existing FAQ entry's question, answer, or category. Returns 409 if another entry already uses the same question.",
)
def update(*, faq_id: UUID, item_in: FaqUpdate) -> FaqUpdated:
    faq = _faq_or_404(faq_id, "FAQ entry not found")

    if faq_crud.get_duplicate_question(question=item_in.question, faq_id=faq_id):
        raise_status(HTTPStatus.CONFLICT, "Another FAQ entry with the same question already exists.")

    faq = faq_crud.update(db_obj=faq, obj_in=item_in)

    return FaqUpdated(
        id=faq.id,
        question=faq.question,
        answer=faq.answer,
        category=faq.category,
    )


@router.delete(
    "/{faq_id}",
    response_model=None,
    status_code=HTTPStatus.NO_CONTENT,
    summary="Delete FAQ entry",
    description="Remove a FAQ entry. Requires authentication.",
)
def delete(faq_id: UUID) -> None:
    faq_crud.delete(id=faq_id)
