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

from server.schemas.base import BoilerplateBaseModel


class LicenseBase(BoilerplateBaseModel):
    name: str
    improviser_user: UUID
    is_recurring: bool
    seats: float
    order_id: UUID
    end_date: Optional[datetime]


class LicenseCreate(LicenseBase):
    pass


class LicenseUpdate(BoilerplateBaseModel):
    seats: Optional[float]
    end_date: Optional[datetime]


class LicenseInDB(LicenseBase):
    id: UUID
    modified_at: datetime
    created_at: datetime
    start_date: datetime

    class Config:
        from_attributes = True


class LicenseSchema(LicenseInDB):
    pass
