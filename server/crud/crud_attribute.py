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

from server.crud.base import CRUDBase, NotFound
from server.db import db
from server.db.models import AttributeOptionTable, AttributeTable, AttributeTranslationTable, ProductAttributeValueTable
from server.schemas.attribute import AttributeCreate, AttributeUpdate


class CRUDAttribute(CRUDBase[AttributeTable, AttributeCreate, AttributeUpdate]):
    def get_by_name(self, *, name: str, shop_id: UUID) -> Optional[AttributeTable]:
        return (
            AttributeTable.query.filter(AttributeTable.shop_id == shop_id).filter(AttributeTable.name == name).first()
        )

    def delete_deep_by_shop_id(self, *, shop_id: UUID, id: UUID) -> None:
        """
        Delete an attribute and all dependent records for a shop.
        Removes in safe order to satisfy FK constraints:
        1) ProductAttributeValue rows referencing the attribute
        2) AttributeOption rows for the attribute
        3) AttributeTranslation row for the attribute
        4) The Attribute itself
        """
        return  # disabled for now, just be sure
        # Fetch attribute first to validate shop ownership
        obj = (
            db.session.query(AttributeTable).filter(AttributeTable.shop_id == shop_id, AttributeTable.id == id).first()
        )
        if obj is None:
            raise NotFound
        try:
            # 1) Delete product attribute values referencing this attribute
            db.session.query(ProductAttributeValueTable).filter(
                ProductAttributeValueTable.attribute_id == obj.id
            ).delete(synchronize_session=False)

            # 2) Delete attribute options belonging to this attribute
            db.session.query(AttributeOptionTable).filter(AttributeOptionTable.attribute_id == obj.id).delete(
                synchronize_session=False
            )

            # 3) Delete translation if present
            db.session.query(AttributeTranslationTable).filter(AttributeTranslationTable.attribute_id == obj.id).delete(
                synchronize_session=False
            )

            # 4) Delete attribute itself
            db.session.delete(obj)

            db.session.commit()
        except:
            db.session.rollback()
            raise

    def delete_by_shop_id(self, *, shop_id: UUID, id: UUID, commit: bool = True, include_deleted: bool = False) -> None:
        """
        Delete an attribute for a shop.
        Does NOT delete related records automatically (no deep delete here anymore).
        Deletion will fail at DB level if relationships (PAVs) are still active (FK constraint).
        """
        # Fetch attribute first to validate shop ownership
        query = db.session.query(AttributeTable).filter(AttributeTable.shop_id == shop_id, AttributeTable.id == id)
        if include_deleted:
            query = query.execution_options(include_deleted=True)
        obj = query.first()
        if obj is None:
            raise NotFound
        try:
            db.session.delete(obj)
            if commit:
                db.session.commit()
        except:
            db.session.rollback()
            raise


attribute_crud = CRUDAttribute(AttributeTable)
