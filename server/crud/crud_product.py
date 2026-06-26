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
from typing import Any, List, Literal, Optional, Tuple
from uuid import UUID, uuid4

from sqlalchemy import String, cast, or_
from sqlalchemy.orm import aliased

from server.crud.base import CRUDBase
from server.db import db
from server.db.models import (
    AttributeOptionTable,
    AttributeTable,
    AttributeTranslationTable,
    ProductAttributeValueTable,
    ProductTable,
)
from server.schemas.product import ProductCreate, ProductUpdate


def _generate_uuid_with_unique_short_id(model: type) -> UUID:
    new_id = uuid4()
    short = str(new_id)[:12]
    exists = db.session.query(model).filter(cast(model.id, String).startswith(short)).count() > 0
    if exists:
        return _generate_uuid_with_unique_short_id(model)
    return new_id


class CRUDProduct(CRUDBase[ProductTable, ProductCreate, ProductUpdate]):
    def get_multi_by_shop_id(
        self,
        *,
        shop_id: Any,
        skip: int = 0,
        limit: int = 100,
        filter_parameters: Optional[List[str]],
        sort_parameters: Optional[List[str]],
        query_parameter: Optional[Any] = None,
        stock_status: Literal["in_stock", "out_of_stock", "all"] = "all",
    ) -> Tuple[List[ProductTable], str]:
        query = query_parameter
        if query is None:
            query = db.session.query(self.model).filter(self.model.shop_id == shop_id)

        if stock_status == "in_stock":
            query = query.filter(ProductTable.stock > 0)
        elif stock_status == "out_of_stock":
            query = query.filter(ProductTable.stock == 0)

        if filter_parameters:
            for filter_parameter in filter_parameters:
                key, *value = filter_parameter.split(":", 1)
                if len(value) > 0:
                    val = value[0]
                    match key:
                        case "attribute_id":
                            query = query.join(ProductAttributeValueTable).filter(
                                ProductAttributeValueTable.attribute_id == val
                            )
                        case "option_id":
                            # We use aliased join for each option_id to achieve AND logic
                            pav_alias = aliased(ProductAttributeValueTable)
                            query = query.join(pav_alias, self.model.id == pav_alias.product_id).filter(
                                pav_alias.option_id == val
                            )
                        case "option_value_key":
                            # We use aliased join for each option_value_key to achieve AND logic
                            pav_alias = aliased(ProductAttributeValueTable)
                            opt_alias = aliased(AttributeOptionTable)
                            query = (
                                query.join(pav_alias, self.model.id == pav_alias.product_id)
                                .join(
                                    opt_alias,
                                    pav_alias.option_id == opt_alias.id,
                                )
                                .filter(opt_alias.value_key.ilike(f"%{val}%"))
                            )
                        case "attribute_name":
                            query = (
                                query.join(ProductAttributeValueTable)
                                .join(AttributeTable, ProductAttributeValueTable.attribute_id == AttributeTable.id)
                                .join(
                                    AttributeTranslationTable,
                                    AttributeTable.id == AttributeTranslationTable.attribute_id,
                                )
                                .filter(
                                    or_(
                                        AttributeTranslationTable.main_name.ilike(f"%{val}%"),
                                        AttributeTranslationTable.alt1_name.ilike(f"%{val}%"),
                                        AttributeTranslationTable.alt2_name.ilike(f"%{val}%"),
                                    )
                                )
                            )
                        case _:
                            pass

        return self.get_multi(
            skip=skip,
            limit=limit,
            filter_parameters=filter_parameters,
            sort_parameters=sort_parameters,
            query_parameter=query,
        )

    def _extra_create_fields(self) -> dict:
        new_id = _generate_uuid_with_unique_short_id(self.model)
        return {"id": new_id, "short_id": str(new_id)[:12]}


product_crud = CRUDProduct(ProductTable)
