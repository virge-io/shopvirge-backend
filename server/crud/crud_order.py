# Copyright 2024 René Dohmen <acidjunk@gmail.com>
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

from sqlalchemy import func

from server.api.models import transform_json
from server.crud.base import CRUDBase
from server.db import db
from server.db.models import OrderTable, ShopTable
from server.schemas.order import OrderPersisted, OrderUpdate


class CRUDOrder(CRUDBase[OrderTable, OrderPersisted, OrderUpdate]):
    def create_with_next_customer_order_id(self, *, obj_in: OrderPersisted) -> OrderTable:
        # Lock the parent shop row so concurrent order creation for one shop
        # serializes until this order and its sequential customer ID are committed.
        db.session.query(ShopTable).filter(ShopTable.id == obj_in.shop_id).with_for_update().one()
        latest_id = (
            db.session.query(func.max(OrderTable.customer_order_id))
            .filter(OrderTable.shop_id == obj_in.shop_id)
            .scalar()
        )
        order_data = transform_json(obj_in.model_dump())
        order_data["customer_order_id"] = (latest_id or 0) + 1

        order = OrderTable(**order_data)
        db.session.add(order)
        db.session.commit()
        db.session.refresh(order)
        return order

    def get_all_orders_filtered_by(self, **kwargs):
        return OrderTable.query.filter_by(**kwargs).all()

    def get_first_order_filtered_by(self, **kwargs):
        return OrderTable.query.filter_by(**kwargs).first()


order_crud = CRUDOrder(OrderTable)
