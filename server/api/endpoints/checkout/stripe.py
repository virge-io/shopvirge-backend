from hashlib import sha256
from http import HTTPStatus
from typing import Any
from uuid import UUID

import stripe
import structlog
from fastapi import APIRouter, HTTPException

from server.api.error_handling import raise_status
from server.crud.crud_shop import shop_crud
from server.db import db
from server.db.models import Account, OrderTable, ShopTable
from server.schemas.base import quantize_money
from server.services import stripe_client

router = APIRouter()
logger = structlog.get_logger(__name__)


def _resume_checkout(order: OrderTable, shop: ShopTable, *, subscription: bool = False) -> dict[str, str] | None:
    """Reuse an already-linked payment, even after Stripe's idempotency-key retention expires."""
    if not order.stripe_payment_intent_id:
        return None
    order_id = str(order.id)
    shop_id = str(shop.id)
    payment_intent_id = order.stripe_payment_intent_id
    api_key = shop.stripe_secret_key
    db.release_connection()
    intent = stripe.PaymentIntent.retrieve(
        payment_intent_id, api_key=api_key, **({"expand": ["invoice.subscription"]} if subscription else {})
    )
    result = {"clientSecret": str(intent["client_secret"])}
    if subscription:
        linked_subscription = intent["invoice"]["subscription"]
        result["subscriptionId"] = (
            linked_subscription if isinstance(linked_subscription, str) else str(linked_subscription["id"])
        )
    logger.info(
        "Resumed checkout with linked payment intent",
        order_id=order_id,
        shop_id=shop_id,
        payment_intent_id=payment_intent_id,
        subscription_id=result.get("subscriptionId"),
    )
    return result


def _save_payment_intent(order_id: UUID, payment_intent_id: str, customer_id: str) -> None:
    # The remote call ran without a DB connection. Re-lock before linking so an
    # overlapping completion cannot have its payment or delivery snapshot replaced.
    order = OrderTable.query.filter(OrderTable.id == order_id).with_for_update().populate_existing().one()
    if order.status != "pending":
        raise HTTPException(HTTPStatus.CONFLICT, "Only pending orders can create payments")
    if order.stripe_payment_intent_id and order.stripe_payment_intent_id != payment_intent_id:
        raise HTTPException(HTTPStatus.CONFLICT, "A payment is already linked; reload checkout")
    if order.stripe_payment_customer_id and order.stripe_payment_customer_id != customer_id:
        raise HTTPException(HTTPStatus.CONFLICT, "A different payment customer is already linked")
    order.stripe_payment_customer_id = customer_id
    order.stripe_payment_intent_id = payment_intent_id
    db.session.commit()


def get_stripe_customer(account_id: UUID, shop_id: UUID):
    account = Account.query.filter(Account.id == account_id, Account.shop_id == shop_id).first()
    return stripe_client.get_customer_id(account)


def replace_missing_customer(account_id: UUID, shop_id: UUID, failed_customer_id: str, *, api_key: str) -> str:
    """Resolve a missing customer without overwriting a concurrent replacement.

    Stripe idempotency coordinates remote creation across workers. A fresh locked
    read then selects the canonical local winner; no DB lock spans network I/O.
    """
    account = Account.query.filter(Account.id == account_id, Account.shop_id == shop_id).populate_existing().first()
    if not account:
        raise_status(HTTPStatus.NOT_FOUND, f"Account with id {account_id} not found")
    current_id = stripe_client.get_customer_id(account)
    if current_id != failed_customer_id:
        db.release_connection()
        return current_id
    email = account.name
    identity = f"{shop_id}:{account_id}:{failed_customer_id}".encode()
    idempotency_key = f"replace-customer-{sha256(identity).hexdigest()}"
    db.release_connection()
    customer = stripe.Customer.create(email=email, api_key=api_key, idempotency_key=idempotency_key)
    replacement_id = str(customer.id)
    account = (
        Account.query.filter(Account.id == account_id, Account.shop_id == shop_id)
        .with_for_update()
        .populate_existing()
        .first()
    )
    if not account:
        raise_status(HTTPStatus.NOT_FOUND, f"Account with id {account_id} not found")
    current_id = stripe_client.get_customer_id(account)
    if current_id == failed_customer_id:
        account.details = {**(account.details or {}), "stripe_customer_id": replacement_id}
        current_id = replacement_id
    db.session.commit()
    return current_id


