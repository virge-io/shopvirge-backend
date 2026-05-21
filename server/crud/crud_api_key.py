# Copyright 2026 René Dohmen <acidjunk@gmail.com>
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
"""CRUD for ApiKeyTable.

Keys are stored as ``sha256`` of the plaintext; the plaintext leaves the
server exactly once, in the response from :meth:`CRUDApiKey.mint`. Listing
endpoints only ever surface the ``prefix`` so users can identify a key.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from uuid import UUID

from server.db import db
from server.db.models import ApiKeyTable

KEY_PLAINTEXT_PREFIX = "sv"
PREFIX_LEN = 8


def _hash(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def _generate_plaintext() -> Tuple[str, str]:
    """Return ``(plaintext, prefix)``. Prefix is the leading ``PREFIX_LEN`` chars
    of the random body — stored alongside the hash so users can identify a key
    in listings without exposing the full secret."""
    body = secrets.token_urlsafe(32)
    prefix = body[:PREFIX_LEN]
    plaintext = f"{KEY_PLAINTEXT_PREFIX}_{prefix}_{body[PREFIX_LEN:]}"
    return plaintext, prefix


class CRUDApiKey:
    def mint(self, *, shop_id: UUID, name: str, created_by_sub: Optional[str] = None) -> Tuple[ApiKeyTable, str]:
        plaintext, prefix = _generate_plaintext()
        api_key = ApiKeyTable(
            shop_id=shop_id,
            name=name,
            prefix=prefix,
            key_hash=_hash(plaintext),
            created_by_sub=created_by_sub,
        )
        db.session.add(api_key)
        db.session.commit()
        db.session.refresh(api_key)
        return api_key, plaintext

    def lookup_by_plaintext(self, plaintext: str) -> Optional[ApiKeyTable]:
        """Return the key row iff the plaintext matches an active (non-revoked) key.

        Bumps ``last_used_at`` as a side effect.
        """
        if not plaintext or not plaintext.startswith(f"{KEY_PLAINTEXT_PREFIX}_"):
            return None
        key_hash = _hash(plaintext)
        row = db.session.query(ApiKeyTable).filter(ApiKeyTable.key_hash == key_hash).first()
        if row is None or row.revoked_at is not None:
            return None
        row.last_used_at = datetime.now(timezone.utc)
        db.session.commit()
        return row

    def list_by_shop(self, shop_id: UUID) -> List[ApiKeyTable]:
        return (
            db.session.query(ApiKeyTable)
            .filter(ApiKeyTable.shop_id == shop_id)
            .order_by(ApiKeyTable.created_at.desc())
            .all()
        )

    def revoke(self, *, shop_id: UUID, key_id: UUID) -> Optional[ApiKeyTable]:
        row = db.session.query(ApiKeyTable).filter(ApiKeyTable.shop_id == shop_id, ApiKeyTable.id == key_id).first()
        if row is None:
            return None
        if row.revoked_at is None:
            row.revoked_at = datetime.now(timezone.utc)
            db.session.commit()
        return row


api_key_crud = CRUDApiKey()
