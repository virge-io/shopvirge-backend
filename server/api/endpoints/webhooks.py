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
"""Public payment webhooks, one route per (provider, shop).

Unauthenticated by necessity — PSPs call these. Safety comes from each
provider's own verification: Mollie events are confirmed by fetching the
payment back from the Mollie API; Stripe events must carry a valid signature.
Order completion happens here (via ``apply_payment_event``), making the
backend — not the frontend — the authority on whether an order was paid.
"""

from http import HTTPStatus
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Request

from server.crud.crud_payment import payment_crud
from server.crud.crud_shop import shop_crud
from server.payments.base import PaymentProviderNotConfigured, PaymentWebhookInvalid
from server.payments.processing import apply_payment_event
from server.payments.registry import get_provider

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.post("/{provider_id}/{shop_id}")
async def payment_webhook(provider_id: str, shop_id: UUID, request: Request) -> dict:
    shop = shop_crud.get(shop_id)
    if not shop:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Shop not found")

    try:
        provider = get_provider(shop, provider_id)
    except PaymentProviderNotConfigured:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Unknown payment provider")

    try:
        event = await provider.handle_webhook(shop=shop, request=request)
    except PaymentWebhookInvalid as e:
        logger.warning("Rejected payment webhook", provider=provider_id, shop_id=str(shop_id), error=str(e))
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="Invalid webhook")
    except PaymentProviderNotConfigured as e:
        logger.warning("Webhook for unconfigured provider", provider=provider_id, shop_id=str(shop_id), error=str(e))
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))

    if event is None:
        # Verified but not something we act on (e.g. unhandled Stripe event type).
        return {"status": "ignored"}

    payment = payment_crud.get_by_provider_payment_id(shop_id=shop_id, provider_payment_id=event.provider_payment_id)
    if not payment:
        # Unknown payment id: 404 so the PSP retries later (or gives up) —
        # this can happen if a webhook outraces our own commit.
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Payment not found")

    apply_payment_event(payment=payment, event=event, shop=shop)
    return {"status": "ok"}
