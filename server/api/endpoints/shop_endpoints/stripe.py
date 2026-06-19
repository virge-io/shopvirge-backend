from enum import Enum
from http import HTTPStatus
from uuid import UUID

import stripe
import structlog
from fastapi import APIRouter

from server.crud.crud_shop import shop_crud
from server.db.models import Account
from server.services import stripe_client

router = APIRouter()
logger = structlog.get_logger(__name__)


def get_stripe_customer(account_id: UUID, shop_id: UUID):
    account = Account.query.filter(Account.id == account_id, Account.shop_id == shop_id).first()
    return stripe_client.get_customer_id(account)


def get_stripe_prices(product_ids: list[UUID], yearly: bool):
    lookup_keys = []
    for id in product_ids:
        if yearly:
            lookup_keys.append(f"yearly-{id}")
        else:
            lookup_keys.append(f"monthly-{id}")

    prices = stripe.Price.list(lookup_keys=lookup_keys)

    items = []
    for price in prices.data:
        items.append({"price": price.id})

    return items


@router.post(
    "/",
    status_code=HTTPStatus.CREATED,
    summary="Create payment intent",
    description=(
        "Create a Stripe PaymentIntent for a one-time purchase. "
        "Uses the shop's own `stripe_secret_key`. The `price` is in euro cents. "
        "Returns a `clientSecret` to complete the payment on the frontend."
    ),
)
def create_payment_intent(shop_id: UUID, price: int, account_id: UUID):
    try:
        shop = shop_crud.get(shop_id)
        stripe_client.configure_for_shop(shop)
        customer_id = get_stripe_customer(account_id, shop_id)

        intent = stripe.PaymentIntent.create(
            amount=price,
            currency="eur",
            payment_method_types=["card", "ideal"],
            setup_future_usage="off_session",
            customer=customer_id,
        )
        return {"clientSecret": intent["client_secret"]}
    except Exception as e:
        return e


@router.post(
    "/subscription",
    status_code=HTTPStatus.CREATED,
    summary="Create subscription",
    description=(
        "Create a Stripe Subscription for one or more products. Price lookup keys are resolved as "
        "`monthly-<product_id>` or `yearly-<product_id>`. "
        "Returns `clientSecret` and `subscriptionId` to confirm payment on the frontend."
    ),
)
def create_subscription_intent(shop_id: UUID, product_ids: list[UUID], account_id: UUID, yearly: bool = False):
    try:
        shop = shop_crud.get(shop_id)
        stripe_client.configure_for_shop(shop)
        customer_id = get_stripe_customer(account_id, shop_id)
        prices = get_stripe_prices(product_ids, yearly)

        subscription = stripe.Subscription.create(
            items=prices,
            payment_behavior="default_incomplete",
            payment_settings={
                "payment_method_types": ["card", "paypal"],
                "save_default_payment_method": "on_subscription",
            },
            customer=customer_id,
            expand=["latest_invoice.payment_intent"],
        )
        return {
            "clientSecret": subscription.latest_invoice.payment_intent.client_secret,
            "subscriptionId": subscription.id,
        }
    except Exception as e:
        return e


@router.delete(
    "/subscription/{subscription_id}",
    response_model=None,
    status_code=HTTPStatus.NO_CONTENT,
    summary="Cancel subscription",
    description="Immediately cancel a Stripe Subscription. Uses the shop's `stripe_secret_key`.",
)
def cancel_subscription(shop_id: UUID, subscription_id: str):
    try:
        shop = shop_crud.get(shop_id)
        stripe_client.configure_for_shop(shop)
        stripe.Subscription.cancel(subscription_id)

        return 204
    except Exception as e:
        return e
