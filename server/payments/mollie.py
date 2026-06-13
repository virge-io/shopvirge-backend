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
"""Mollie payment provider (hosted checkout, redirect flow).

Shop config lives in ``shop.payment_config["mollie"]``:

    {"mollie": {"api_key": "live_..."}}

Mollie webhooks are unsigned by design: the webhook body only carries the
payment id, and verification consists of fetching that payment back from the
Mollie API with the shop's key and trusting only the API response.
"""

from decimal import Decimal
from typing import Optional

import structlog
from fastapi import Request
from mollie.api.client import Client

from server.db.models import OrderTable, PaymentTable, ShopTable
from server.payments.base import (
    PaymentEvent,
    PaymentProvider,
    PaymentProviderNotConfigured,
    PaymentSession,
    PaymentStatus,
    PaymentWebhookInvalid,
)
from server.settings import app_settings

logger = structlog.get_logger(__name__)

# https://docs.mollie.com/payments/status-changes
MOLLIE_STATUS_MAP = {
    "open": PaymentStatus.PENDING,
    "pending": PaymentStatus.PENDING,
    "authorized": PaymentStatus.PENDING,
    "paid": PaymentStatus.PAID,
    "failed": PaymentStatus.FAILED,
    "canceled": PaymentStatus.CANCELED,
    "expired": PaymentStatus.EXPIRED,
}


class MollieProvider(PaymentProvider):
    id = "mollie"

    def _get_client(self, shop: ShopTable) -> Client:
        api_key = ((shop.payment_config or {}).get("mollie") or {}).get("api_key")
        if not api_key:
            raise PaymentProviderNotConfigured(
                f"Shop {shop.id} has no Mollie api_key in payment_config['mollie']['api_key']"
            )
        client = Client()
        client.set_api_key(api_key)
        return client

    def _webhook_url(self, shop: ShopTable) -> Optional[str]:
        base = app_settings.PUBLIC_BASE_URL.rstrip("/")
        if "localhost" in base or "127.0.0.1" in base:
            # Mollie refuses non-public webhook URLs. In local dev the
            # poll-time sync in GET /payments/{id} keeps statuses moving.
            return None
        return f"{base}/webhooks/payments/{self.id}/{shop.id}"

    def create_payment(
        self, *, shop: ShopTable, order: OrderTable, payment: PaymentTable, return_url: str
    ) -> PaymentSession:
        client = self._get_client(shop)
        payload = {
            "amount": {"currency": payment.currency, "value": f"{Decimal(payment.amount):.2f}"},
            "description": f"Order #{order.customer_order_id} - {shop.name}",
            "redirectUrl": return_url,
            "metadata": {"order_id": str(order.id), "payment_id": str(payment.id)},
        }
        webhook_url = self._webhook_url(shop)
        if webhook_url:
            payload["webhookUrl"] = webhook_url

        mollie_payment = client.payments.create(payload)
        return PaymentSession(
            provider_payment_id=mollie_payment.id,
            status=MOLLIE_STATUS_MAP.get(mollie_payment.status, PaymentStatus.PENDING),
            flow="redirect",
            redirect_url=mollie_payment.checkout_url,
            raw=dict(mollie_payment),
        )

    async def handle_webhook(self, *, shop: ShopTable, request: Request) -> Optional[PaymentEvent]:
        form = await request.form()
        provider_payment_id = form.get("id")
        if not provider_payment_id or not str(provider_payment_id).startswith("tr_"):
            raise PaymentWebhookInvalid("Mollie webhook without a payment id")
        # Fetch-back is the verification — never trust the webhook body itself.
        return self.get_status(shop=shop, provider_payment_id=str(provider_payment_id))

    def get_status(self, *, shop: ShopTable, provider_payment_id: str) -> PaymentEvent:
        client = self._get_client(shop)
        mollie_payment = client.payments.get(provider_payment_id)
        return PaymentEvent(
            provider_payment_id=provider_payment_id,
            status=MOLLIE_STATUS_MAP.get(mollie_payment.status, PaymentStatus.PENDING),
            raw=dict(mollie_payment),
        )
