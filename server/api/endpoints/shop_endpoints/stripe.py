from http import HTTPStatus
from typing import Any
from uuid import UUID

import stripe
import structlog
from fastapi import APIRouter, HTTPException

from server.api.error_handling import raise_status
from server.crud.crud_shop import shop_crud
from server.db import db
from server.db.models import Account, OrderTable
from server.schemas.base import quantize_money
from server.services import stripe_client

router = APIRouter()
logger = structlog.get_logger(__name__)


def get_stripe_customer(account_id: UUID, shop_id: UUID):
    account = Account.query.filter(Account.id == account_id, Account.shop_id == shop_id).first()
    return stripe_client.get_customer_id(account)


def replace_missing_customer(account_id: UUID, shop_id: UUID) -> str:
    account = Account.query.filter(Account.id == account_id, Account.shop_id == shop_id).first()
    if not account:
        raise_status(HTTPStatus.NOT_FOUND, f"Account with id {account_id} not found")

    customer = stripe.Customer.create(email=account.name)
    customer_id = str(customer.id)
    account.details = {**(account.details or {}), "stripe_customer_id": customer_id}
    db.session.add(account)
    db.session.commit()
    return customer_id


def get_stripe_prices(order_info: list[dict[str, Any]], yearly: bool) -> list[dict[str, Any]]:
    lookup_keys = [f"{'yearly' if yearly else 'monthly'}-{item['product_id']}" for item in order_info]

    prices = stripe.Price.list(lookup_keys=lookup_keys)
    prices_by_lookup_key = {price.lookup_key: price.id for price in prices.data}
    return [
        {
            "price": prices_by_lookup_key[f"{'yearly' if yearly else 'monthly'}-{item['product_id']}"],
            "quantity": item["quantity"],
        }
        for item in order_info
    ]


@router.post(
    "/",
    status_code=HTTPStatus.CREATED,
    summary="Create payment intent",
    description=(
        "Create a Stripe PaymentIntent for a one-time purchase. "
        "Uses the shop's own `stripe_secret_key` and the total saved on the order. "
        "Returns a `clientSecret` to complete the payment on the frontend."
    ),
)
def create_payment_intent(shop_id: UUID, order_id: UUID) -> dict[str, str]:
    order = OrderTable.query.filter(OrderTable.id == order_id, OrderTable.shop_id == shop_id).first()
    if not order:
        raise_status(HTTPStatus.NOT_FOUND, f"Order with id {order_id} not found")
    if order.total is None or order.total <= 0:
        raise_status(HTTPStatus.UNPROCESSABLE_ENTITY, f"Order with id {order_id} has no payable total")
    if any(item.get("plan") not in {None, "onetime"} for item in order.order_info):
        raise_status(HTTPStatus.UNPROCESSABLE_ENTITY, "Recurring orders must create a subscription")

    try:
        shop = shop_crud.get(shop_id)
        stripe_client.configure_for_shop(shop)
        customer_id = get_stripe_customer(order.account_id, shop_id)

        intent_args = {
            "amount": int(quantize_money(order.total) * 100),
            "currency": "eur",
            "payment_method_types": ["card", "ideal"],
            "setup_future_usage": "off_session",
            "customer": customer_id,
        }
        try:
            intent = stripe.PaymentIntent.create(**intent_args)
        except stripe.error.InvalidRequestError as exc:
            if not stripe_client.is_missing_customer_error(exc):
                raise
            customer_id = replace_missing_customer(order.account_id, shop_id)
            logger.info("Replaced missing Stripe customer", order_id=str(order_id), customer_id=customer_id)
            intent = stripe.PaymentIntent.create(**(intent_args | {"customer": customer_id}))
        return {"clientSecret": str(intent["client_secret"])}
    except Exception as exc:
        logger.exception("Failed to create payment intent", order_id=str(order_id))
        raise HTTPException(HTTPStatus.BAD_GATEWAY, "Unable to create payment intent") from exc


@router.post(
    "/subscription",
    status_code=HTTPStatus.CREATED,
    summary="Create subscription",
    description=(
        "Create a Stripe Subscription using products and plan stored on an order. Price lookup keys are resolved as "
        "`monthly-<product_id>` or `yearly-<product_id>`. "
        "Returns `clientSecret` and `subscriptionId` to confirm payment on the frontend."
    ),
)
def create_subscription_intent(shop_id: UUID, order_id: UUID) -> dict[str, str]:
    order = OrderTable.query.filter(OrderTable.id == order_id, OrderTable.shop_id == shop_id).first()
    if not order:
        raise_status(HTTPStatus.NOT_FOUND, f"Order with id {order_id} not found")

    plans = {item.get("plan") for item in order.order_info}
    if len(plans) == 1 and plans <= {"monthly", "yearly"}:
        yearly = plans == {"yearly"}
    else:
        raise_status(HTTPStatus.UNPROCESSABLE_ENTITY, "Subscriptions require one recurring plan for every order line")

    try:
        shop = shop_crud.get(shop_id)
        stripe_client.configure_for_shop(shop)
        customer_id = get_stripe_customer(order.account_id, shop_id)
        prices = get_stripe_prices(order.order_info, yearly)

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
            "clientSecret": str(subscription.latest_invoice.payment_intent.client_secret),
            "subscriptionId": str(subscription.id),
        }
    except Exception as exc:
        logger.exception("Failed to create subscription", order_id=str(order_id))
        raise HTTPException(HTTPStatus.BAD_GATEWAY, "Unable to create subscription") from exc


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
