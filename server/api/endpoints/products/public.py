from http import HTTPStatus
from uuid import UUID

import structlog
from fastapi import APIRouter

from server.agent_tags import AgentTag
from server.api.error_handling import raise_status
from server.crud.crud_product import product_crud
from server.schemas.product import (
    ProductWithAttributes,
    ProductWithDefaultPrice,
    ProductWithDetailsAndPrices,
)
from server.schemas.product_attribute import ProductAttributeItem

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get(
    "/{product_id}/with_attributes",
    response_model=ProductWithAttributes,
    tags=[AgentTag.EXPOSED],
    operation_id="get_product_attributes",
    summary="Get product with attributes",
    description="Retrieve a single product together with its assigned attribute values (e.g. size, color). Public endpoint — no authentication required.",
)
def get_by_id_with_attributes(product_id: UUID, shop_id: UUID) -> ProductWithAttributes:
    """Retrieve a product together with every attribute option currently assigned to it."""
    product = product_crud.get_id_by_shop_id(shop_id, product_id)
    if not product:
        raise_status(HTTPStatus.NOT_FOUND, f"Product with id {product_id} not found")

    product.images_amount = 0
    for i in [1, 2, 3, 4, 5, 6]:
        if getattr(product, f"image_{i}"):
            product.images_amount += 1

    attrs: list[ProductAttributeItem] = []
    for pav in getattr(product, "attribute_values", []) or []:
        attribute = getattr(pav, "attribute", None)
        option = getattr(pav, "option", None)
        attribute_name = None
        if attribute is not None:
            translation = getattr(attribute, "translation", None)
            attribute_name = getattr(translation, "main_name", None) or getattr(attribute, "name", None)
        attrs.append(
            ProductAttributeItem(
                attribute_id=getattr(attribute, "id", None),
                attribute_name=attribute_name,
                option_id=getattr(option, "id", None),
                option_value_key=getattr(option, "value_key", None),
            )
        )

    prod_schema = ProductWithDefaultPrice.model_validate(product)
    return ProductWithAttributes(product=prod_schema, attributes=attrs)


@router.get(
    "/{product_id}",
    response_model=ProductWithDetailsAndPrices,
    tags=[AgentTag.EXPOSED],
    operation_id="get_product",
    summary="Get product",
    description="Retrieve full product details including all active prices, translations, and images. Public endpoint — no authentication required.",
)
def get_by_id(product_id: UUID, shop_id: UUID) -> ProductWithDetailsAndPrices:
    product = product_crud.get_id_by_shop_id(shop_id, product_id)
    if not product:
        raise_status(HTTPStatus.NOT_FOUND, f"Product with id {product_id} not found")

    product.images_amount = 0
    for i in [1, 2, 3, 4, 5, 6]:
        if getattr(product, f"image_{i}"):
            product.images_amount += 1

    return product
