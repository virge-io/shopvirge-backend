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
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from server.schemas.base import BoilerplateBaseModel, Money


# Made them optional for now because there are some empty order_info fields in DB
class OrderItem(BoilerplateBaseModel):
    description: Optional[str]
    price: Money  # Was optional
    # kind_id: Optional[str]
    # kind_name: Optional[str]
    product_id: UUID  # Was optional
    product_name: str  # Was optional
    quantity: int  # Was optional


class OrderBase(BoilerplateBaseModel):
    account_id: Optional[UUID] = None  # Optional for account creation on absence
    total: Optional[Money]
    notes: Optional[str]
    customer_order_id: Optional[int]  # Optional or required ?
    status: Optional[str]
    shipping_fee_inc_btw: Optional[Money] = None


# Properties to receive via API on creation
class OrderCreate(OrderBase):
    shop_id: UUID
    order_info: List[OrderItem]  # OrderItem
    completed_at: Optional[datetime] = None
    account_name: Optional[str] = None


# Properties to receive via API after creation
class OrderCreated(OrderBase):
    id: UUID
    created_at: datetime
    completed_at: Optional[datetime] = None
    account_name: Optional[str]


# Properties to receive via API on update
class OrderUpdate(OrderBase):
    shop_id: UUID
    order_info: List[OrderItem]  # OrderItem


class OrderUpdated(OrderUpdate):
    id: UUID


class OrderInDBBase(OrderBase):
    id: UUID
    shop_id: UUID
    order_info: List[OrderItem]  # OrderItem
    created_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# Additional properties to return via API
class OrderSchema(OrderInDBBase):
    account_name: Optional[str]
    shop_name: Optional[str]
