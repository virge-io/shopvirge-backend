from datetime import datetime
from http import HTTPStatus
from typing import List
from uuid import UUID

import structlog
from fastapi import APIRouter

from server.api.endpoints.shops.common import shop_or_404
from server.api.error_handling import raise_status
from server.crud.crud_shop import shop_crud
from server.db.models import ShopTable
from server.schemas.shop import (
    ShopIp,
    ShopUpdate,
)

logger = structlog.get_logger(__name__)

router = APIRouter()


def _set_allowed_ips(shop: ShopTable, allowed_ips: List[str]) -> List[str]:
    """Persist a new order-submission allow-list; every other shop field is carried over unchanged."""
    shop_crud.update(
        db_obj=shop,
        obj_in=ShopUpdate(
            name=shop.name,
            description=shop.description,
            modified_at=datetime.utcnow(),
            allowed_ips=allowed_ips,
            vat_standard=shop.vat_standard,
            vat_lower_1=shop.vat_lower_1,
            vat_lower_2=shop.vat_lower_2,
            vat_lower_3=shop.vat_lower_3,
            vat_special=shop.vat_special,
            vat_zero=shop.vat_zero,
        ),
    )
    return allowed_ips


@router.get(
    "/allowed-ips/{shop_id}",
    response_model=List[str],
    summary="List allowed IPs",
    description="Returns the list of IP addresses permitted to submit orders to this shop. An empty list means all IPs are allowed.",
)
def get_allowed_ips(shop_id: UUID) -> List[str]:
    return list(shop_or_404(shop_id).allowed_ips or [])


@router.post(
    "/allowed-ips/{shop_id}",
    response_model=List[str],
    summary="Add allowed IP",
    description="Add an IP address to the shop's order submission allowlist. Returns the updated list of allowed IPs.",
)
def add_new_ip(shop_id: UUID, new_ip: ShopIp) -> List[str]:
    shop = shop_or_404(shop_id)
    allowed_ips = list(shop.allowed_ips or [])
    if new_ip.ip in allowed_ips:
        raise_status(HTTPStatus.BAD_REQUEST, f"IP {new_ip.ip} already exists")
    allowed_ips.append(new_ip.ip)
    return _set_allowed_ips(shop, allowed_ips)


@router.post(
    "/allowed-ips/{shop_id}/remove",
    response_model=List[str],
    summary="Remove allowed IP",
    description="Remove an IP address from the shop's order submission allowlist. Returns the updated list.",
)
def remove_ip(shop_id: UUID, old_ip: ShopIp) -> List[str]:
    shop = shop_or_404(shop_id)
    allowed_ips = list(shop.allowed_ips or [])
    if old_ip.ip not in allowed_ips:
        raise_status(HTTPStatus.BAD_REQUEST, f"IP {old_ip.ip} not on list")
    allowed_ips.remove(old_ip.ip)
    return _set_allowed_ips(shop, allowed_ips)
