from typing import List
from uuid import UUID

import structlog
from fastapi import APIRouter
from fastapi.param_functions import Depends
from starlette.responses import Response

from server.api.deps import PageParams
from server.api.endpoints.content.faq import _faq_or_404, faq_page_params
from server.api.route_helpers import list_page
from server.crud.crud_faq import faq_crud
from server.db.models import FaqTable
from server.schemas.faq import FaqSchema

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get(
    "/",
    response_model=List[FaqSchema],
    summary="List FAQ entries",
    description="Returns all FAQ question/answer entries. Supports pagination, filtering, and sorting.",
)
def get_multi(response: Response, page: PageParams = Depends(faq_page_params)) -> List[FaqTable]:
    return list_page(faq_crud, page, response)


@router.get(
    "/{id}",
    response_model=FaqSchema,
    summary="Get FAQ entry",
    description="Retrieve a single FAQ entry by its UUID.",
)
def get_by_id(id: UUID) -> FaqTable:
    return _faq_or_404(id)
