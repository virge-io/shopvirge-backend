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
from typing import List, Optional, Union
from uuid import UUID

import structlog
from fastapi import HTTPException, Request

from server.db.models import ShopTable

logger = structlog.get_logger(__name__)


def convert_price_string_to_float(price: str) -> Union[float, None]:
    try:
        price = price.replace(",", ".")
        return float(price)
    except ValueError:
        return None


def validate_uuid4(uuid_string):
    """
    Validate that a UUID string is in
    fact a valid uuid4.
    Happily, the uuid module does the actual
    checking for us.
    It is vital that the 'version' kwarg be passed
    to the UUID() call, otherwise any 32-character
    hex string is considered valid.
    """

    try:
        val = UUID(uuid_string, version=4)
    except ValueError:
        # If it's a value error, then the string
        # is not a valid hex code for a UUID.
        return False

    # If the uuid_string is a valid hex code,
    # but an invalid uuid4,
    # the UUID.__init__ will convert it to a
    # valid uuid4. This is bad for validation purposes.

    return str(val) == uuid_string


def is_ip_allowed(request: Request, shop):
    allowed_ips = shop.allowed_ips
    ip = str(request.client.host)
    shop_id = str(shop.id)
    if not allowed_ips:
        # IP checking isn't activated
        logger.info("IP check isn't activated for shop", shop_name=shop.name, shop_id=shop_id, ip=ip)
        return True
    if ip in shop.allowed_ips:
        logger.info("IP check OK for shop", shop_name=shop.name, shop_id=shop_id, ip=ip, allowed_ips=allowed_ips)
        return True
    logger.warning("IP is not allowed to order", shop_name=shop.name, shop_id=shop_id, ip=ip, allowed_ips=allowed_ips)
    return False
