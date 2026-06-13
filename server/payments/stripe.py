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
"""Stripe payment provider (PaymentIntents, in-page confirmation flow).

Credentials come from the legacy per-shop columns ``stripe_secret_key`` /
``stripe_public_key`` (kept for backwards compatibility). The optional
webhook signing secret lives in ``shop.payment_config["stripe"]["webhook_secret"]``.
"""

from decimal import Decimal
from typing import Optional

import stripe as stripe_sdk
import structlog
from fastapi import Request

from server.crud.crud_account import account_crud
from server.db.models import OrderTable, PaymentTable, ShopTable
from server.payments.base import (
    PaymentEvent,
    PaymentProvider,
    PaymentProviderNotConfigured,
    PaymentSession,
    PaymentStatus,
    PaymentWebhookInvalid,
)
from server.services import stripe_client
from server.services.stripe_client import StripeCustomerMissing, StripeNotConfigured

logger = structlog.get_logger(__name__)

# https://docs.stripe.com/payments/paymentintents/lifecycle
STRIPE_INTENT_STATUS_MAP = {
    "requires_payment_method": PaymentStatus.PENDING,
    "requires_confirmation": PaymentStatus.PENDING,
    "requires_action": PaymentStatus.PENDING,
    "processing": PaymentStatus.PENDING,
    "requires_capture": PaymentStatus.PENDING,
    "succeeded": PaymentStatus.PAID,
    "canceled": PaymentStatus.CANCELED,
}

STRIPE_EVENT_STATUS_MAP = {
    "payment_intent.succeeded": PaymentStatus.PAID,
    "payment_intent.payment_failed": PaymentStatus.FAILED,
    "payment_intent.canceled": PaymentStatus.CANCELED,
}


class StripeProvider(PaymentProvider):
    id = "stripe"

    def _configure(self, shop: ShopTable) -> None:
        try:
            stripe_client.configure_for_shop(shop)
        except StripeNotConfigured as e:
            raise PaymentProviderNotConfigured(str(e)) from e

    def create_payment(
        self, *, shop: ShopTable, order: OrderTable, payment: PaymentTable, return_url: str
    ) -> PaymentSession:
        self._configure(shop)

        kwargs = {
            "amount": int(Decimal(payment.amount) * 100),
            "currency": payment.currency.lower(),
            "payment_method_types": ["card", "ideal"],
            "metadata": {"order_id": str(order.id), "payment_id": str(payment.id)},
        }
        account = account_crud.get(order.account_id) if order.account_id else None
        try:
            kwargs["customer"] = stripe_client.get_customer_id(account)
            kwargs["setup_future_usage"] = "off_session"
        except StripeCustomerMissing:
            # Guest checkout / account never linked to Stripe: a one-off
            # intent without a customer works fine.
            pass

        intent = stripe_sdk.PaymentIntent.create(**kwargs)
        return PaymentSession(
            provider_payment_id=intent["id"],
            status=STRIPE_INTENT_STATUS_MAP.get(intent["status"], PaymentStatus.PENDING),
            flow="client_confirmation",
            client_secret=intent["client_secret"],
            publishable_key=shop.stripe_public_key,
            raw={"id": intent["id"], "status": intent["status"]},
        )

    async def handle_webhook(self, *, shop: ShopTable, request: Request) -> Optional[PaymentEvent]:
        webhook_secret = ((shop.payment_config or {}).get("stripe") or {}).get("webhook_secret")
        if not webhook_secret:
            raise PaymentProviderNotConfigured(
                f"Shop {shop.id} has no Stripe webhook secret in payment_config['stripe']['webhook_secret']"
            )

        payload = await request.body()
        signature = request.headers.get("stripe-signature", "")
        try:
            event = stripe_sdk.Webhook.construct_event(payload, signature, webhook_secret)
        except (ValueError, stripe_sdk.error.SignatureVerificationError) as e:
            raise PaymentWebhookInvalid(str(e)) from e

        status = STRIPE_EVENT_STATUS_MAP.get(event["type"])
        if status is None:
            return None

        intent = event["data"]["object"]
        return PaymentEvent(
            provider_payment_id=intent["id"],
            status=status,
            raw={"id": intent["id"], "status": intent["status"], "event_type": event["type"]},
        )

    def get_status(self, *, shop: ShopTable, provider_payment_id: str) -> PaymentEvent:
        self._configure(shop)
        intent = stripe_sdk.PaymentIntent.retrieve(provider_payment_id)
        return PaymentEvent(
            provider_payment_id=provider_payment_id,
            status=STRIPE_INTENT_STATUS_MAP.get(intent["status"], PaymentStatus.PENDING),
            raw={"id": intent["id"], "status": intent["status"]},
        )
