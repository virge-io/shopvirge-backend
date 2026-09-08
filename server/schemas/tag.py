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
from typing import Optional
from uuid import UUID

from server.schemas.base import BoilerplateBaseModel


class TagTranslationBase(BoilerplateBaseModel):
    main_name: str
    alt1_name: Optional[str] = None
    alt2_name: Optional[str] = None


class TagBase(BoilerplateBaseModel):
    shop_id: UUID
    name: str
    translation: TagTranslationBase


# Properties to receive via API on creation
class TagCreate(TagBase):
    pass


# Properties to receive via API on update
class TagUpdate(TagBase):
    pass


class TagInDBBase(TagBase):
    id: UUID

    class Config:
        from_attributes = True


# Additional properties to return via API
class TagSchema(TagInDBBase):
    pass
