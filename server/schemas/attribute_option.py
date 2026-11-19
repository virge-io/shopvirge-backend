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

from server.schemas.base import BoilerplateBaseModel


class AttributeOptionTranslationBase(BoilerplateBaseModel):
    # Only main_name is required for now
    main_name: str
    alt1_name: Optional[str] = None
    alt2_name: Optional[str] = None


class AttributeOptionBase(BoilerplateBaseModel):
    attribute_id: UUID
    value_key: str
    translation: Optional[AttributeOptionTranslationBase] = None


class AttributeOptionCreate(BoilerplateBaseModel):
    attribute_id: UUID
    value_key: str
    translation: Optional[AttributeOptionTranslationBase] = None


class AttributeOptionUpdate(BoilerplateBaseModel):
    value_key: str
    translation: Optional[AttributeOptionTranslationBase] = None


class AttributeOptionInDBBase(AttributeOptionBase):
    id: UUID

    class Config:
        from_attributes = True


class AttributeOptionSchema(AttributeOptionInDBBase):
    attribute_id: UUID
    value_key: str
    translation: Optional[AttributeOptionTranslationBase] = None
