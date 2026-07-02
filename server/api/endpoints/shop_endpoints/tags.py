from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, List
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query
from fastapi.param_functions import Body, Depends
from starlette.responses import Response

from server.agent_tags import AgentTag
from server.api.deps import common_parameters
from server.api.error_handling import raise_status
from server.crud.crud_tag import tag_crud
from server.db import db
from server.db.models import ApiKeyTable
from server.schemas.tag import TagCreate, TagSchema, TagUpdate
from server.security import auth_required_any

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get(
    "/",
    response_model=List[TagSchema],
    tags=[AgentTag.EXPOSED, AgentTag.LARGE],
    operation_id="list_tags",
    summary="List tags",
    description="Returns all tags defined for a shop. Tags can be attached to products for flexible grouping and filtering.",
)
def get_multi(shop_id: UUID, response: Response, common: dict = Depends(common_parameters)) -> List[TagSchema]:
    tags, header_range = tag_crud.get_multi_by_shop_id(
        shop_id=shop_id,
        skip=common["skip"],
        limit=common["limit"],
        filter_parameters=common["filter"],
        sort_parameters=common["sort"],
    )
    response.headers["Content-Range"] = header_range
    return tags


@router.get(
    "/{tag_id}",
    response_model=TagSchema,
    tags=[AgentTag.EXPOSED],
    operation_id="get_tag",
    summary="Get tag",
    description="Retrieve a single tag by its UUID within a shop.",
)
def get_by_id(tag_id: UUID, shop_id: UUID) -> TagSchema:
    tag = tag_crud.get_id_by_shop_id(shop_id, tag_id)
    if not tag:
        raise_status(HTTPStatus.NOT_FOUND, f"Tag with id {tag_id} not found")
    return tag


@router.get(
    "/name/{name}",
    response_model=TagSchema,
    summary="Get tag by name",
    description="Retrieve a tag by its exact name within a shop.",
)
def get_by_name(name: str, shop_id: UUID) -> TagSchema:
    tag = tag_crud.get_by_name(name=name, shop_id=shop_id)

    if not tag:
        raise_status(HTTPStatus.NOT_FOUND, f"Tag with name {name} not found")
    return tag


@router.post(
    "/",
    response_model=None,
    status_code=HTTPStatus.CREATED,
    tags=[AgentTag.EXPOSED],
    operation_id="create_tag",
    summary="Create tag",
    description="Create a new tag for a shop. Tags are attached to products via the `products-to-tags` resource.",
)
def create(shop_id: UUID, data: TagCreate = Body(...)) -> None:
    logger.info("Saving tag", data=data)
    tag = tag_crud.create_by_shop_id(shop_id=shop_id, obj_in=data)
    return tag


@router.put(
    "/{tag_id}",
    response_model=None,
    status_code=HTTPStatus.CREATED,
    tags=[AgentTag.EXPOSED],
    operation_id="update_tag",
    summary="Update tag",
    description="Update an existing tag's name or translations.",
)
def update(*, tag_id: UUID, shop_id: UUID, item_in: TagUpdate) -> Any:
    tag = tag_crud.get_id_by_shop_id(shop_id, tag_id)
    logger.info("Updating tag", data=tag)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    tag = tag_crud.update(
        db_obj=tag,
        obj_in=item_in,
    )
    return tag


@router.delete(
    "/{tag_id}",
    response_model=None,
    status_code=HTTPStatus.NO_CONTENT,
    tags=[AgentTag.EXPOSED],
    operation_id="delete_tag",
    summary="Delete tag (moves to trash)",
    description=(
        "Moves a tag to the trash: it disappears from listings and from the products carrying it, but its "
        "product links are kept so restoring the tag brings everything back. This action is reversible. "
        "Only `force=true` permanently purges the tag (and its product links); that is irreversible and "
        "requires user (Cognito) credentials — API keys get 403."
    ),
)
def delete(
    tag_id: UUID,
    shop_id: UUID,
    force: bool = Query(False, description="Permanently purge instead of moving to trash. Irreversible."),
    principal: Any = Depends(auth_required_any),
) -> None:
    tag = tag_crud.get_id_by_shop_id(shop_id, tag_id, for_update=True, include_deleted=force)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    if force:
        if isinstance(principal, ApiKeyTable):
            raise HTTPException(
                status_code=403,
                detail="Purging a tag is irreversible and requires user credentials; API keys may only trash.",
            )
        try:
            tag_crud.delete_by_shop_id(shop_id=shop_id, id=tag_id, include_deleted=True)
        except Exception as e:
            raise HTTPException(HTTPStatus.BAD_REQUEST, detail=f"{e.__cause__}")
        return None

    tag.deleted_at = datetime.now(timezone.utc)
    db.session.commit()
    return None
