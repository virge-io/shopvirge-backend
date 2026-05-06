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
from typing import List, Optional
from uuid import UUID

from server.schemas.base import BoilerplateBaseModel
from server.schemas.order import OrderItem


class ShippingCalculateRequest(BoilerplateBaseModel):
    shop_id: UUID
    order_info: List[OrderItem]


class ShippingLine(BoilerplateBaseModel):
    btw_rate: float
    amount_ex_btw: float
    amount_inc_btw: float
    amount_btw: float


class ShippingCalculation(BoilerplateBaseModel):
    enabled: bool
    method: Optional[str] = None
    fee_inc_btw: float
    fee_ex_btw: float
    fee_btw: float
    free_shipping_applied: bool
    free_shipping_threshold: Optional[float] = None
    lines: List[ShippingLine]
