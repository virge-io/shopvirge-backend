from uuid import UUID

import structlog

from server.api.route_helpers import get_or_404
from server.crud.crud_shop import shop_crud
from server.db.models import ShopTable

logger = structlog.get_logger(__name__)


def shop_or_404(shop_id: UUID) -> ShopTable:
    return get_or_404(shop_crud.get(shop_id), f"Shop with id {shop_id} not found")
