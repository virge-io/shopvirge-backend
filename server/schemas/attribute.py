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

from server.schemas.attribute_option import AttributeOptionSchema
from server.schemas.base import BoilerplateBaseModel


class AttributeTranslationBase(BoilerplateBaseModel):
    # Only main_name is required for now
    main_name: str
    alt1_name: Optional[str] = None
    alt2_name: Optional[str] = None


class AttributeBase(BoilerplateBaseModel):
    shop_id: UUID
    name: str
    unit: Optional[str] = None
    translation: Optional[AttributeTranslationBase] = None


class AttributeCreate(BoilerplateBaseModel):
    name: str
    unit: Optional[str] = None
    translation: Optional[AttributeTranslationBase] = None


class AttributeUpdate(BoilerplateBaseModel):
    name: Optional[str] = None
    unit: Optional[str] = None
    translation: Optional[AttributeTranslationBase] = None


class AttributeInDBBase(AttributeBase):
    id: UUID

    class Config:
        from_attributes = True


class AttributeSchema(AttributeInDBBase):
    pass


class AttributeWithOptionsSchema(AttributeInDBBase):
    options: list[AttributeOptionSchema] = []


class AvailableOptionSchema(BoilerplateBaseModel):
    id: UUID
    value_key: str
    product_count: int


class AvailableAttributeSchema(BoilerplateBaseModel):
    id: UUID
    name: str
    unit: Optional[str] = None
    translation: Optional[AttributeTranslationBase] = None
    options: list[AvailableOptionSchema] = []
