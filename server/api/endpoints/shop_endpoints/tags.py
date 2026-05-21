from http import HTTPStatus
from typing import Any, List
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.param_functions import Body, Depends
from starlette.responses import Response

from server.agent_tags import AgentTag
from server.api.deps import common_parameters
from server.api.error_handling import raise_status
from server.crud.crud_tag import tag_crud
from server.schemas.tag import TagCreate, TagSchema, TagUpdate

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get(
    "/",
    response_model=List[TagSchema],
    tags=[AgentTag.EXPOSED, AgentTag.LARGE],
    operation_id="list_tags",
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
)
def get_by_id(tag_id: UUID, shop_id: UUID) -> TagSchema:
    tag = tag_crud.get_id_by_shop_id(shop_id, tag_id)
    if not tag:
        raise_status(HTTPStatus.NOT_FOUND, f"Tag with id {tag_id} not found")
    return tag


@router.get("/name/{name}", response_model=TagSchema)
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
)
def delete(tag_id: UUID, shop_id: UUID) -> None:
    try:
        tag_crud.delete_by_shop_id(shop_id=shop_id, id=tag_id)
    except Exception as e:
        raise HTTPException(HTTPStatus.BAD_REQUEST, detail=f"{e.__cause__}")
    return
