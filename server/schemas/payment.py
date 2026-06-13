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
from typing import Literal, Optional
from uuid import UUID

from server.schemas.base import BoilerplateBaseModel, Money


class PaymentCreate(BoilerplateBaseModel):
    order_id: UUID
    # Where the PSP (or the frontend itself) sends the browser after the
    # payment attempt — typically the shop's /checkout/return page.
    return_url: str


class PaymentSessionSchema(BoilerplateBaseModel):
    """Provider-agnostic 'what to do next' answer for a created payment."""

    payment_id: UUID
    order_id: UUID
    provider: str
    status: str
    amount: Money
    currency: str
    flow: Literal["redirect", "client_confirmation"]
    redirect_url: Optional[str] = None
    client_secret: Optional[str] = None
    publishable_key: Optional[str] = None


class PaymentStatusSchema(BoilerplateBaseModel):
    payment_id: UUID
    order_id: UUID
    provider: str
    status: str
    order_status: str
