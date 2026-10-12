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
from server.crud.base import CRUDBase
from server.db.models import ShopTable
from server.schemas.shop import ShopCreate, ShopType, ShopUpdate


class CRUDShop(CRUDBase[ShopTable, ShopCreate, ShopUpdate]):
    def _extra_create_fields(self) -> dict:
        # The public config route serialises ``shop_type``, so a shop is never created without a valid one.
        return {"shop_type": ShopType.trial().model_dump(mode="json")}


shop_crud = CRUDShop(ShopTable)
