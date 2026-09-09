from datetime import datetime
from decimal import Decimal
from http import HTTPStatus
from operator import or_
from typing import Any, List
from uuid import UUID

import stripe
import structlog
from alembic.util import not_none
from fastapi import APIRouter, HTTPException, Request
from fastapi.param_functions import Body, Depends
from starlette.responses import Response

from server.agent_tags import AgentTag
from server.api import deps
from server.api.deps import common_parameters
from server.api.error_handling import raise_status
from server.api.helpers import _query_with_filters, invalidateCompletedOrdersCache, invalidatePendingOrdersCache, load
from server.api.utils import is_ip_allowed, validate_uuid4
from server.crud.crud_account import account_crud
from server.crud.crud_order import order_crud
from server.crud.crud_product import product_crud
from server.crud.crud_shop import shop_crud
from server.db.models import Account, OrderTable, ProductTable, ShopTable
from server.mail import send_order_confirmation_emails
from server.schemas import ProductUpdate
from server.schemas.account import AccountCreate
from server.schemas.base import quantize_money
from server.schemas.order import (
    OrderCreate,
    OrderCreated,
    OrderItem,
    OrderPersisted,
    OrderQuote,
    OrderQuoteRequest,
    OrderSchema,
    OrderStatusUpdate,
    OrderUpdated,
)
from server.schemas.product import ProductTranslationBase
from server.security import CustomCognitoToken, auth_required, auth_required_any_for_shop
from server.services import stripe_client
from server.services.shipping import compute_shipping_for_cart, resolve_vat_rate
from server.services.stripe_client import StripeNotConfigured
from server.settings import mail_settings
from server.utils.discord.discord import post_discord_order_complete

logger = structlog.get_logger(__name__)

router = APIRouter()


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


def _quote_order(shop: ShopTable, data: OrderQuoteRequest, validate_stock: bool) -> OrderQuote:
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


@router.get(
    "/",
    response_model=List[OrderSchema],
    summary="List all orders",
    description="Returns all orders across all shops. Requires authentication. Supports pagination, filtering (e.g. `status:pending`), and sorting.",
)
def get_multi(
    response: Response,
    common: dict = Depends(common_parameters),
    current_user: CustomCognitoToken = Depends(auth_required),
) -> List[OrderSchema]:
    orders, header_range = order_crud.get_multi(
        skip=common["skip"], limit=common["limit"], filter_parameters=common["filter"], sort_parameters=common["sort"]
    )
    for order in orders:
        if order.account_id:
            order.account_name = order.account.name
        if order.shop_id:
            order.shop_name = order.shop.name
    response.headers["Content-Range"] = header_range
    return orders


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
    common: dict = Depends(common_parameters),
    principal: Any = Depends(auth_required_any_for_shop),
) -> List[OrderSchema]:
    query = OrderTable.query.filter(OrderTable.shop_id == shop_id).filter(OrderTable.status == "pending")
    orders, header_range = order_crud.get_multi(
        query_parameter=query,
        skip=common["skip"],
        limit=common["limit"],
        filter_parameters=common["filter"],
        sort_parameters=common["sort"],
    )

    for order in orders:
        if order.account_id:
            order.account_name = order.account.name
        if order.shop_id:
            order.shop_name = order.shop.name

    response.headers["Content-Range"] = header_range
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
    common: dict = Depends(common_parameters),
    principal: Any = Depends(auth_required_any_for_shop),
) -> List[OrderSchema]:
    query = OrderTable.query.filter(OrderTable.shop_id == shop_id).filter(
        or_(OrderTable.status == "complete", OrderTable.status == "cancelled")
    )
    orders, header_range = order_crud.get_multi(
        query_parameter=query,
        skip=common["skip"],
        limit=common["limit"],
        filter_parameters=common["filter"],
        sort_parameters=common["sort"],
    )

    for order in orders:
        if order.account_id:
            order.account_name = order.account.name
        if order.shop_id:
            order.shop_name = order.shop.name

    response.headers["Content-Range"] = header_range
    return orders


@router.get(
    "/{id}",
    summary="Get order",
    description="Retrieve a single order by its UUID, including line items, account name, and shop name.",
)
def get_by_id(id: UUID) -> OrderSchema:
    order = order_crud.get(id)
    if not order:
        raise_status(HTTPStatus.NOT_FOUND, f"Order with id {id} not found")

    if order.account_id:
        order.account_name = order.account.name
    if order.shop_id:
        order.shop_name = order.shop.name

    return order


