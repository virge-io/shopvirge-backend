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
from typing import Optional
from uuid import UUID

from server.schemas.base import BoilerplateBaseModel, Money


class PriceBase(BoilerplateBaseModel):
    internal_product_id: Optional[str]
    half: Optional[Money]
    one: Optional[Money]
    two_five: Optional[Money]
    five: Optional[Money]
    joint: Optional[Money]
    piece: Optional[Money]


# Properties to receive via API on creation
class PriceCreate(PriceBase):
    pass


# Properties to receive via API on update
class PriceUpdate(PriceBase):
    pass


class PriceInDBBase(PriceBase):
    id: UUID
    created_at: Optional[datetime]
    modified_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# Additional properties to return via API
class PriceSchema(PriceInDBBase):
    pass


# Made this to because Flask's kinds.get_multi() have prices with every field None and needed it to be 1:1
# Can be removed later
# In the original backend there is no half ??
class DefaultPrice(BoilerplateBaseModel):
    id: Optional[UUID] = None
    created_at: Optional[datetime] = None
    modified_at: Optional[datetime] = None
    internal_product_id: Optional[str] = None
    active: Optional[bool] = None
    new: Optional[bool] = None
    one: Optional[Money] = None
    two_five: Optional[Money] = None
    five: Optional[Money] = None
    joint: Optional[Money] = None
    piece: Optional[Money] = None
