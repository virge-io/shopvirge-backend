from datetime import datetime
from http import HTTPStatus
from typing import List
from uuid import UUID

import stripe
import structlog
from fastapi import APIRouter, Request
from fastapi.param_functions import Body

from server.api.endpoints.orders.common import attach_names, mark_completed, order_updated, quote_order
from server.api.error_handling import raise_status
from server.api.helpers import invalidateCompletedOrdersCache, invalidatePendingOrdersCache
from server.api.route_helpers import get_or_404
from server.api.utils import is_ip_allowed, validate_uuid4
from server.crud.crud_account import account_crud
from server.crud.crud_order import order_crud
from server.crud.crud_product import product_crud
from server.crud.crud_shop import shop_crud
from server.db.models import Account, OrderTable
from server.mail import send_order_confirmation_emails
from server.schemas import ProductUpdate
from server.schemas.account import AccountCreate
from server.schemas.order import (
    OrderCreate,
    OrderCreated,
    OrderPersisted,
    OrderQuote,
    OrderQuoteRequest,
    OrderSchema,
    OrderStatusUpdate,
    OrderUpdated,
)
from server.services import stripe_client
from server.services.stripe_client import StripeNotConfigured
from server.settings import mail_settings
from server.utils.discord.discord import post_discord_order_complete

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get(
    "/{id}",
    response_model=OrderSchema,
    summary="Get order",
    description="Retrieve a single order by its UUID, including line items, account name, and shop name.",
)
def get_by_id(id: UUID) -> OrderTable:
    order = get_or_404(order_crud.get(id), f"Order with id {id} not found")
    attach_names([order])
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
        item = order_crud.get(id)
        if item:
            items.append(item)

    for item in items:
        if item.shop_id != items[0].shop_id:
            raise_status(HTTPStatus.BAD_REQUEST, "All ID's should belong to one shop")
        else:
            checked_order = OrderCreated(
                account_id=item.account_id,
                total=item.total,
                notes=item.notes,
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
    shop = get_or_404(shop_crud.get(data.shop_id), f"Shop with id {data.shop_id} not found")
    return quote_order(shop, data, validate_stock=True)


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
    shop = get_or_404(shop_crud.get(shop_id), f"Shop with id {shop_id} not found")

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

    order_quote = quote_order(shop, data, validate_stock=True)

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
    order = get_or_404(order_crud.get(order_id), "Order not found")

    # Early exit if status of request is the same as in db, as or right now there is you cant cancel or complete an order again
    if item_in.status and order.status == item_in.status:
        logger.info(f"Order status is already set to {item_in.status}")
        return order_updated(order)

    shop_id = order.shop_id
    shop = get_or_404(shop_crud.get(shop_id), f"Shop with ID {shop_id} not found")

    if item_in.status in {"complete", "cancelled"} and not order.completed_at:
        mark_completed(order)

    order = order_crud.update(
        db_obj=order,
        obj_in=item_in,
    )

    updated_order = order_updated(order)

    # The following is fixed by the early exit from before `order.status == item_in.status`:
    # `item_in.status == "complete"` is not enough because it doesn't account for the order's current status, this means that the stock gets updated even though the order might not have been changed
    if shop.config["toggles"]["enable_stock_on_products"] and item_in.status == "complete":
        for order_product in order.order_info:
            product = get_or_404(
                product_crud.get_id_by_shop_id(shop_id, order_product["product_id"]),
                f"Product {order_product['product_id']} not found for this shop",
            )

            logger.info(
                f"Updating stock for order {product.id} , old stock: {product.stock}, new stock: {product.stock - order_product['quantity']}"
            )

            # PATCH semantics: only the field we actually change (see ProductUpdate).
            new_product = ProductUpdate(stock=product.stock - order_product["quantity"])
            product_crud.update(db_obj=product, obj_in=new_product)

    # Fetch account once for Discord and email notifications
    account = account_crud.get(updated_order.account_id) if updated_order.account_id else None

    try:
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


@router.get(
    "/stock/{order_id}",
    response_model=bool,
    summary="Check order stock availability",
    description="Returns `true` if all products in the order have sufficient stock, `false` otherwise. Only meaningful when the shop has stock tracking enabled.",
)
def get_order_products_in_stock(order_id: UUID) -> bool:
    order = get_or_404(order_crud.get(order_id), "Order not found")

    shop_id = order.shop_id
    shop = get_or_404(shop_crud.get(shop_id), f"Shop with ID {shop_id} not found")

    if shop.config["toggles"]["enable_stock_on_products"]:
        for order_product in order.order_info:
            product = product_crud.get_id_by_shop_id(shop_id, order_product["product_id"])
            if not product or product.stock < order_product["quantity"]:
                return False

    return True
