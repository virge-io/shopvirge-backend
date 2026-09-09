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
from typing import Optional, Union
from uuid import UUID

from server.schemas.base import BoilerplateBaseModel


class CategoryEmptyBase(BoilerplateBaseModel):
    pass


class CategoryTranslationBase(BoilerplateBaseModel):
    main_name: str
    main_description: str
    alt1_name: Optional[str] = None
    alt1_description: Optional[str] = None
    alt2_name: Optional[str] = None
    alt2_description: Optional[str] = None


class CategoryBase(BoilerplateBaseModel):
    shop_id: UUID
    color: str
    icon: Optional[str] = None
    order_number: Optional[int] = None
    translation: CategoryTranslationBase
    main_image: Union[Optional[dict], Optional[str]] = None
    alt1_image: Union[Optional[dict], Optional[str]] = None
    alt2_image: Union[Optional[dict], Optional[str]] = None


# Properties to receive via API on creation
class CategoryCreate(CategoryBase):
    pass


class CategoryTranslationUpdate(CategoryTranslationBase):
    main_name: Optional[str] = None
    main_description: Optional[str] = None


# Properties to receive via API on update. All fields are optional: the CRUD
# layer updates with exclude_unset=True (PATCH semantics), so omitted fields
# are left untouched.
class CategoryUpdate(CategoryBase):
    shop_id: Optional[UUID] = None
    color: Optional[str] = None
    translation: Optional[CategoryTranslationUpdate] = None


class CategoryInDBBase(CategoryBase):
    id: UUID

    class Config:
        from_attributes = True


# Additional properties to return via API
class CategorySchema(CategoryInDBBase):
    pass


class CategoryWithNames(CategoryInDBBase):
    pass
    # shop_name: str


class CategoryImageDelete(CategoryEmptyBase):
    image: str


class CategoryIsDeletable(CategoryEmptyBase):
    is_deletable: bool


class CategoryOrder(BoilerplateBaseModel):
    order_number: int
