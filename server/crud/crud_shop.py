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
from uuid import UUID

from sqlalchemy import select

from server.crud.base import CRUDBase
from server.db.models import ShopTable
from server.schemas.shop import ShopCreate, ShopType, ShopUpdate


class CRUDShop(CRUDBase[ShopTable, ShopCreate, ShopUpdate]):
    def _extra_create_fields(self) -> dict:
        # The public config route serialises ``shop_type``, so a shop is never created without a valid one.
        return {"shop_type": ShopType.trial().model_dump(mode="json")}
    
    def has_related_data(self, shop_id: UUID) -> bool:
        """Check dynamically if the shop has related records in any model table containing a shop_id column."""
        from server.db import db
        from server.db.models import BaseModel

        for table in BaseModel.metadata.tables.values():
            if "shop_id" in table.c:
                stmt = select(1).select_from(table).where(table.c.shop_id == shop_id).limit(1)
                if db.session.scalar(stmt) is not None:
                    return True

        return False


shop_crud = CRUDShop(ShopTable)
