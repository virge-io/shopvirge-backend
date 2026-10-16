from uuid import UUID

import structlog
from fastapi import APIRouter

from server.agent_tags import AgentTag
from server.api.endpoints.shops.common import shop_or_404
from server.schemas.shop import ShopAbout

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get(
    "/about",
    response_model=ShopAbout,
    tags=[AgentTag.EXPOSED],
    operation_id="get_shop_about",
    summary="Get what a shop is about",
    description=(
        "Returns the shop's own About text (markdown) for each translation slot (`main`, `alt1`, `alt2`), "
        "with the slot's `language_name`. Use it to learn what the shop sells and how it presents itself, "
        "so your answers and any copy you write fit that shop. A slot without a text has `about` null."
    ),
)
def get_about(shop_id: UUID) -> ShopAbout:
    shop = shop_or_404(shop_id)
    return ShopAbout.from_shop(shop.name, shop.config)