@router.get(
    "/check/{ids}",
    response_model=List[OrderCreated],
    summary="Check order statuses",
    description="Retrieve the status and totals of up to 10 orders by passing a comma-separated list of UUIDs. All orders must belong to the same shop. Used by the checkout confirmation page.",
)
def check(
    ids: str,
) -> List[OrderCreated]:
    id_list = ids.split(",")

    # Validate input
    for index, id in enumerate(id_list):
        if not validate_uuid4(id):
            raise_status(HTTPStatus.BAD_REQUEST, f"ID {index + 1} is not valid")

    if len(id_list) > 10:
        raise_status(HTTPStatus.BAD_REQUEST, "Max 10 orders")

    # Build response
    items = []
    items_with_schema = []
    for id in id_list:
        # item = load(Order, id, allow_404=True) #the old
        item = order_crud.get(id)
        if item:
            item.account_name = item.account.name
            items.append(item)

    for item in items:
        if item.shop_id != items[0].shop_id:
            raise_status(HTTPStatus.BAD_REQUEST, "All ID's should belong to one shop")
        else:
            checked_order = OrderCreated(
                account_id=item.account_id,
                total=item.total,
                customer_order_id=item.customer_order_id,
                status=item.status,
                id=item.id,
                created_at=item.created_at,
                completed_at=item.completed_at,
                account_name=item.account.name,
            )
            items_with_schema.append(checked_order)

    return items_with_schema


@router.post(
    "/quote",
    response_model=OrderQuote,
    summary="Quote an order",
    description="Calculate gross line prices, shipping, and total from product IDs, quantities, and plans.",
)
def quote(data: OrderQuoteRequest = Body(...)) -> OrderQuote:
    shop = shop_crud.get(data.shop_id)
    if not shop:
        raise_status(HTTPStatus.NOT_FOUND, f"Shop with id {data.shop_id} not found")
    return _quote_order(shop, data, validate_stock=True)


@router.post(
    "/",
    response_model=OrderCreated,
    status_code=HTTPStatus.CREATED,
    summary="Create order",
    description=(
        "Submit a new customer order. The caller's IP is validated against the shop's allowlist. "
        "Unit prices, shipping, and totals are derived server-side from the product catalogue. "
        "If stock tracking is enabled the product availability is verified before the order is created. "
        "A Stripe customer is auto-created for new account names when the shop has Stripe configured."
    ),
)
def create(request: Request, data: OrderCreate = Body(...)) -> OrderCreated:
    logger.info("Saving order", data=data)

    shop_id = data.shop_id
    shop = shop_crud.get(shop_id)
    if not shop:
        raise_status(HTTPStatus.NOT_FOUND, f"Shop with id {shop_id} not found")

    if data.account_name and not data.account_id:
        accounts = Account.query.filter(Account.shop_id == shop_id)
        new_account = True
        for account in accounts:
            if account.name == data.account_name:
                new_account = False
                data.account_id = account.id
                del data.account_name
                break

        if new_account:
            details = {}
            try:
                stripe_client.configure_for_shop(shop)
                customer = stripe.Customer.create(email=data.account_name)
                details["stripe_customer_id"] = customer.id
            except StripeNotConfigured:
                # Shop has no Stripe key configured — proceed without
                # creating a Stripe customer (matches prior behavior).
                logger.info(
                    "Skipping Stripe customer creation: shop has no stripe_secret_key",
                    shop_id=str(shop.id),
                    account_name=data.account_name,
                )

            account_data = AccountCreate(shop_id=data.shop_id, name=data.account_name, details=details)
            account = account_crud.create(obj_in=account_data)
            data.account_id = account.id
            del data.account_name

    if not is_ip_allowed(request, shop) and str(data.account_id) != "0999fbcd-a72b-4cc2-abbe-41ccd466cdaf":
        # allow test table to bypass IP check if any
        raise_status(HTTPStatus.BAD_REQUEST, "NOT_ON_SHOP_WIFI")

    order_quote = _quote_order(shop, data, validate_stock=True)

    status = "pending"
    completed_at = None
    if str(data.account_id) == "0999fbcd-a72b-4cc2-abbe-41ccd466cdaf":
        # Test table -> flag it complete
        status = "complete"
        completed_at = datetime.now()

    # Compute shipping fee from shop config and recompute the persisted total
    # server-side from the authoritative line prices so it can't be manipulated
    # by the client.
    order = order_crud.create_with_next_customer_order_id(
        obj_in=OrderPersisted(
            account_id=data.account_id,
            total=order_quote.total,
            notes=data.notes,
            customer_order_id=None,
            status=status,
            shipping_fee_inc_btw=order_quote.shipping_fee_inc_btw,
            shop_id=shop_id,
            order_info=order_quote.order_info,
            completed_at=completed_at,
        )
    )

    created_order = OrderCreated(
        account_id=order.account_id,
        total=order.total,
        customer_order_id=order.customer_order_id,
        notes=order.notes,
        status=order.status,
        id=order.id,
        order_info=order.order_info,
        created_at=order.created_at,
        completed_at=order.completed_at,
        account_name=order.account.name,
        shipping_fee_inc_btw=order.shipping_fee_inc_btw,
    )
    if str(data.account_id) == "0999fbcd-a72b-4cc2-abbe-41ccd466cdaf":
        # Test table -> invalidate completed orders
        invalidateCompletedOrdersCache(created_order.id)
    else:
        invalidatePendingOrdersCache(created_order.id)
    return created_order


