from datetime import datetime
from typing import Iterable

import structlog

from server.api.deps import page_params_for
from server.crud.crud_order import order_crud
from server.db.models import OrderTable
from server.schemas.order import OrderUpdated

logger = structlog.get_logger(__name__)

order_page_params = page_params_for(order_crud)


def attach_names(orders: Iterable[OrderTable]) -> None:
    """Populate ``account_name``/``shop_name``, which OrderSchema serialises but OrderTable doesn't store."""
    for order in orders:
        if order.account_id:
            order.account_name = order.account.name
        if order.shop_id:
            order.shop_name = order.shop.name


def mark_completed(order: OrderTable) -> None:
    order.completed_at = datetime.now()


def order_updated(order: OrderTable) -> OrderUpdated:
    return OrderUpdated(
        account_id=order.account_id,
        notes=order.notes,
        total=order.total,
        customer_order_id=order.customer_order_id,
        status=order.status,
        shop_id=order.shop_id,
        order_info=order.order_info,
        id=order.id,
    )
