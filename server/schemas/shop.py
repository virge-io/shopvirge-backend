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
from enum import Enum
from typing import Annotated, List, Optional
from uuid import UUID

from pydantic import EmailStr, UrlConstraints
from pydantic_core import Url
from pydantic_extra_types.phone_numbers import PhoneNumber

from server.schemas.base import BoilerplateBaseModel


class PhoneNumberNl(PhoneNumber):
    default_region_code = "NL"
    phone_format = "INTERNATIONAL"


HttpUrl = Annotated[
    Url,
    UrlConstraints(max_length=2083, allowed_schemes=["https"]),
]


class ShopEmptyBase(BoilerplateBaseModel):
    pass

    class Config:
        from_attributes = True


class ShopBase(BoilerplateBaseModel):
    name: str
    description: str
    internal_url: str | None = None
    external_url: str | None = None
    vat_standard: float
    vat_lower_1: float
    vat_lower_2: float
    vat_lower_3: float
    vat_special: float
    vat_zero: float


# Properties to receive via API on creation
class ShopCreate(ShopBase):
    pass


# Properties to receive via API on update
class ShopUpdate(ShopBase):
    modified_at: Optional[datetime]
    # Todo: deal with the commented params below
    # last_pending_order: Optional[str]
    # last_completed_order: Optional[str]
    allowed_ips: Optional[List[str]] = None


class ShopInDBBase(ShopBase):
    id: UUID

    class Config:
        from_attributes = True


# Additional properties to return via API
class ShopSchema(ShopInDBBase):
    pass


class ShopWithPrices(ShopInDBBase):
    # prices: List[dict]
    pass


class ShopCacheStatus(ShopEmptyBase):
    modified_at: Optional[datetime]


class ShopLastCompletedOrder(ShopEmptyBase):
    last_completed_order: Optional[str]


class ShopLastPendingOrder(ShopEmptyBase):
    last_pending_order: Optional[str]


class ShopIp(BoilerplateBaseModel):
    ip: str


class ConfigurationLanguageFieldMenuItems(BoilerplateBaseModel):
    about: str
    cart: str
    checkout: str
    products: str
    contact: str
    policies: str
    terms: str
    privacy_policy: str
    return_policy: str
    website: str
    phone: str
    email: str
    address: str


class ConfigurationLanguageFieldStaticTexts(BoilerplateBaseModel):
    about: str
    terms: str
    privacy_policy: str
    return_policy: str


class ConfigurationLanguageFields(BoilerplateBaseModel):
    language_name: str
    menu_items: ConfigurationLanguageFieldMenuItems
    static_texts: ConfigurationLanguageFieldStaticTexts


class ConfigurationLanguages(BoilerplateBaseModel):
    main: ConfigurationLanguageFields
    alt1: ConfigurationLanguageFields | None = None
    alt2: ConfigurationLanguageFields | None = None


class ConfigurationContact(BoilerplateBaseModel):
    company: str
    website: str | None = None
    phone: PhoneNumberNl
    email: EmailStr
    address: str
    zip_code: str
    city: str
    twitter: str | None = None
    facebook: str | None = None
    instagram: str | None = None
    linkedin: str | None = None
    tiktok: str | None = None


class ConfigurationLegal(BoilerplateBaseModel):
    kvk_number: str | None = None
    btw_number: str | None = None


class Toggles(BoilerplateBaseModel):
    show_new_products: bool = True
    show_featured_products: bool = True
    show_categories: bool = True
    show_shop_name: bool = True
    show_nav_categories: bool = False
    language_alt1_enabled: bool = False
    language_alt2_enabled: bool = False
    product_call_to_action_enabled: bool = False
    enable_stock_on_products: bool = False
    enable_attributes_for_categories: bool = False


class ConfigurationShipping(BoilerplateBaseModel):
    enabled: bool = False
    method: str = "fixed"
    fixed_fee: float = 0.0
    free_shipping_above_enabled: bool = False
    free_shipping_above_amount: float = 0.0


class ConfigurationV1(BoilerplateBaseModel):
    short_shop_name: str
    logo: str
    main_banner: str
    alt1_banner: str | None = None
    alt2_banner: str | None = None
    gradient_percentage: int = 75
    languages: ConfigurationLanguages
    google_analytics_id: str | None = None
    contact: ConfigurationContact
    toggles: Toggles
    legal: ConfigurationLegal | None = None
    shipping: ConfigurationShipping | None = None


class ShopTypeName(str, Enum):
    SMALL = "small"
    BUSINESS = "business"


class ShopType(BoilerplateBaseModel):
    max_languages: float
    max_products: float
    stripe_access: bool
    trial_mode: bool
    trial_started: datetime | None = None
    name: ShopTypeName


class ShopConfig(BoilerplateBaseModel):
    config: ConfigurationV1
    config_version: int
    shop_type: ShopType
    stripe_public_key: Optional[str]


class ShopConfigUpdate(BoilerplateBaseModel):
    config: ConfigurationV1
    config_version: int
