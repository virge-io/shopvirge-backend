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
from http import HTTPStatus

import structlog
from fastapi import APIRouter
from fastapi.param_functions import Body

from server.api.error_handling import raise_status
from server.crud.crud_shop import shop_crud
from server.schemas.shipping import ShippingCalculateRequest, ShippingCalculation
from server.services.shipping import compute_shipping_for_cart

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.post("/calculate", response_model=ShippingCalculation)
def calculate(data: ShippingCalculateRequest = Body(...)) -> ShippingCalculation:
    shop = shop_crud.get(data.shop_id)
    if not shop:
        raise_status(HTTPStatus.NOT_FOUND, f"Shop with id {data.shop_id} not found")

    calc = compute_shipping_for_cart(data.order_info, shop)
    if calc is None:
        return ShippingCalculation(
            enabled=False,
            method=None,
            fee_inc_btw=0.0,
            fee_ex_btw=0.0,
            fee_btw=0.0,
            free_shipping_applied=False,
            free_shipping_threshold=None,
            lines=[],
        )
    return calc
