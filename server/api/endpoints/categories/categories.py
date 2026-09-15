from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, List
from uuid import UUID, uuid4

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.param_functions import Body, Depends
from starlette.responses import Response

from server.agent_tags import AgentTag
from server.api.deps import common_parameters
from server.api.error_handling import raise_status
from server.crud import crud_shop
from server.crud.crud_category import category_crud
from server.db import db
from server.db.models import (
    CategoryTable,
    ProductTable,
)
from server.schemas.category import (
    CategoryCreate,
    CategoryOrder,
    CategorySchema,
    CategoryUpdate,
)
from server.security import auth_required_any
from server.services.revisions import (
    actor,
    ensure_baseline_category_revision,
    ensure_baseline_product_revision,
    record_category_revision,
    record_product_revision,
)

logger = structlog.get_logger(__name__)

router = APIRouter()


def get_shop(shop_id: UUID):
    shop = crud_shop.get_id(id=shop_id)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    return shop


@router.get(
    "/",
    response_model=List[CategorySchema],
    tags=[AgentTag.EXPOSED, AgentTag.LARGE],
    operation_id="list_categories",
    summary="List categories",
    description="Returns paginated categories for a shop, ordered by `order_number`. Supports filtering and sorting.",
)
def get_multi(shop_id: UUID, response: Response, common: dict = Depends(common_parameters)) -> List[CategorySchema]:
    # shop = get_shop(shop_id)
    categories, header_range = category_crud.get_multi_by_shop_id(
        shop_id=shop_id,
        skip=common["skip"],
        limit=common["limit"],
        filter_parameters=common["filter"],
        sort_parameters=common["sort"],
    )
    response.headers["Content-Range"] = header_range
    return categories


@router.get(
    "/{category_id}",
    response_model=CategorySchema,
    tags=[AgentTag.EXPOSED],
    operation_id="get_category",
    summary="Get category",
    description="Retrieve a single category by its UUID within a shop.",
)
def get_by_id(shop_id: UUID, category_id: UUID) -> CategorySchema:
    category = category_crud.get_id_by_shop_id(shop_id, category_id)
    if not category:
        raise_status(HTTPStatus.NOT_FOUND, f"Category with id {category_id} not found")
    return category


@router.get(
    "/name/{name}",
    response_model=CategorySchema,
    summary="Get category by name",
    description="Retrieve a category using its human-readable name (exact match, case-sensitive).",
)
def get_by_name(name: str, shop_id: UUID) -> CategorySchema:
    category = category_crud.get_by_name(name=name, shop_id=shop_id)

    if not category:
        raise_status(HTTPStatus.NOT_FOUND, f"Category with name {name} not found")
    return category


@router.post(
    "/",
    response_model=None,
    status_code=HTTPStatus.CREATED,
    tags=[AgentTag.EXPOSED],
    operation_id="create_category",
    summary="Create category",
    description="Add a new category to a shop. The `order_number` is automatically set to the next available value.",
)
def create(
    shop_id: UUID, request: Request, data: CategoryCreate = Body(...), principal: Any = Depends(auth_required_any)
) -> None:
    category = CategoryTable.query.filter_by(shop_id=shop_id).order_by(CategoryTable.order_number.desc()).first()
    data.order_number = (category.order_number + 1) if category is not None else 0

    logger.info("Saving category", data=data)
    created_by, source = actor(principal, request)
    category = category_crud.create_by_shop_id(obj_in=data, shop_id=shop_id, commit=False)
    record_category_revision(category, action="create", created_by=created_by, source=source)
    db.session.commit()
    db.session.refresh(category)
    return category


@router.put(
    "/{category_id}",
    response_model=None,
    status_code=HTTPStatus.CREATED,
    tags=[AgentTag.EXPOSED],
    operation_id="update_category",
    summary="Update category",
    description=(
        "Partially update a category. Send ONLY the fields you want to change; omitted fields are left "
        "untouched. Names and descriptions live in the nested `translation` object and can also be sent "
        "partially. `main_image`, `alt1_image` and `alt2_image` are S3 object filenames managed by the "
        "image-upload flow - do not set them unless explicitly given a filename."
    ),
)
def update(
    *,
    category_id: UUID,
    shop_id: UUID,
    item_in: CategoryUpdate,
    request: Request,
    principal: Any = Depends(auth_required_any),
) -> Any:
    category = category_crud.get_id_by_shop_id(shop_id, category_id, for_update=True)
    logger.info("Updating category", data=category)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    created_by, source = actor(principal, request)
    ensure_baseline_category_revision(category)
    category = category_crud.update(
        db_obj=category,
        obj_in=item_in,
        commit=False,
    )
    record_category_revision(category, action="update", created_by=created_by, source=source)
    db.session.commit()

    return category


