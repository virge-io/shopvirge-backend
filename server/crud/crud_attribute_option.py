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

from server.crud.base import CRUDBase
from server.db import db
from server.db.models import AttributeOptionTable, AttributeOptionTranslationTable
from server.schemas.attribute_option import AttributeOptionCreate, AttributeOptionUpdate


class CRUDAttributeOption(CRUDBase[AttributeOptionTable, AttributeOptionCreate, AttributeOptionUpdate]):
    def get_by_value_key(self, *, attribute_id, value_key: str) -> Optional[AttributeOptionTable]:
        return (
            AttributeOptionTable.query.filter(AttributeOptionTable.attribute_id == attribute_id)
            .filter(AttributeOptionTable.value_key == value_key)
            .first()
        )

    def update(
        self, *, db_obj: AttributeOptionTable, obj_in: AttributeOptionUpdate, commit: bool = True
    ) -> AttributeOptionTable:

        update_data = obj_in.model_dump(exclude_unset=True)

        translation_data = update_data.pop("translation", None)

        if translation_data is not None:
            translation = db_obj.translation

            if translation is None:
                translation = AttributeOptionTranslationTable(**translation_data)
                db_obj.translation = translation
            else:
                for field, value in translation_data.items():
                    setattr(translation, field, value)

        for field, value in update_data.items():
            if field in db_obj.__table__.columns and field != "id":
                setattr(db_obj, field, value)

        db.session.add(db_obj)

        if commit:
            db.session.commit()

        return db_obj


attribute_option_crud = CRUDAttributeOption(AttributeOptionTable)
