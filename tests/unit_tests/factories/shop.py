import json
from uuid import uuid4

import structlog

from server.db import ShopTable, db
from server.schemas.shop import (
    ConfigurationContact,
    ConfigurationLanguageFieldMenuItems,
    ConfigurationLanguageFields,
    ConfigurationLanguageFieldStaticTexts,
    ConfigurationLanguages,
    ConfigurationShipping,
    ConfigurationV1,
    ShopConfig,
    ShopConfigUpdate,
    Toggles,
)

logger = structlog.getLogger(__name__)


def make_shop(with_config=False, random_shop_name=False):
    name = ""
    if random_shop_name:
        name = f" - {str(uuid4())}"
    if with_config:
        menu_items = ConfigurationLanguageFieldMenuItems(
            about="string",
            cart="string",
            checkout="string",
            products="string",
            contact="string",
            policies="string",
            terms="string",
            privacy_policy="string",
            return_policy="string",
            website="string",
            phone="string",
            email="string",
            address="string",
        )

        static_texts = ConfigurationLanguageFieldStaticTexts(
            about="string", terms="string", privacy_policy="string", return_policy="string"
        )

        language_fields = ConfigurationLanguageFields(
            language_name="string", menu_items=menu_items, static_texts=static_texts
        )

        toggles = Toggles(
            show_new_products=True,
            show_featured_products=True,
            show_categories=True,
            show_shop_name=True,
            show_nav_categories=False,
            language_alt1_enabled=False,
            language_alt2_enabled=False,
            enable_stock_on_products=True,
            enable_attributes_for_categories=False,
        )

        config_languages = ConfigurationLanguages(main=language_fields, alt1=language_fields, alt2=language_fields)

        config_contact = ConfigurationContact(
            company="string",
            website="https://example.com/",
            phone="+31 6 12345678",
            email="user@example.com",
            address="string",
            zip_code="string",
            city="string",
            twitter="https://example.com/",
            facebook="https://example.com/",
            instagram="https://example.com/",
        )

        config = ConfigurationV1(
            languages=config_languages,
            short_shop_name="string",
            main_banner="string",
            alt1_banner="string",
            alt2_banner="string",
            logo="string",
            contact=config_contact,
            toggles=toggles,
        )

        shop = ShopTable(
            name=f"Test Shop with config{name}",
            description=f"Test Shop Description with config{name}",
            config=config.model_dump(),
            shop_type="{}",
            vat_standard=21,
            vat_lower_1=15,
            vat_lower_2=10,
            vat_lower_3=5,
            vat_special=2,
            vat_zero=0,
            stripe_public_key="string",
        )
    else:
        shop = ShopTable(
            name=f"Test Shop{name}",
            description=f"Test Shop Description{name}",
            stripe_public_key="string",
            vat_standard=21,
            vat_lower_1=15,
            vat_lower_2=10,
            vat_lower_3=5,
            vat_special=2,
            vat_zero=0,
            config="{}",
            shop_type="{}",
        )
    db.session.add(shop)
    db.session.commit()
    return shop.id


def make_shop_with_shipping(
    fixed_fee: float = 4.95,
    free_shipping_above_enabled: bool = False,
    free_shipping_above_amount: float = 0.0,
    enabled: bool = True,
    method: str = "fixed",
):
    """Create a shop with a populated config and a shipping block."""
    menu_items = ConfigurationLanguageFieldMenuItems(
        about="string",
        cart="string",
        checkout="string",
        products="string",
        contact="string",
        policies="string",
        terms="string",
        privacy_policy="string",
        return_policy="string",
        website="string",
        phone="string",
        email="string",
        address="string",
    )
    static_texts = ConfigurationLanguageFieldStaticTexts(
        about="string", terms="string", privacy_policy="string", return_policy="string"
    )
    language_fields = ConfigurationLanguageFields(
        language_name="string", menu_items=menu_items, static_texts=static_texts
    )
    toggles = Toggles()
    config_languages = ConfigurationLanguages(main=language_fields)
    config_contact = ConfigurationContact(
        company="string",
        phone="+31 6 12345678",
        email="user@example.com",
        address="string",
        zip_code="string",
        city="string",
    )
    shipping = ConfigurationShipping(
        enabled=enabled,
        method=method,
        fixed_fee=fixed_fee,
        free_shipping_above_enabled=free_shipping_above_enabled,
        free_shipping_above_amount=free_shipping_above_amount,
    )
    config = ConfigurationV1(
        languages=config_languages,
        short_shop_name="string",
        main_banner="string",
        logo="string",
        contact=config_contact,
        toggles=toggles,
        shipping=shipping,
    )
    shop = ShopTable(
        name=f"Test Shop with shipping - {uuid4()}",
        description=f"Test Shop Description with shipping - {uuid4()}",
        config=config.model_dump(),
        shop_type="{}",
        vat_standard=21,
        vat_lower_1=9,
        vat_lower_2=10,
        vat_lower_3=5,
        vat_special=2,
        vat_zero=0,
        stripe_public_key="string",
    )
    db.session.add(shop)
    db.session.commit()
    return shop.id
