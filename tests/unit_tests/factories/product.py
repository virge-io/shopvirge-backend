from uuid import UUID, uuid4

import structlog

from server.db import db
from server.db.models import ProductTable, ProductTranslationTable

logger = structlog.getLogger(__name__)


def make_product(
    shop_id: UUID,
    category_id: UUID,
    main_name="Product for Testing",
    main_description_short="Test Product Short Description",
    main_description="Test Product Description",
    price=1.0,
    tax_category="vat_standard",
    stock: int = 1,
    shippable: bool = True,
):
    new_id = uuid4()
    product = ProductTable(
        id=new_id,
        short_id=str(new_id)[:12],
        shop_id=shop_id,
        category_id=category_id,
        price=price,
        stock=stock,
        tax_category=tax_category,
        shippable=shippable,
    )
    db.session.add(product)
    db.session.commit()

    # make translation
    trans = ProductTranslationTable(
        product_id=product.id,
        main_name=main_name,
        main_description=main_description,
        main_description_short=main_description_short,
    )

    db.session.add(trans)
    db.session.commit()

    return product.id


def make_translated_product(
    shop_id: UUID,
    category_id: UUID,
    main_name="Product for Testing",
    main_description_short="Test Product Short Description",
    main_description="Test Product Description",
    alt1_name="Product voor Testen",
    alt1_description="Test Product Beschrijving",
    alt1_description_short="Test Product Korte Beschrijving",
    alt2_name="Produkt zum Testen",
    alt2_description="Test Produkt Beschreibung",
    alt2_description_short="Test Produkt Kurzbeschreibung",
    price=1.0,
):
    new_id = uuid4()
    product = ProductTable(
        id=new_id, short_id=str(new_id)[:12], shop_id=shop_id, category_id=category_id, price=price, stock=1
    )
    db.session.add(product)
    db.session.commit()

    # make translation
    trans = ProductTranslationTable(
        product_id=product.id,
        main_name=main_name,
        main_description=main_description,
        main_description_short=main_description_short,
        alt1_name=alt1_name,
        alt1_description=alt1_description,
        alt1_description_short=alt1_description_short,
        alt2_name=alt2_name,
        alt2_description=alt2_description,
        alt2_description_short=alt2_description_short,
    )

    db.session.add(trans)
    db.session.commit()

    return product.id
