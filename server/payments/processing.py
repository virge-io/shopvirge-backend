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
"""Apply normalized payment events to our payment + order state.

This is the single funnel between providers and the order lifecycle: both
webhook delivery and poll-time status sync end up here, so completion
semantics (idempotency included) exist exactly once.
"""

import structlog

from server.db import db
from server.db.models import OrderTable, PaymentTable, ShopTable
from server.payments.base import PaymentEvent, PaymentStatus
from server.services.order_lifecycle import complete_order

logger = structlog.get_logger(__name__)


def apply_payment_event(*, payment: PaymentTable, event: PaymentEvent, shop: ShopTable) -> PaymentTable:
    """Persist a payment status change and complete the order when paid.

    Idempotent: replays of the same event (Mollie retries webhooks) find the
    payment already in its target status and the order already complete.
    """
    old_status = payment.status
    payment.status = event.status.value
    if event.raw is not None:
        payment.raw = event.raw
    db.session.add(payment)
    db.session.commit()

    if old_status != payment.status:
        logger.info(
            "Payment status changed",
            payment_id=str(payment.id),
            provider=payment.provider,
            provider_payment_id=payment.provider_payment_id,
            old_status=old_status,
            new_status=payment.status,
        )

    if event.status == PaymentStatus.PAID:
        order = db.session.get(OrderTable, payment.order_id)
        if order is not None:
            complete_order(order, shop)

    return payment
