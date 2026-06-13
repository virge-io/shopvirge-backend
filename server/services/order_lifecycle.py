# Copyright 2026 René Dohmen <acidjunk@gmail.com>
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Order completion lifecycle, shared by order endpoints and payment webhooks.

Completing an order has side effects (stock deduction, Discord ping,
confirmation emails, cache invalidation) that historically lived inline in the
orders PATCH endpoint. Payment webhooks need the exact same behavior, so the
logic lives here. ``complete_order`` is idempotent: payment providers retry
webhooks, and during the migration period a legacy frontend may still PATCH
the order to complete — whichever arrives second is a no-op.
"""

from datetime import datetime
from typing import Optional

import structlog

from server.crud.crud_account import account_crud
from server.crud.crud_product import product_crud
from server.db import db
from server.db.models import Account, OrderTable, ShopTable
from server.mail import send_order_confirmation_emails
from server.schemas import ProductUpdate
from server.settings import mail_settings
from server.utils.discord.discord import post_discord_order_complete

logger = structlog.get_logger(__name__)


def deduct_stock_for_order(order: OrderTable, shop: ShopTable) -> None:
    """Decrease product stock for every order line, if the shop tracks stock."""
    # Older shop rows may carry a JSON string or empty config instead of a dict.
    config = shop.config if isinstance(shop.config, dict) else {}
    toggles = config.get("toggles") or {}
    if not toggles.get("enable_stock_on_products"):
        return

    for order_product in order.order_info:
        product = product_crud.get_id_by_shop_id(shop.id, order_product["product_id"])

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


def notify_order_complete(order: OrderTable, shop: ShopTable, account: Optional[Account]) -> None:
    """Best-effort notifications for a completed order: Discord + emails.

    Failures are logged, never raised — a flaky Discord webhook or SMTP server
    must not undo a successful payment.
    """
    if shop.discord_webhook is not None and account:
        try:
            post_discord_order_complete(
                f"New order from {account.name}",
                botname=shop.name,
                webhook=shop.discord_webhook,
                order=order,
                email=account.name,
            )
        except Exception as e:
            logger.error("Failed to post to Discord: ", error=str(e))

    if mail_settings.SHOP_MAIL_ENABLED and account:
        try:
            send_order_confirmation_emails(order=order, shop=shop, account=account)
        except Exception as e:
            logger.error("Failed to send order confirmation email", error=str(e))


def complete_order(order: OrderTable, shop: ShopTable) -> OrderTable:
    """Idempotently transition an order to ``complete`` and run all side effects.

    Returns the (possibly unchanged) order. Safe to call multiple times: an
    order that is already complete is returned as-is, so retried webhooks and
    a racing legacy status PATCH cannot double-deduct stock or double-mail.
    """
    if order.status == "complete":
        logger.info("Order already complete, skipping", order_id=str(order.id))
        return order

    order.status = "complete"
    if not order.completed_at:
        order.completed_at = datetime.now()
    db.session.add(order)
    db.session.commit()

    deduct_stock_for_order(order, shop)

    account = account_crud.get(order.account_id) if order.account_id else None
    notify_order_complete(order, shop, account)

    # Imported here: server.api.helpers pulls in API-layer modules that in
    # turn import services, so a module-level import would be circular.
    from server.api.helpers import invalidateCompletedOrdersCache

    invalidateCompletedOrdersCache(order.id)
    return order
