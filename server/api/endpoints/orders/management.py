from http import HTTPStatus
from typing import List
from uuid import UUID

import structlog
from fastapi import APIRouter
from fastapi.param_functions import Depends
from starlette.responses import Response

from server.api.deps import PageParams
from server.api.endpoints.orders.common import attach_names, mark_completed, order_page_params, order_updated
from server.api.route_helpers import get_or_404, list_page
from server.crud.crud_order import order_crud
from server.db.models import OrderTable
from server.schemas.order import (
    OrderSchema,
    OrderStatusUpdate,
    OrderUpdated,
)

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get(
    "/",
    response_model=List[OrderSchema],
    summary="List all orders",
    description="Returns all orders across all shops. Requires authentication. Supports pagination, filtering (e.g. `status:pending`), and sorting.",
)
def get_multi(response: Response, page: PageParams = Depends(order_page_params)) -> List[OrderTable]:
    orders = list_page(order_crud, page, response)
    attach_names(orders)
    return orders


@router.put(
    "/{order_id}",
    response_model=OrderUpdated,
    status_code=HTTPStatus.CREATED,
    summary="Update order status",
    description="Update an order's status or notes. Prices, line items, and totals are immutable after creation.",
)
def update(*, order_id: UUID, item_in: OrderStatusUpdate) -> OrderUpdated:
    order = get_or_404(order_crud.get(order_id), "Order not found")

    if item_in.status and (item_in.status == "complete" or item_in.status == "cancelled") and not order.completed_at:
        mark_completed(order)

    order = order_crud.update(db_obj=order, obj_in=item_in)
    return order_updated(order)


@router.delete(
    "/{order_id}",
    response_model=None,
    status_code=HTTPStatus.NO_CONTENT,
    summary="Delete order",
    description="Permanently remove an order record. Requires authentication.",
)
def delete(order_id: UUID) -> None:
    order_crud.delete(id=order_id)
