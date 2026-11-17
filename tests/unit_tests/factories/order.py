from uuid import UUID

import structlog

from server.db import db
from server.db.models import OrderTable

logger = structlog.getLogger(__name__)


def make_shipping_address() -> dict:
    """Synthetic Stripe shipping payload, freshly allocated for each test."""
    return {
        "name": "Alex Example",
        "phone": "+31612345678",
        "address": {
            "line1": "Example street 1",
            "line2": "Unit 2",
            "postal_code": "1234 AB",
            "city": "Amsterdam",
            "state": None,
            "country": "NL",
        },
    }


def make_pending_order(
    shop_id: UUID,
    account_id: UUID,
    product_id_1: UUID,
    product_id_2: UUID,
    customer_order_id=1,
    total=2.0,
):
    order_info = [
        {
            "description": "Test Order Description",
            "product_name": "Test Product",
            "price": 1.0,
            "quantity": 1,
            "product_id": product_id_1,
        },
        {
            "description": "Test Order Description",
            "product_name": "Test Product 2",
            "price": 1.0,
            "quantity": 1,
            "product_id": product_id_2,
        },
    ]
    order = OrderTable(
        shop_id=shop_id,
        account_id=account_id,
        customer_order_id=customer_order_id,
        order_info=order_info,
        total=total,
    )
    db.session.add(order)
    db.session.commit()
    return order
