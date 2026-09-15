from datetime import datetime
from decimal import Decimal
from http import HTTPStatus
from typing import Iterable

import structlog

from server.api.deps import page_params_for
from server.api.error_handling import raise_status
from server.crud.crud_order import order_crud
from server.crud.crud_product import product_crud
from server.db.models import OrderTable, ProductTable, ShopTable
from server.schemas.base import quantize_money
from server.schemas.order import (
    OrderItem,
    OrderQuote,
    OrderQuoteRequest,
    OrderUpdated,
)
from server.services.shipping import compute_shipping_for_cart, resolve_vat_rate

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


def _discount_active(product: ProductTable) -> bool:
    """True if the product's discount window is currently open.

    A missing ``discounted_from``/``discounted_to`` bound is treated as open on
    that side (an ongoing discount).
    """
    now = datetime.now()
    start = product.discounted_from
    end = product.discounted_to
    if start is not None and now < start:
        return False
    if end is not None and now > end:
        return False
    return True


def _authoritative_unit_price_ex(product: ProductTable, plan: str) -> Decimal:
    """Resolve a net unit price from the product's catalogue price."""
    if plan == "monthly":
        price = product.recurring_price_monthly
    elif plan == "yearly":
        price = product.recurring_price_yearly
    else:
        price = (
            product.discounted_price
            if product.discounted_price is not None and _discount_active(product)
            else product.price
        )

    if price is None:
        raise_status(HTTPStatus.UNPROCESSABLE_ENTITY, f"Product '{product.id}' has no {plan} price")

    return price


def _authoritative_unit_price_inc(product: ProductTable, shop: ShopTable, plan: str) -> Decimal:
    """Resolve a gross unit price from the product's net catalogue price."""
    price = _authoritative_unit_price_ex(product, plan)
    tax_rate = resolve_vat_rate(product, shop)
    return quantize_money(price * (Decimal("1") + tax_rate / Decimal("100")))


def quote_order(shop: ShopTable, data: OrderQuoteRequest, validate_stock: bool) -> OrderQuote:
    plans = {item.plan for item in data.order_info}
    if len(plans) > 1:
        raise_status(HTTPStatus.UNPROCESSABLE_ENTITY, "All order lines must use the same payment plan")

    order_info: list[OrderItem] = []
    shipping_order_info: list[OrderItem] = []
    for requested_item in data.order_info:
        product = product_crud.get_id_by_shop_id(shop.id, requested_item.product_id)
        if not product:
            raise_status(HTTPStatus.NOT_FOUND, f"Product '{requested_item.product_name}' not found")

        # Availability check
        if (
            validate_stock
            and shop.config["toggles"]["enable_stock_on_products"]
            and product.stock < requested_item.quantity
        ):
            raise_status(HTTPStatus.BAD_REQUEST, f"Not enough stock for product '{requested_item.product_name}'")

        price_ex = _authoritative_unit_price_ex(product, requested_item.plan)
        order_info.append(
            OrderItem(
                **requested_item.model_dump(),
                price=_authoritative_unit_price_inc(product, shop, requested_item.plan),
            )
        )
        shipping_order_info.append(OrderItem(**requested_item.model_dump(), price=price_ex))

    shipping_calc = compute_shipping_for_cart(shipping_order_info, shop)
    shipping_fee_inc_btw = shipping_calc.fee_inc_btw if shipping_calc is not None else None
    subtotal = quantize_money(sum((item.price * item.quantity for item in order_info), Decimal("0")))
    return OrderQuote(
        order_info=order_info,
        subtotal=subtotal,
        shipping_fee_inc_btw=shipping_fee_inc_btw,
        free_shipping_applied=shipping_calc.free_shipping_applied if shipping_calc is not None else False,
        free_shipping_threshold=shipping_calc.free_shipping_threshold if shipping_calc is not None else None,
        total=quantize_money(subtotal + (shipping_fee_inc_btw or Decimal("0"))),
    )
