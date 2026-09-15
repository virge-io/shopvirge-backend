from operator import or_
from typing import List
from uuid import UUID

import structlog
from fastapi import APIRouter
from fastapi.param_functions import Depends
from starlette.responses import Response

from server.agent_tags import AgentTag
from server.api.deps import PageParams
from server.api.endpoints.orders.common import attach_names, order_page_params
from server.api.route_helpers import list_page
from server.crud.crud_order import order_crud
from server.db.models import OrderTable
from server.schemas.order import (
    OrderSchema,
)

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get(
    "/shop/{shop_id}/pending",
    response_model=List[OrderSchema],
    tags=[AgentTag.EXPOSED, AgentTag.LARGE],
    operation_id="list_pending_orders",
    summary="List pending orders for a shop",
    description=(
        "Read-only. Returns the shop's orders with status `pending` - orders awaiting fulfilment. "
        "Scoped to the shop in the path; you cannot read other shops' orders. Results include "
        "customer names and totals, so treat them as personal data. Supports pagination (`skip`/`limit`), "
        "filtering and sorting via the common query parameters. `filter` matches order fields only "
        "(status, dates, totals, etc.) and does NOT match customer name or email - to find a customer's "
        "orders, list the shop's orders and match on `account_name` client-side."
    ),
)
def show_all_pending_orders_per_shop(
    shop_id: UUID,
    response: Response,
    page: PageParams = Depends(order_page_params),
) -> List[OrderTable]:
    query = OrderTable.query.filter(OrderTable.shop_id == shop_id).filter(OrderTable.status == "pending")
    orders = list_page(order_crud, page, response, query=query)
    attach_names(orders)
    return orders


@router.get(
    "/shop/{shop_id}/complete",
    response_model=List[OrderSchema],
    tags=[AgentTag.EXPOSED, AgentTag.LARGE],
    operation_id="list_complete_orders",
    summary="List completed orders for a shop",
    description=(
        "Read-only. Returns the shop's orders with status `complete` or `cancelled` - the order history, "
        "useful for reporting. Scoped to the shop in the path; you cannot read other shops' orders. "
        "Results include customer names and totals, so treat them as personal data. Supports pagination "
        "(`skip`/`limit`), filtering and sorting via the common query parameters. `filter` matches order "
        "fields only (status, dates, totals, etc.) and does NOT match customer name or email - to find a "
        "customer's orders, list the shop's orders and match on `account_name` client-side."
    ),
)
def show_all_complete_orders_per_shop(
    shop_id: UUID,
    response: Response,
    page: PageParams = Depends(order_page_params),
) -> List[OrderTable]:
    query = OrderTable.query.filter(OrderTable.shop_id == shop_id).filter(
        or_(OrderTable.status == "complete", OrderTable.status == "cancelled")
    )
    orders = list_page(order_crud, page, response, query=query)
    attach_names(orders)
    return orders
