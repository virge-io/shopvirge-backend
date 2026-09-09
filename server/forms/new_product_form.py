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
from typing import Any, Generator, Optional

import structlog
from pydantic import validator
from pydantic.v1.validators import str_validator
from pydantic_forms.core import DisplayOnlyFieldType, FormPage, register_form
from pydantic_forms.types import FormGenerator, State

from server.db.models import CategoryTable, ProductTable, TagTable

logger = structlog.get_logger(__name__)


class MarkdownText(str):
    @classmethod
    def __modify_schema__(cls, field_schema: dict[str, Any]) -> None:
        field_schema.update(format="markdown", type="string")

    @classmethod
    def __get_validators__(cls) -> Generator:
        yield str_validator


class Hidden(DisplayOnlyFieldType):
    @classmethod
    def __modify_schema__(cls, field_schema: dict[str, Any]) -> None:
        field_schema.update(format="hidden", type="string")


def validate_product_name(product_name: str, values: State) -> str:
    """Check if product already exists."""
    products = ProductTable.query.all()
    product_items = [item.translation.main_name.lower() for item in products if item.translation]
    if product_name.lower() in product_items:
        raise ValueError("Dit product bestaat al.")
    return product_name


def validate_category_name(category_name: str, values: State) -> str:
    """Check if category already exists."""
    categories = CategoryTable.query.filter(CategoryTable.shop_id == values["shop_id"]).all()
    category_items = [item.translation.main_name.lower() for item in categories if item.translation]
    if category_name.lower() in category_items:
        raise ValueError("Deze categorie bestaat al.")
    return category_name


def validate_tag_name(tag_name: str, values: State) -> str:
    """Check if tag already exists."""
    tags = TagTable.query.all()
    tag_items = [item.name.lower() for item in tags if item.name]
    if tag_name.lower() in tag_items:
        raise ValueError("Deze tag bestaat al.")
    return tag_name


def create_tag_form(current_state: dict) -> FormGenerator:
    class TagForm(FormPage):
        class Config:
            title = "Nieuwe tag toevoegen"

        tag_name: str
        _validate_tag_name: classmethod = validator("tag_name", allow_reuse=True)(validate_tag_name)

    user_input = yield TagForm
    return user_input.dict()


def create_product_form(current_state: dict) -> FormGenerator:
    class ProductForm(FormPage):
        class Config:
            title = "Nieuwe horeca product toevoegen"

        product_name: str
        _validate_product_name: classmethod = validator("product_name", allow_reuse=True)(validate_product_name)
        short_description_nl: str
        description_nl: Optional[MarkdownText]
        short_description_en: Optional[str]
        description_en: Optional[MarkdownText]

    user_input = yield ProductForm
    return user_input.dict()


def create_category_form(current_state: dict) -> FormGenerator:
    class CategoryForm(FormPage):
        class Config:
            title = "Nieuwe categorie toevoegen"

        shop_id: Hidden = current_state["extra_state"]["shop_id"]
        category_name: str
        _validate_category_name: classmethod = validator("category_name", allow_reuse=True)(validate_category_name)
        name_en: Optional[str]
        # description: Optional[str]
        color: str = "#000000"
        icon: Optional[str]
        is_cannabis: bool = False

    user_input = yield CategoryForm
    return user_input.dict()


register_form("create_tag_form", create_tag_form)
register_form("create_product_form", create_product_form)
register_form("create_categorie_form", create_category_form)