# TODO mention discord in documentation?
@router.patch(
    "/{order_id}",
    response_model=OrderUpdated,
    status_code=HTTPStatus.CREATED,
    summary="Update order status",
    description=(
        "Partially update an order — typically to mark it `complete` or `cancelled`. "
        "Setting status to `complete` triggers stock deduction (if enabled), a Discord webhook "
        "notification, and an order confirmation email. Idempotent: setting the same status twice is a no-op."
    ),
)
def patch(
    *,
    order_id: UUID,
    item_in: OrderStatusUpdate,
) -> OrderUpdated:
    order = order_crud.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Early exit if status of request is the same as in db, as or right now there is you cant cancel or complete an order again
    if item_in.status and order.status == item_in.status:
        logger.info(f"Order status is already set to {item_in.status}")
        return order

    shop_id = order.shop_id
    shop = shop_crud.get(shop_id)
    if not shop:
        raise HTTPException(status_code=404, detail=f"Shop with ID {shop_id} not found")

    if item_in.status in {"complete", "cancelled"} and not order.completed_at:
        order.completed_at = datetime.now()

    order = order_crud.update(
        db_obj=order,
        obj_in=item_in,
    )

    updated_order = OrderUpdated(
        account_id=order.account_id,
        notes=order.notes,
        total=order.total,
        customer_order_id=order.customer_order_id,
        status=order.status,
        shop_id=order.shop_id,
        order_info=order.order_info,
        id=order.id,
    )

    # The following is fixed by the early exit from before `order.status == item_in.status`:
    # `item_in.status == "complete"` is not enough because it doesn't account for the order's current status, this means that the stock gets updated even though the order might not have been changed
    if shop.config["toggles"]["enable_stock_on_products"] and item_in.status == "complete":
        for order_product in order.order_info:
            product = product_crud.get_id_by_shop_id(shop_id, order_product["product_id"])

            logger.info(
                f"Updating stock for order {product.id} , old stock: {product.stock}, new stock: {product.stock - order_product['quantity']}"
            )

            # PATCH semantics: only the field we actually change (see ProductUpdate).
            new_product = ProductUpdate(stock=product.stock - order_product["quantity"])
            product_crud.update(db_obj=product, obj_in=new_product)

    # Fetch account once for Discord and email notifications
    account = account_crud.get(updated_order.account_id) if updated_order.account_id else None

    try:
        shop = load(ShopTable, updated_order.shop_id)
        if shop.discord_webhook is not None and account:
            post_discord_order_complete(
                f"New order from {account.name}",
                botname=shop.name,
                webhook=shop.discord_webhook,
                order=updated_order,
                email=account.name,
            )
    except Exception as e:
        logger.error("Failed to post to Discord: ", error=str(e))

    # Send order confirmation emails
    if mail_settings.SHOP_MAIL_ENABLED and item_in.status == "complete" and account:
        try:
            send_order_confirmation_emails(order=order, shop=shop, account=account)
        except Exception as e:
            logger.error("Failed to send order confirmation email", error=str(e))

    invalidateCompletedOrdersCache(updated_order.id)
    return updated_order


def update_stock_on_order_complete(order_id: UUID):
    order = order_crud.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")


@router.put(
    "/{order_id}",
    response_model=OrderUpdated,
    status_code=HTTPStatus.CREATED,
    summary="Update order status",
    description="Update an order's status or notes. Prices, line items, and totals are immutable after creation.",
)
def update(
    *, order_id: UUID, item_in: OrderStatusUpdate, current_user: CustomCognitoToken = Depends(auth_required)
) -> OrderUpdated:
    order = order_crud.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if item_in.status and (item_in.status == "complete" or item_in.status == "cancelled") and not order.completed_at:
        order.completed_at = datetime.now()

    order = order_crud.update(
        db_obj=order,
        obj_in=item_in,
    )

    updated_order = OrderUpdated(
        account_id=order.account_id,
        notes=order.notes,
        total=order.total,
        customer_order_id=order.customer_order_id,
        status=order.status,
        shop_id=order.shop_id,
        order_info=order.order_info,
        id=order.id,
    )

    return updated_order


@router.delete(
    "/{order_id}",
    response_model=None,
    status_code=HTTPStatus.NO_CONTENT,
    summary="Delete order",
    description="Permanently remove an order record. Requires authentication.",
)
def delete(order_id: UUID, current_user: CustomCognitoToken = Depends(auth_required)) -> None:
    return order_crud.delete(id=order_id)


@router.get(
    "/stock/{order_id}",
    response_model=bool,
    summary="Check order stock availability",
    description="Returns `true` if all products in the order have sufficient stock, `false` otherwise. Only meaningful when the shop has stock tracking enabled.",
)
def get_order_products_in_stock(order_id: UUID) -> bool:
    order = order_crud.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    shop_id = order.shop_id
    shop = shop_crud.get(shop_id)
    if not shop:
        raise HTTPException(status_code=404, detail=f"Shop with ID {shop_id} not found")

    if shop.config["toggles"]["enable_stock_on_products"]:
        for order_product in order.order_info:
            product = product_crud.get_id_by_shop_id(shop_id, order_product["product_id"])
            if not product or product.stock < order_product["quantity"]:
                return False

    return True
