import json
from datetime import datetime
from enum import Enum
from uuid import UUID

import structlog
from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy.orm import contains_eager, selectinload

from server.api.route_helpers import get_or_404
from server.crud.crud_product import ATTRIBUTE_NAMES
from server.crud.crud_shop import shop_crud
from server.db import ProductTable, db
from server.db.models import (
    CategoryTable,
    CategoryTranslationTable,
    ProductTranslationTable,
)
from server.schemas.base import Money

router = APIRouter()

logger = structlog.get_logger(__name__)


class Lang(str, Enum):
    """Language options."""

    MAIN = "main"
    ALT1 = "alt1"
    ALT2 = "alt2"


class ProductResponse(BaseModel):
    id: str
    short_id: str | None = None
    sku: str | None = None
    category: str
    category_image: str | None = None
    category_order_number: int
    order_number: int
    stock: int | None = None
    tags: list[str] = []
    name: str
    description_short: str
    description: str
    tax_category: str
    tax_percentage: Money
    price: Money | None = None
    recurring_price_monthly: Money | None = None
    recurring_price_yearly: Money | None = None
    max_one: bool
    shippable: bool
    attributes: list[str] = []
    digital: str | None = None
    featured: bool
    new_product: bool
    discounted_price: Money | None = None
    discounted_from: datetime | None = None
    discounted_to: datetime | None = None
    image_1: str | None = None
    image_2: str | None = None
    image_3: str | None = None
    image_4: str | None = None
    image_5: str | None = None
    image_6: str | None = None


class Cart(BaseModel):
    products: list[UUID]


def _catalogue_query(shop_id: UUID):
    """The shop's products with everything the pricelist renders, loaded in a fixed number of queries.

    The inner joins keep excluding products without a translation or a (translated) category; ``contains_eager``
    makes those already-joined rows populate the relationships instead of one lazy SELECT per product. Tags and
    attribute names follow in a few batched ``IN`` queries, so the statement count no longer grows with the
    catalogue — the old version issued roughly two queries per product and kept its pooled connection busy for
    the whole catalogue.
    """
    return (
        db.session.query(ProductTable)
        .join(ProductTable.translation)
        .join(ProductTable.category)
        .join(CategoryTable.translation)
        .options(
            contains_eager(ProductTable.translation),
            contains_eager(ProductTable.category).contains_eager(CategoryTable.translation),
            selectinload(ProductTable.tags),
            *ATTRIBUTE_NAMES,
        )
        .filter(ProductTable.shop_id == shop_id)
    )


def _load_and_release(query) -> list[ProductTable]:
    """Run the catalogue query, then give the pooled connection back before the response is built.

    Building a few hundred ``ProductResponse`` objects is pure Python and takes far longer than the queries;
    everything it reads has been eagerly loaded, so the ORM objects are detached (keeping their loaded state)
    and the connection goes back to the pool instead of idling in a transaction until the response is sent.
    """
    rows = query.all()
    db.session.expunge_all()
    db.release_connection()
    return rows


def _shop_config(shop) -> dict:
    """The shop config as a dict, without writing a normalised copy back onto the ORM object."""
    return json.loads(shop.config) if isinstance(shop.config, str) else (shop.config or {})


def _attribute_names(product: ProductTable) -> list[str]:
    # A soft-deleted attribute is filtered out of the eager load, leaving ``pav.attribute`` empty.
    return [
        pav.attribute.translation.main_name
        for pav in product.attribute_values
        if pav.attribute is not None and pav.attribute.translation is not None
    ]


