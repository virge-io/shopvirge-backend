# Copyright 2026 René Dohmen <acidjunk@gmail.com>
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
"""Aggregate revision snapshots for PIM entities (products, categories).

Every mutation of a product aggregate — the product row, its translation, its
tag links, its attribute values or its image slots — records one row in the
``revisions`` table holding a full JSON snapshot of the aggregate. Restoring a
revision (see ``server/services/restore.py``) deserializes that snapshot and
re-applies it.

Robustness against model churn is structural, not per-field: the serializer
iterates the model's mapped columns at runtime, so newly added columns are
snapshotted automatically with zero code change here. Restore applies only the
intersection of snapshot keys and current columns and reports the difference.
``SCHEMA_VERSION`` only needs a bump (plus an entry in
``server/services/restore.py::UPCONVERTERS``) for *structural* reshapes of the
snapshot dict — renamed or re-nested keys — never for plain column changes.

Transactions: ``record_*_revision`` only ``session.add()``s the revision row and
prunes old ones — it never commits. The calling endpoint owns the transaction
and must hold a ``FOR UPDATE`` row lock on the entity (via
``get_id_by_shop_id(..., for_update=True)``) so that revision numbering is
race-free under concurrent writers.
"""

from typing import Any, Optional, Tuple
from uuid import UUID

import structlog
from fastapi import Request
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func
from sqlalchemy.inspection import inspect as sa_inspect

from server.db import db
from server.db.models import CategoryTable, ProductTable, RevisionTable
from server.settings import app_settings

logger = structlog.get_logger(__name__)

SCHEMA_VERSION = 1

ENTITY_PRODUCT = "product"
ENTITY_CATEGORY = "category"

# Lifecycle/identity fields that are not part of an entity's content
_EXCLUDED_KEYS = {"id", "shop_id", "deleted_at", "deleted_batch_id"}
_EXCLUDED_TRANSLATION_KEYS = {"id", "product_id", "category_id"}

# Minimum revisions to keep regardless of settings — the PIM undo story assumes it.
_MIN_RETENTION = 10


def retention() -> int:
    return max(app_settings.REVISION_RETENTION, _MIN_RETENTION)


def actor(principal: Any = None, request: Optional[Request] = None) -> Tuple[Optional[str], str]:
    """Derive (created_by, source) from the auth principal and the incoming request.

    ``principal`` is whatever ``auth_required_any`` returned: an ``ApiKeyTable`` row
    for API-key clients or a ``CustomCognitoToken`` for Cognito users. MCP calls are
    detected via the ``mcp-session-id`` header that fastmcp forwards into the
    in-process request.
    """
    from server.db.models import ApiKeyTable

    created_by = None
    if isinstance(principal, ApiKeyTable):
        created_by = f"api_key:{principal.id}"
    elif principal is not None and getattr(principal, "cognito_id", None):
        created_by = f"cognito:{principal.cognito_id}"

    source = "mcp" if request is not None and request.headers.get("mcp-session-id") else "rest"
    return created_by, source


def _columns_snapshot(obj: Any, excluded: set[str]) -> dict:
    """Snapshot every mapped column of ``obj`` (minus ``excluded``) as JSON-able values."""
    keys = [k for k in sa_inspect(type(obj)).columns.keys() if k not in excluded]
    return {key: jsonable_encoder(getattr(obj, key)) for key in keys}


def snapshot_product(product: ProductTable) -> dict:
    """Serialize the full product aggregate. Call after ``session.flush()`` so pending changes are visible."""
    translation = product.translation
    category = product.category

    category_name = None
    if category is not None and category.translation is not None:
        category_name = category.translation.main_name

    return {
        "product": _columns_snapshot(product, _EXCLUDED_KEYS),
        "translation": _columns_snapshot(translation, _EXCLUDED_TRANSLATION_KEYS) if translation else None,
        "category": (
            {"id": jsonable_encoder(category.id), "name": category_name}
            if category is not None
            else ({"id": jsonable_encoder(product.category_id), "name": None} if product.category_id else None)
        ),
        "tags": [{"id": jsonable_encoder(tag.id), "name": tag.name} for tag in (product.tags or [])],
        "attribute_values": [
            {
                "attribute_id": jsonable_encoder(pav.attribute_id),
                "attribute_name": pav.attribute.name if pav.attribute else None,
                "option_id": jsonable_encoder(pav.option_id),
                "option_value_key": pav.option.value_key if pav.option else None,
            }
            for pav in (product.attribute_values or [])
        ],
    }


def snapshot_category(category: CategoryTable) -> dict:
    translation = category.translation
    return {
        "category": _columns_snapshot(category, _EXCLUDED_KEYS),
        "translation": _columns_snapshot(translation, _EXCLUDED_TRANSLATION_KEYS) if translation else None,
    }