def get_stripe_prices(
    order_info: list[dict[str, Any]], yearly: bool, *, api_key: str | None = None
) -> list[dict[str, Any]]:
    lookup_keys = [f"{'yearly' if yearly else 'monthly'}-{item['product_id']}" for item in order_info]

    prices = stripe.Price.list(lookup_keys=lookup_keys, api_key=api_key)
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
    if order.status != "pending":
        raise_status(HTTPStatus.CONFLICT, "Only pending orders can create payments")
    if order.total is None or order.total <= 0:
        raise_status(HTTPStatus.UNPROCESSABLE_ENTITY, f"Order with id {order_id} has no payable total")
    if any(item.get("plan") not in {None, "onetime"} for item in order.order_info):
        raise_status(HTTPStatus.UNPROCESSABLE_ENTITY, "Recurring orders must create a subscription")

    try:
        shop = shop_crud.get(shop_id)
        stripe_client.configure_for_shop(shop)
        api_key = shop.stripe_secret_key
        existing = _resume_checkout(order, shop)
        if existing:
            return existing
        account_id = order.account_id
        customer_id = get_stripe_customer(account_id, shop_id)

        intent_args = {
            "api_key": api_key,
            "amount": int(quantize_money(order.total) * 100),
            "currency": "eur",
            "payment_method_types": ["card", "ideal"],
            "setup_future_usage": "off_session",
            "customer": customer_id,
            "metadata": {"order_id": str(order_id), "shop_id": str(shop_id)},
            "idempotency_key": f"order-{order_id}-{customer_id}",
        }
        # Everything Stripe needs is in plain values now: give the pooled connection back for the remote call.
        db.release_connection()
        try:
            intent = stripe.PaymentIntent.create(**intent_args)
        except stripe.error.InvalidRequestError as exc:
            if not stripe_client.is_missing_customer_error(exc):
                raise
            customer_id = replace_missing_customer(account_id, shop_id, customer_id, api_key=api_key)
            logger.warning(
                "Replaced missing Stripe customer",
                order_id=str(order_id),
                shop_id=str(shop_id),
                customer_id=customer_id,
            )
            db.release_connection()
            intent = stripe.PaymentIntent.create(
                **(intent_args | {"customer": customer_id, "idempotency_key": f"order-{order_id}-{customer_id}"})
            )
        _save_payment_intent(order_id, str(intent["id"]), customer_id)
        logger.info(
            "PaymentIntent created successfully",
            order_id=str(order_id),
            shop_id=str(shop_id),
            customer_id=customer_id,
            payment_intent_id=str(intent["id"]),
            amount=intent_args["amount"],
        )
        return {"clientSecret": str(intent["client_secret"])}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to create payment intent", order_id=str(order_id), shop_id=str(shop_id))
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
    if order.status != "pending":
        raise_status(HTTPStatus.CONFLICT, "Only pending orders can create payments")

    plans = {item.get("plan") for item in order.order_info}
    if len(plans) == 1 and plans <= {"monthly", "yearly"}:
        yearly = plans == {"yearly"}
    else:
        raise_status(HTTPStatus.UNPROCESSABLE_ENTITY, "Subscriptions require one recurring plan for every order line")

    try:
        shop = shop_crud.get(shop_id)
        stripe_client.configure_for_shop(shop)
        api_key = shop.stripe_secret_key
        existing = _resume_checkout(order, shop, subscription=True)
        if existing:
            return existing
        account_id = order.account_id
        order_info = order.order_info
        customer_id = get_stripe_customer(account_id, shop_id)
        # Two remote calls follow; nothing below reads the ORM objects, so return the pooled connection first.
        db.release_connection()
        prices = get_stripe_prices(order_info, yearly, api_key=api_key)

        subscription_args = {
            "api_key": api_key,
            "items": prices,
            "payment_behavior": "default_incomplete",
            "payment_settings": {
                "payment_method_types": ["card", "paypal"],
                "save_default_payment_method": "on_subscription",
            },
            "customer": customer_id,
            "expand": ["latest_invoice.payment_intent"],
            "metadata": {"order_id": str(order_id), "shop_id": str(shop_id)},
            "idempotency_key": f"subscription-order-{order_id}-{customer_id}",
        }
        try:
            subscription = stripe.Subscription.create(**subscription_args)
        except stripe.error.InvalidRequestError as exc:
            if not stripe_client.is_missing_customer_error(exc):
                raise
            customer_id = replace_missing_customer(account_id, shop_id, customer_id, api_key=api_key)
            logger.warning(
                "Replaced missing Stripe customer",
                order_id=str(order_id),
                shop_id=str(shop_id),
                customer_id=customer_id,
            )
            db.release_connection()
            subscription = stripe.Subscription.create(
                **(
                    subscription_args
                    | {
                        "customer": customer_id,
                        "idempotency_key": f"subscription-order-{order_id}-{customer_id}",
                    }
                )
            )
        _save_payment_intent(order_id, str(subscription.latest_invoice.payment_intent.id), customer_id)
        logger.info(
            "Subscription created successfully",
            order_id=str(order_id),
            shop_id=str(shop_id),
            subscription_id=str(subscription.id),
            customer_id=customer_id,
            payment_intent_id=str(subscription.latest_invoice.payment_intent.id),
        )
        return {
            "clientSecret": str(subscription.latest_invoice.payment_intent.client_secret),
            "subscriptionId": str(subscription.id),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to create subscription", order_id=str(order_id), shop_id=str(shop_id))
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
        db.release_connection()
        stripe.Subscription.cancel(subscription_id)
        logger.info("Subscription cancelled successfully", subscription_id=subscription_id, shop_id=str(shop_id))
        return 204
    except Exception as e:
        logger.exception("Failed to cancel subscription", subscription_id=subscription_id, shop_id=str(shop_id))
        return e
