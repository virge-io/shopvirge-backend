from typing import Tuple
from uuid import UUID

from server.crud.crud_api_key import api_key_crud
from server.db.models import ApiKeyTable


def make_api_key(
    shop_id: UUID,
    *,
    name: str = "test-key",
    created_by_sub: str = "test-user",
) -> Tuple[ApiKeyTable, str]:
    """Mint an API key for ``shop_id`` and return ``(row, plaintext)``.

    Plaintext is only available from the return value — the DB stores only
    the bcrypt hash + sha256 fingerprint.
    """
    return api_key_crud.mint(shop_id=shop_id, name=name, created_by_sub=created_by_sub)