def _next_revision_no(entity_type: str, entity_id: UUID) -> int:
    current = (
        db.session.query(func.max(RevisionTable.revision_no))
        .filter(RevisionTable.entity_type == entity_type, RevisionTable.entity_id == entity_id)
        .scalar()
    )
    return (current or 0) + 1


def _prune(entity_type: str, entity_id: UUID, latest_no: int) -> None:
    cutoff = latest_no - retention()
    if cutoff <= 0:
        return
    (
        db.session.query(RevisionTable)
        .filter(
            RevisionTable.entity_type == entity_type,
            RevisionTable.entity_id == entity_id,
            RevisionTable.revision_no <= cutoff,
        )
        .delete(synchronize_session=False)
    )


def _record_revision(
    *,
    shop_id: UUID,
    entity_type: str,
    entity_id: UUID,
    action: str,
    data: dict,
    created_by: Optional[str],
    source: str,
) -> RevisionTable:
    revision_no = _next_revision_no(entity_type, entity_id)
    revision = RevisionTable(
        shop_id=shop_id,
        entity_type=entity_type,
        entity_id=entity_id,
        revision_no=revision_no,
        action=action,
        schema_version=SCHEMA_VERSION,
        data=data,
        created_by=created_by,
        source=source,
    )
    db.session.add(revision)
    _prune(entity_type, entity_id, revision_no)
    logger.info(
        "Recorded revision",
        entity_type=entity_type,
        entity_id=str(entity_id),
        revision_no=revision_no,
        action=action,
        created_by=created_by,
        source=source,
    )
    return revision


def _has_revision(entity_type: str, entity_id: UUID) -> bool:
    query = db.session.query(RevisionTable.id).filter(
        RevisionTable.entity_type == entity_type, RevisionTable.entity_id == entity_id
    )
    return db.session.query(query.exists()).scalar()


def _ensure_baseline(entity_type: str, entity: Any, snapshot: Any) -> Optional[RevisionTable]:
    # Autoflush stays off for the whole capture so mutations already pending in the
    # session (new tag links, attribute values) cannot leak into the baseline.
    with db.session.no_autoflush:
        if _has_revision(entity_type, entity.id):
            return None
        return _record_revision(
            shop_id=entity.shop_id,
            entity_type=entity_type,
            entity_id=entity.id,
            action="baseline",
            data=snapshot(entity),
            created_by=None,
            source="rest",
        )


def ensure_baseline_product_revision(product: ProductTable) -> Optional[RevisionTable]:
    """Capture the pre-mutation state of a product that predates the revisions feature.

    Entities created before revision tracking shipped have no revision rows, so their
    first edit would otherwise be un-undoable: the first recorded revision would hold
    the *post*-edit state. This records the current state as revision 1
    (``action="baseline"``) and is a no-op once any revision exists.

    Call it BEFORE applying the mutation: in-memory column changes are visible to the
    snapshot regardless of flushing. ``created_by`` stays empty because the captured
    state was authored before tracking existed, not by the actor triggering the capture.
    Deletes don't need a baseline — a delete revision already snapshots the pre-delete state.
    """
    return _ensure_baseline(ENTITY_PRODUCT, product, snapshot_product)


def ensure_baseline_category_revision(category: CategoryTable) -> Optional[RevisionTable]:
    """Category counterpart of ``ensure_baseline_product_revision`` — same contract."""
    return _ensure_baseline(ENTITY_CATEGORY, category, snapshot_category)


def record_product_revision(
    product: ProductTable,
    *,
    action: str,
    created_by: Optional[str] = None,
    source: str = "rest",
    extra_data: Optional[dict] = None,
) -> RevisionTable:
    """Record a snapshot of the product aggregate. Does NOT commit — the caller owns the transaction."""
    # Make sure pending mutations are visible and relationship caches (tags,
    # attribute_values) are not stale from before the mutation.
    db.session.flush()
    db.session.expire(product)
    data = snapshot_product(product)
    if extra_data:
        data.update(extra_data)
    return _record_revision(
        shop_id=product.shop_id,
        entity_type=ENTITY_PRODUCT,
        entity_id=product.id,
        action=action,
        data=data,
        created_by=created_by,
        source=source,
    )


def record_category_revision(
    category: CategoryTable,
    *,
    action: str,
    created_by: Optional[str] = None,
    source: str = "rest",
    extra_data: Optional[dict] = None,
) -> RevisionTable:
    """Record a snapshot of the category. Does NOT commit — the caller owns the transaction."""
    db.session.flush()
    db.session.expire(category)
    data = snapshot_category(category)
    if extra_data:
        data.update(extra_data)
    return _record_revision(
        shop_id=category.shop_id,
        entity_type=ENTITY_CATEGORY,
        entity_id=category.id,
        action=action,
        data=data,
        created_by=created_by,
        source=source,
    )
