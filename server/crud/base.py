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
from typing import Any, Generic, List, Optional, Tuple, Type, TypeVar, Union
from uuid import UUID

import structlog
from fastapi.encoders import jsonable_encoder
from more_itertools import one
from sqlalchemy import String, cast, or_
from sqlalchemy.inspection import inspect as sa_inspect
from sqlalchemy.sql import expression

from server.api.models import transform_json
from server.db import db
from server.db.database import BaseModel

# Below translation model imports are necessary for the create_by_shop_id, update, and delete_by_shop_id functions
from server.db.models import (
    AttributeTranslationTable,
    CategoryTranslationTable,
    ProductTranslationTable,
    TagTranslationTable,
)

logger = structlog.getLogger()

ModelType = TypeVar("ModelType", bound=BaseModel)
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)


class NotFound(Exception):
    pass


class CRUDBase(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    def __init__(self, model: Type[ModelType]):
        """
        CRUD object with default methods to Create, Read, Update, Delete (CRUD).

        **Parameters**
        * `model`: A SQLAlchemy model class
        * `schema`: A Pydantic model (schema) class
        """
        self.model = model

    def get(self, id: UUID | str) -> Optional[ModelType]:
        obj = db.session.get(self.model, id)
        # Session.get() can bypass the do_orm_execute soft-delete filter (identity map),
        # so re-check deleted_at explicitly for soft-deletable models.
        if obj is not None and getattr(obj, "deleted_at", None) is not None:
            return None
        return obj

    def get_id(self, id: UUID | str) -> Optional[ModelType]:
        return self.get(id)

    def get_id_by_shop_id(
        self,
        shop_id: UUID,
        id: UUID,
        for_update: bool = False,
        include_deleted: bool = False,
    ) -> Optional[ModelType]:
        query = db.session.query(self.model).filter(self.model.shop_id == shop_id, self.model.id == id)
        if include_deleted:
            query = query.execution_options(include_deleted=True)
        if for_update:
            # Row lock: serializes concurrent writers on the same entity so that
            # revision numbering (max + 1) is race-free.
            query = query.with_for_update()
        return query.first()

    def get_multi(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        filter_parameters: Optional[List[str]],
        sort_parameters: Optional[List[str]],
        query_parameter: Optional[Any] = None,
    ) -> Tuple[List[ModelType], str]:
        query = query_parameter
        if query is None:
            query = db.session.query(self.model)

        logger.debug(
            f"Filter and Sort parameters model={self.model}, sort_parameters={sort_parameters}, filter_parameters={filter_parameters}",
        )
        conditions = []

        if filter_parameters:
            for filter_parameter in filter_parameters:
                key, *value = filter_parameter.split(":", 1)

                # Use this branch if we detect a key value search (key:value) if it is just a single string (value)
                # treat the key as the value
                if len(value) > 0:
                    if key in sa_inspect(self.model).columns.keys():
                        conditions.append(cast(self.model.__dict__[key], String).ilike("%" + one(value) + "%"))
                    else:
                        logger.info(f"Key: not found in database model key={key}, model={self.model}")
                    query = query.filter(or_(*conditions))
                else:
                    if isinstance(value, list):
                        logger.info("Query parameters set to GET_MANY, ID column only", value=value)
                        conditions = []
                        for item in value:
                            conditions.append(self.model.__dict__["id"] == item)
                        query = query.filter(or_(*conditions))
                    else:
                        for column in sa_inspect(self.model).columns.keys():
                            conditions.append(cast(self.model.__dict__[column], String).ilike("%" + key + "%"))
                            query = query.filter(or_(*conditions))

        if sort_parameters and len(sort_parameters):
            for sort_parameter in sort_parameters:
                try:
                    sort_col, sort_order = sort_parameter.split(":")
                    if sort_col in sa_inspect(self.model).columns.keys():
                        if sort_order.upper() == "DESC":
                            query = query.order_by(expression.desc(self.model.__dict__[sort_col]))
                        else:
                            query = query.order_by(expression.asc(self.model.__dict__[sort_col]))
                    else:
                        logger.debug(f"Sort col does not exist sort_col={sort_col}")
                except ValueError:
                    if sort_parameter in sa_inspect(self.model).columns.keys():
                        query = query.order_by(expression.asc(self.model.__dict__[sort_parameter]))
                    else:
                        logger.debug(f"Sort param does not exist sort_parameter={sort_parameter}")

        # Generate Content Range Header Values
        count = query.count()

        if limit:
            # Limit is not 0: use limit
            response_range = "{}s {}-{}/{}".format(self.model.__name__.lower(), skip, skip + limit, count)
            return query.offset(skip).limit(limit).all(), response_range
        else:
            # Limit is 0: unlimited
            response_range = "{}s {}/{}".format(self.model.__name__.lower(), skip, count)
            return query.offset(skip).all(), response_range

    def get_multi_by_shop_id(
        self,
        *,
        shop_id: any,
        skip: int = 0,
        limit: int = 100,
        filter_parameters: Optional[List[str]],
        sort_parameters: Optional[List[str]],
        query_parameter: Optional[Any] = None,
    ) -> Tuple[List[ModelType], str]:
        query = query_parameter
        if query is None:
            query = db.session.query(self.model).filter(self.model.shop_id == shop_id)
        return self.get_multi(
            skip=skip,
            limit=limit,
            filter_parameters=filter_parameters,
            sort_parameters=sort_parameters,
            query_parameter=query,
        )

    def create(self, *, obj_in: CreateSchemaType) -> ModelType:
        obj_in_data = transform_json(obj_in.model_dump())
        # Todo: remove translate from base? We should handle this in a more generic way, for now a UGLY hack:
        translation_data = None
        try:
            translation_data = obj_in_data.pop("translation")
        except:
            pass

        db_obj = self.model(**obj_in_data)
        db.session.add(db_obj)
        db.session.commit()
        db.session.refresh(db_obj)

        if translation_data:
            translation_name = db_obj.__class__.__name__.split("Table")[0]
            translation_model = globals().get(translation_name + "TranslationTable", None)
            translation_data[translation_name.lower() + "_id"] = db_obj.id
            translation = translation_model(**translation_data)
            db.session.add(translation)
            db.session.commit()
            db.session.refresh(translation)

        return db_obj

    def _extra_create_fields(self) -> dict:
        return {}

    def create_by_shop_id(self, *, shop_id: any, obj_in: CreateSchemaType, commit: bool = True) -> ModelType:
        obj_in_data = transform_json(obj_in.model_dump())
        # Todo: remove translate from base? We should handle this in a more generic way, for now a UGLY hack:
        translation_data = None
        try:
            translation_data = obj_in_data.pop("translation")
        except:
            pass

        try:
            db_obj = self.model(**{**obj_in_data, "shop_id": shop_id, **self._extra_create_fields()})
            db.session.add(db_obj)
            db.session.flush()

            if translation_data:
                for field in translation_data:
                    if translation_data[field] == "":
                        translation_data[field] = None
                translation_name = db_obj.__class__.__name__.split("Table")[0]
                translation_model = globals().get(translation_name + "TranslationTable", None)
                translation_data[translation_name.lower() + "_id"] = db_obj.id
                translation = translation_model(**translation_data)
                db.session.add(translation)
                if commit:
                    db.session.commit()
                    db.session.refresh(db_obj)
                    db.session.refresh(translation)
                else:
                    db.session.flush()
        except:
            db.session.rollback()
            raise

        return db_obj

    def update(self, *, db_obj: ModelType, obj_in: UpdateSchemaType, commit: bool = True) -> ModelType:
        obj_data = jsonable_encoder(db_obj)
        update_data = obj_in.model_dump(exclude_unset=True)

        # # Handle int based foreign key types:
        # for k, v in update_data.items():
        #     if isinstance(v, int):
        #         update_data[k] = v

        # Update translations
        if "translation" in update_data:
            translation_data = update_data.pop("translation")
            translation_name = db_obj.__class__.__name__.split("Table")[0]
            translation_model = globals().get(translation_name + "TranslationTable", None)
            translation = (
                db.session.query(translation_model).filter_by(**{translation_name.lower() + "_id": db_obj.id}).first()
            )
            if translation:
                for field in translation_data:
                    if translation_data[field] != "":
                        setattr(translation, field, translation_data[field])
                    else:
                        setattr(translation, field, None)
                db.session.add(translation)

        # Update DB record
        for field in obj_data:
            if field != "id" and field in update_data:
                setattr(db_obj, field, update_data[field])

        db.session.add(db_obj)

        # Set to false if you make two or more updates consecutively
        if commit:
            db.session.commit()

        return db_obj

    def delete(self, *, id: str) -> None:
        obj = db.session.get(self.model, id)
        if obj is None:
            raise NotFound
        db.session.delete(obj)
        db.session.commit()
        return None

    def delete_by_shop_id(self, *, shop_id: UUID, id: UUID, commit: bool = True, include_deleted: bool = False) -> None:
        query = db.session.query(self.model).filter(self.model.shop_id == shop_id, self.model.id == id)
        if include_deleted:
            query = query.execution_options(include_deleted=True)
        obj = query.first()
        if obj is None:
            raise NotFound

        if obj.translation:
            translation_name = obj.__class__.__name__.split("Table")[0]
            translation_model = globals().get(translation_name + "TranslationTable", None)
            if translation_model:
                translation_obj = (
                    db.session.query(translation_model).filter(translation_model.id == obj.translation.id).first()
                )

                if translation_obj:
                    db.session.delete(translation_obj)

        db.session.delete(obj)
        if commit:
            db.session.commit()
        return None
