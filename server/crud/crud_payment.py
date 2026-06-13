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
from typing import Optional
from uuid import UUID

from server.crud.base import CRUDBase
from server.db import db
from server.db.models import OrderTable, PaymentTable
from server.schemas.payment import PaymentCreate


class CRUDPayment(CRUDBase[PaymentTable, PaymentCreate, PaymentCreate]):
    def create_for_order(self, *, order: OrderTable, provider: str, currency: str = "EUR") -> PaymentTable:
        """Persist a new payment attempt for an order, amount taken from the order."""
        payment = PaymentTable(
            shop_id=order.shop_id,
            order_id=order.id,
            provider=provider,
            amount=order.total,
            currency=currency,
            status="created",
        )
        db.session.add(payment)
        db.session.commit()
        db.session.refresh(payment)
        return payment

    def get_by_provider_payment_id(self, *, shop_id: UUID, provider_payment_id: str) -> Optional[PaymentTable]:
        return (
            db.session.query(PaymentTable)
            .filter(
                PaymentTable.shop_id == shop_id,
                PaymentTable.provider_payment_id == provider_payment_id,
            )
            .first()
        )


payment_crud = CRUDPayment(PaymentTable)