# Note: the "product" will have some Joined attributes that are not avail on the type itself
def to_response_model(product: ProductTable, lang: Lang, shop) -> ProductResponse:
    tax = getattr(shop, product.tax_category)

    if lang == Lang.MAIN:
        product_response = ProductResponse(
            id=str(product.id),
            short_id=product.short_id,
            sku=product.sku,
            category=product.category.translation.main_name,
            category_image=product.category.main_image,
            category_order_number=product.category.order_number,
            order_number=product.order_number,
            tags=[tag.translation.main_name for tag in product.tags],
            name=product.translation.main_name,
            description_short=product.translation.main_description_short,
            description=product.translation.main_description,
            tax_category=product.tax_category,
            tax_percentage=tax,
            max_one=product.max_one,
            shippable=product.shippable,
            featured=product.featured,
            new_product=product.new_product,
            attributes=_attribute_names(product),
        )
    elif lang == Lang.ALT1:
        product_response = ProductResponse(
            id=str(product.id),
            short_id=product.short_id,
            sku=product.sku,
            category=product.category.translation.alt1_name,
            category_image=(
                product.category.alt1_image if product.category.alt1_image else product.category.main_image
            ),
            category_order_number=product.category.order_number,
            order_number=product.order_number,
            tags=[tag.translation.alt1_name for tag in product.tags if tag.translation.alt1_name],
            name=product.translation.alt1_name,
            description_short=product.translation.alt1_description_short,
            description=product.translation.alt1_description,
            tax_category=product.tax_category,
            tax_percentage=tax,
            max_one=product.max_one,
            shippable=product.shippable,
            featured=product.featured,
            new_product=product.new_product,
            attributes=_attribute_names(product),  # TODO update me when attribute translations are implemented
        )
    elif lang == Lang.ALT2:
        product_response = ProductResponse(
            id=str(product.id),
            short_id=product.short_id,
            sku=product.sku,
            category=product.category.translation.alt2_name,
            category_image=(
                product.category.alt2_image if product.category.alt2_image else product.category.main_image
            ),
            category_order_number=product.category.order_number,
            order_number=product.order_number,
            tags=[tag.translation.alt2_name for tag in product.tags if tag.translation.alt2_name],
            name=product.translation.alt2_name,
            description_short=product.translation.alt2_description_short,
            description=product.translation.alt2_description,
            tax_category=product.tax_category,
            tax_percentage=tax,
            max_one=product.max_one,
            shippable=product.shippable,
            featured=product.featured,
            new_product=product.new_product,
            attributes=_attribute_names(product),  # TODO update me when attribute translations are implemented
        )
    else:
        raise ValueError(f"Unsupported language: {lang}")

    product_response.price = product.price
    product_response.recurring_price_monthly = product.recurring_price_monthly
    product_response.recurring_price_yearly = product.recurring_price_yearly
    product_response.discounted_price = product.discounted_price
    product_response.discounted_from = product.discounted_from
    product_response.discounted_to = product.discounted_to
    product_response.image_1 = product.image_1
    product_response.image_2 = product.image_2
    product_response.image_3 = product.image_3
    product_response.image_4 = product.image_4
    product_response.image_5 = product.image_5
    product_response.image_6 = product.image_6
    product_response.digital = product.digital
    product_response.stock = product.stock

    return product_response


@router.get(
    "/",
    response_model=list[ProductResponse],
    summary="List products (pricelist)",
    description=(
        "Returns the full product catalogue for a shop in the requested language (`main`, `alt1`, or `alt2`). "
        "Products with missing translations for the requested language are excluded. "
        "When stock tracking is enabled, out-of-stock products are also filtered out."
    ),
)
def get_products(
    shop_id: UUID,
    lang: Lang,
    # response: Response,
) -> list[dict]:
    shop = get_or_404(shop_crud.get(shop_id), f"Shop with id {shop_id} not found")
    products = _catalogue_query(shop_id)

    if lang == Lang.ALT1:
        # filter out products and categories with missing translations
        products = (
            products.filter(ProductTranslationTable.alt1_name.is_not(None))
            .filter(ProductTranslationTable.alt1_description.is_not(None))
            .filter(ProductTranslationTable.alt1_description_short.is_not(None))
            .filter(CategoryTranslationTable.alt1_name.is_not(None))
        )
    if lang == Lang.ALT2:
        # filter out products and categories with missing translations
        products = (
            products.filter(ProductTranslationTable.alt2_name.is_not(None))
            .filter(ProductTranslationTable.alt2_description.is_not(None))
            .filter(ProductTranslationTable.alt2_description_short.is_not(None))
            .filter(CategoryTranslationTable.alt2_name.is_not(None))
        )

    # Filter out-of-stock products in SQL rather than after building every response row.
    if _shop_config(shop).get("toggles", {}).get("enable_stock_on_products"):
        products = products.filter(ProductTable.stock > 0)

    rows = _load_and_release(products)
    return [to_response_model(product, lang, shop) for product in rows]


@router.post(
    "/",
    response_model=list[ProductResponse],
    summary="Get cart products",
    description=(
        "Retrieve product details for a list of product IDs (a cart). "
        "Falls back to the `main` language for any product missing a translation in the requested language."
    ),
)
def get_cart_products(
    shop_id: UUID,
    lang: Lang,
    cart: Cart,
    # response: Response,
) -> list[dict]:
    shop = get_or_404(shop_crud.get(shop_id), f"Shop with id {shop_id} not found")
    products = _catalogue_query(shop_id).filter(ProductTable.id.in_(cart.products))

    response_products = []

    for product in _load_and_release(products):
        if lang == Lang.ALT1:
            if (
                product.translation.alt1_name is None
                or product.translation.alt1_description is None
                or product.translation.alt1_description_short is None
                or product.category.translation.alt1_name is None
            ):
                response_product = to_response_model(product, Lang.MAIN, shop)
                response_products.append(response_product)
            else:
                response_product = to_response_model(product, lang, shop)
                response_products.append(response_product)
        elif lang == Lang.ALT2:
            if (
                product.translation.alt2_name is None
                or product.translation.alt2_description is None
                or product.translation.alt2_description_short is None
                or product.category.translation.alt2_name is None
            ):
                response_product = to_response_model(product, Lang.MAIN, shop)
                response_products.append(response_product)
            else:
                response_product = to_response_model(product, lang, shop)
                response_products.append(response_product)
        else:
            response_product = to_response_model(product, lang, shop)
            response_products.append(response_product)

    return response_products