@router.put(
    "/{category_id}/swap",
    response_model=None,
    status_code=HTTPStatus.CREATED,
    summary="Reorder category",
    description="Move a category up (`move_up=true`) or down (`move_up=false`) in the display order. Swaps `order_number` with the adjacent category.",
)
def swap(shop_id: UUID, category_id: UUID, move_up: bool):
    category = category_crud.get_id_by_shop_id(shop_id, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    last_category = CategoryTable.query.filter_by(shop_id=shop_id).order_by(CategoryTable.order_number.desc()).first()

    first_category = CategoryTable.query.filter_by(shop_id=shop_id).order_by(CategoryTable.order_number.asc()).first()

    old_order_number = category.order_number
    new_order_number = None

    if move_up:
        if old_order_number == first_category.order_number:
            raise HTTPException(status_code=400, detail="Cannot move up further - Minimum order number achieved.")
        new_order_number = old_order_number - 1
    else:
        if old_order_number == last_category.order_number:
            raise HTTPException(status_code=400, detail="Cannot move down further - Maximum order number achieved.")
        new_order_number = old_order_number + 1

    category_to_swap = CategoryTable.query.filter_by(shop_id=shop_id).filter_by(order_number=new_order_number).first()

    if category_to_swap is not None:
        category_crud.update(db_obj=category_to_swap, obj_in=CategoryOrder(order_number=old_order_number), commit=False)

    category_crud.update(db_obj=category, obj_in=CategoryOrder(order_number=new_order_number))

    return HTTPStatus.CREATED


@router.delete(
    "/{category_id}",
    response_model=None,
    status_code=HTTPStatus.NO_CONTENT,
    tags=[AgentTag.EXPOSED],
    operation_id="delete_category",
    summary="Delete category (moves to trash)",
    description=(
        "Moves a category to the trash (restorable with `restore_category`). If products are still "
        "assigned to it the request fails with 409 and the product count; retry with `force=true` to "
        "also move all those products to the trash (restorable as one batch), or with `detach=true` to "
        "keep the products but clear their category. `force` and `detach` are mutually exclusive."
    ),
)
def delete(
    category_id: UUID,
    shop_id: UUID,
    request: Request,
    force: bool = Query(False, description="Also move all products in this category to the trash."),
    detach: bool = Query(False, description="Keep the products; clear their category reference instead."),
    principal: Any = Depends(auth_required_any),
) -> None:
    if force and detach:
        raise HTTPException(status_code=422, detail="force and detach are mutually exclusive")

    category = category_crud.get_id_by_shop_id(shop_id, category_id, for_update=True)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    products = (
        db.session.query(ProductTable)
        .filter(ProductTable.shop_id == shop_id, ProductTable.category_id == category_id)
        .with_for_update()
        .all()
    )

    if products and not force and not detach:
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"Category still has {len(products)} product(s); deleting it affects all of them.",
                "product_count": len(products),
                "hint": (
                    "Retry with force=true to move the products to the trash too (restorable as one batch), "
                    "or detach=true to keep the products without a category."
                ),
            },
        )

    created_by, source = actor(principal, request)
    now = datetime.now(timezone.utc)
    extra_data = None

    if products and force:
        batch_id = uuid4()
        for product in products:
            record_product_revision(product, action="delete", created_by=created_by, source=source)
            product.deleted_at = now
            product.deleted_batch_id = batch_id
        extra_data = {"deleted_batch_id": str(batch_id), "deleted_product_count": len(products)}
    elif products and detach:
        category_name = category.translation.main_name if category.translation else None
        detached_from = {"id": str(category_id), "name": category_name}
        for product in products:
            ensure_baseline_product_revision(product)
            product.category_id = None
            record_product_revision(
                product,
                action="update",
                created_by=created_by,
                source=source,
                extra_data={"detached_from_category": detached_from},
            )
        extra_data = {"detached_product_count": len(products)}

    record_category_revision(category, action="delete", created_by=created_by, source=source, extra_data=extra_data)
    category.deleted_at = now
    db.session.commit()
    return
