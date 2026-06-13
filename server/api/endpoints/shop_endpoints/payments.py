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
"""Provider-agnostic checkout payments.

The frontend never talks to a PSP-specific endpoint: it POSTs an order id
here, gets back a :class:`PaymentSessionSchema` telling it what to do
(redirect vs in-page confirmation), and polls the GET endpoint after the
customer returns. Order completion itself is driven by webhooks (or the
poll-time sync fallback) — never by the frontend.
"""

from http import HTTPStatus
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.param_functions import Body

from server.api.error_handling import raise_status
from server.crud.crud_order import order_crud
from server.crud.crud_payment import payment_crud
from server.crud.crud_shop import shop_crud
from server.db import db
from server.payments.base import PaymentProviderError, PaymentProviderNotConfigured, PaymentStatus
from server.payments.processing import apply_payment_event
from server.payments.registry import get_provider
from server.schemas.payment import PaymentCreate, PaymentSessionSchema, PaymentStatusSchema

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.post("/", response_model=PaymentSessionSchema, status_code=HTTPStatus.CREATED)
def create_payment(shop_id: UUID, data: PaymentCreate = Body(...)) -> PaymentSessionSchema:
    shop = shop_crud.get(shop_id)
    if not shop:
        raise_status(HTTPStatus.NOT_FOUND, f"Shop with id {shop_id} not found")

    order = order_crud.get(data.order_id)
    if not order or order.shop_id != shop_id:
        raise_status(HTTPStatus.NOT_FOUND, f"Order with id {data.order_id} not found")
    if order.status != "pending":
        raise_status(HTTPStatus.CONFLICT, f"ORDER_NOT_PAYABLE: order status is '{order.status}'")

    try:
        provider = get_provider(shop)
    except PaymentProviderNotConfigured as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))

    payment = payment_crud.create_for_order(order=order, provider=provider.id)
    try:
        session = provider.create_payment(shop=shop, order=order, payment=payment, return_url=data.return_url)
    except PaymentProviderNotConfigured as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(
            "Payment creation failed at provider",
            provider=provider.id,
            payment_id=str(payment.id),
            error=str(e),
        )
        payment.status = PaymentStatus.FAILED.value
        db.session.add(payment)
        db.session.commit()
        raise HTTPException(status_code=HTTPStatus.BAD_GATEWAY, detail="PAYMENT_PROVIDER_ERROR")

    payment.provider_payment_id = session.provider_payment_id
    payment.status = session.status.value
    payment.raw = session.raw
    db.session.add(payment)
    db.session.commit()

    return PaymentSessionSchema(
        payment_id=payment.id,
        order_id=order.id,
        provider=provider.id,
        status=payment.status,
        amount=payment.amount,
        currency=payment.currency,
        flow=session.flow,
        redirect_url=session.redirect_url,
        client_secret=session.client_secret,
        publishable_key=session.publishable_key,
    )


@router.get("/{payment_id}", response_model=PaymentStatusSchema)
def get_payment(shop_id: UUID, payment_id: UUID) -> PaymentStatusSchema:
    """Current payment status, freshly synced from the provider.

    The sync makes this endpoint double as the webhook fallback: when the
    customer lands on the return page before (or without) a webhook arriving,
    polling here still moves the payment — and on 'paid', the order — forward.
    """
    payment = payment_crud.get_id_by_shop_id(shop_id, payment_id)
    if not payment:
        raise_status(HTTPStatus.NOT_FOUND, f"Payment with id {payment_id} not found")
    shop = shop_crud.get(shop_id)

    current_status = PaymentStatus(payment.status)
    if payment.provider_payment_id and not current_status.is_terminal:
        try:
            provider = get_provider(shop, payment.provider)
            event = provider.get_status(shop=shop, provider_payment_id=payment.provider_payment_id)
            payment = apply_payment_event(payment=payment, event=event, shop=shop)
        except PaymentProviderError as e:
            # Return the stored status rather than failing the poll.
            logger.warning("Payment status sync failed", payment_id=str(payment.id), error=str(e))

    order = order_crud.get(payment.order_id)
    return PaymentStatusSchema(
        payment_id=payment.id,
        order_id=payment.order_id,
        provider=payment.provider,
        status=payment.status,
        order_status=order.status if order else "unknown",
    )
