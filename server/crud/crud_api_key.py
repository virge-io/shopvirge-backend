# Copyright 2026 René Dohmen <acidjunk@gmail.com>
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
"""CRUD for ApiKeyTable.

Two-layer storage: sha256 fingerprint for indexed lookup, bcrypt hash for
verification. A DB dump alone cannot yield usable keys — even if SHA256 is
weakened, the bcrypt round still has to be brute-forced per row.

The plaintext leaves the server exactly once, in the response from
:meth:`CRUDApiKey.mint`. Listing endpoints surface only the ``prefix`` so
users can identify a key.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from uuid import UUID

import bcrypt as _bcrypt
from sqlalchemy import update

from server.db import db
from server.db.models import ApiKeyTable
from server.settings import app_settings

KEY_PLAINTEXT_PREFIX = "sv"
PREFIX_LEN = 8


def _bcrypt_hash(plaintext: str) -> str:
    return _bcrypt.hashpw(plaintext.encode("utf-8")[:72], _bcrypt.gensalt()).decode("utf-8")


def _bcrypt_verify(plaintext: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plaintext.encode("utf-8")[:72], hashed.encode("utf-8"))


def _fingerprint(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def _should_record_use(last_used_at: Optional[datetime], now: datetime) -> bool:
    """Whether ``last_used_at`` is stale enough to be written again (see ``API_KEY_LAST_USED_WRITE_INTERVAL``)."""
    if last_used_at is None:
        return True
    return (now - last_used_at).total_seconds() >= app_settings.API_KEY_LAST_USED_WRITE_INTERVAL


def _generate_plaintext() -> Tuple[str, str]:
    """Return ``(plaintext, prefix)``. Prefix is the leading ``PREFIX_LEN`` chars
    of the random body — stored alongside so users can identify a key in
    listings without exposing the full secret.
    """
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
            fingerprint=_fingerprint(plaintext),
            encrypted_key=_bcrypt_hash(plaintext),
            created_by_sub=created_by_sub,
        )
        db.session.add(api_key)
        db.session.commit()
        db.session.refresh(api_key)
        return api_key, plaintext

    def lookup_by_plaintext(self, plaintext: str) -> Optional[ApiKeyTable]:
        """Return the key row iff the plaintext matches an active (non-revoked) key.

        Sha256 fingerprint narrows the lookup to one row; bcrypt-verify confirms the
        plaintext. ``last_used_at`` is bumped at most once per
        ``API_KEY_LAST_USED_WRITE_INTERVAL``, so authenticating is normally one SELECT
        and no write. bcrypt is CPU-bound for a good fraction of a second: call this
        from a worker thread, never on the event loop.
        """
        if not plaintext or not plaintext.startswith(f"{KEY_PLAINTEXT_PREFIX}_"):
            return None
        row = db.session.query(ApiKeyTable).filter(ApiKeyTable.fingerprint == _fingerprint(plaintext)).first()
        if row is None or row.revoked_at is not None:
            return None
        # bcrypt takes a good fraction of a second; detach the (fully loaded) row and give the pooled
        # connection back for the duration instead of sitting idle in a transaction.
        db.session.expunge(row)
        db.release_connection()
        if not _bcrypt_verify(plaintext, row.encrypted_key):
            return None
        now = datetime.now(timezone.utc)
        if _should_record_use(row.last_used_at, now):
            db.session.execute(update(ApiKeyTable).where(ApiKeyTable.id == row.id).values(last_used_at=now))
            db.session.commit()
            row.last_used_at = now
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
