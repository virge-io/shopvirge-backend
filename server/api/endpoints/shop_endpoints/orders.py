from datetime import datetime
from decimal import Decimal
from http import HTTPStatus
from operator import or_
from typing import Any, List, Optional
from uuid import UUID

import stripe
import structlog
from alembic.util import not_none
from fastapi import APIRouter, HTTPException, Request
from fastapi.param_functions import Body, Depends
from starlette.responses import Response

from server.api import deps
from server.api.deps import common_parameters
from server.api.error_handling import raise_status
from server.api.helpers import _query_with_filters, invalidateCompletedOrdersCache, invalidatePendingOrdersCache, load
from server.api.utils import is_ip_allowed, validate_uuid4
from server.crud.crud_account import account_crud
from server.crud.crud_order import order_crud
from server.crud.crud_product import product_crud
from server.crud.crud_shop import shop_crud
from server.db.models import Account, OrderTable, ShopTable
from server.mail import send_order_confirmation_emails
from server.schemas import ProductUpdate
from server.schemas.account import AccountCreate
from server.schemas.base import quantize_money
from server.schemas.order import OrderBase, OrderCreate, OrderCreated, OrderSchema, OrderUpdate, OrderUpdated
from server.schemas.product import ProductTranslationBase
from server.security import CustomCognitoToken, auth_required
from server.services import stripe_client
from server.services.shipping import compute_shipping_for_cart
from server.services.stripe_client import StripeNotConfigured
from server.settings import mail_settings
from server.utils.discord.discord import post_discord_order_complete

logger = structlog.get_logger(__name__)

router = APIRouter()


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
        if (order.status == "complete" or order.status == "cancelled") and order.completed_by:
            order.completed_by_name = order.user.first_name
        if order.account_id:
            order.account_name = order.account.name
        if order.shop_id:
            order.shop_name = order.shop.name
    response.headers["Content-Range"] = header_range
    return orders


@router.get(
    "/shop/{shop_id}/pending",
    response_model=List[OrderSchema],
    summary="List pending orders for a shop",
    description="Returns all orders with status `pending` for the given shop. These are orders awaiting fulfilment.",
)
def show_all_pending_orders_per_shop(
    shop_id: UUID,
    response: Response,
    common: dict = Depends(common_parameters),
    current_user: CustomCognitoToken = Depends(auth_required),
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
    summary="List completed orders for a shop",
    description="Returns all orders with status `complete` or `cancelled` for the given shop. Used for order history and reporting.",
)
def show_all_complete_orders_per_shop(
    shop_id: UUID,
    response: Response,
    common: dict = Depends(common_parameters),
    current_user: CustomCognitoToken = Depends(auth_required),
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
        if (order.status == "complete" or order.status == "cancelled") and order.completed_by:
            order.completed_by_name = order.user.first_name
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

    if (order.status == "complete" or order.status == "cancelled") and order.completed_by:
        order.completed_by_name = order.user.first_name
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
    "/",
    response_model=OrderCreated,
    status_code=HTTPStatus.CREATED,
    summary="Create order",
    description=(
        "Submit a new customer order. The caller's IP is validated against the shop's allowlist. "
        "If stock tracking is enabled the product availability is verified before the order is created. "
        "A Stripe customer is auto-created for new account names when the shop has Stripe configured."
    ),
)
def create(request: Request, data: OrderCreate = Body(...)) -> OrderCreated:
    logger.info("Saving order", data=data)

    if data.customer_order_id:
        del data.customer_order_id
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

    # Availability check
    if shop.config["toggles"]["enable_stock_on_products"]:
        for order_product in data.order_info:
            product = product_crud.get_id_by_shop_id(shop_id, order_product.product_id)
            if not product:
                raise_status(HTTPStatus.NOT_FOUND, f"Product '{order_product.product_name}' not found")
            if product.stock < order_product.quantity:
                raise_status(HTTPStatus.BAD_REQUEST, f"Not enough stock for product '{order_product.product_name}'")

    data.customer_order_id = order_crud.get_newest_order_id(shop_id=shop_id)

    if data.status in ["complete", "cancelled"] and not data.completed_at:
        data.completed_at = datetime.now()

    if data.status not in ["pending", "complete", "cancelled"]:
        data.status = "pending"

    if str(data.account_id) == "0999fbcd-a72b-4cc2-abbe-41ccd466cdaf":
        # Test table -> flag it complete
        data.status = "complete"
        data.completed_at = datetime.now()

    # Compute shipping fee from shop config and recompute the persisted total
    # server-side so it can't be manipulated by the client.
    shipping_calc = compute_shipping_for_cart(data.order_info, shop)
    data.shipping_fee_inc_btw = shipping_calc.fee_inc_btw if shipping_calc is not None else None
    items_total = sum((item.price * item.quantity for item in data.order_info), Decimal("0"))
    data.total = quantize_money(items_total + (data.shipping_fee_inc_btw or Decimal("0")))

    order = order_crud.create(obj_in=data)

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
    item_in: OrderBase,
    # current_user: CustomCognitoToken = Depends(auth_required)
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

    if (
        "complete" not in order.status
        and item_in.status
        and (item_in.status == "complete" or item_in.status == "cancelled")
        and not order.completed_at
    ):
        order.completed_at = datetime.now()
        # order.completed_by = current_user.id

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

            new_product = ProductUpdate(
                shop_id=product.shop_id,
                category_id=product.category_id,
                max_one=product.max_one,
                shippable=product.shippable,
                featured=product.featured,
                new_product=product.new_product,
                tax_category=product.tax_category,
                stock=product.stock - order_product["quantity"],
                translation=product.translation,
                image_1=product.image_1,
                image_2=product.image_2,
                image_3=product.image_3,
                image_4=product.image_4,
                image_5=product.image_5,
                image_6=product.image_6,
            )
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
    summary="Full order update",
    description="Fully replace an order's fields. Requires authentication. Also sets `completed_at` when transitioning to `complete` or `cancelled`.",
)
def update(
    *, order_id: UUID, item_in: OrderUpdate, current_user: CustomCognitoToken = Depends(auth_required)
) -> OrderUpdated:
    order = order_crud.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if item_in.status and (item_in.status == "complete" or item_in.status == "cancelled") and not order.completed_at:
        order.completed_at = datetime.now()
        order.completed_by = None

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
