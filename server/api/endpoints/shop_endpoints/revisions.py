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
"""Revision history, restore and trash endpoints for the PIM."""

from typing import Any, List, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.param_functions import Depends
from starlette.responses import Response

from server.agent_tags import AgentTag
from server.db import db
from server.db.models import ApiKeyTable, CategoryTable, ProductTable, ProductTranslationTable, RevisionTable
from server.schemas.revision import RestoreReport, RevisionDetail, RevisionSummary, TrashItem
from server.security import auth_required_any
from server.services.restore import (
    restore_category_from_trash,
    restore_product_from_trash,
    restore_product_revision,
)
from server.services.revisions import ENTITY_ATTRIBUTE, ENTITY_CATEGORY, ENTITY_PRODUCT, ENTITY_TAG, actor

logger = structlog.get_logger(__name__)

router = APIRouter()

_ENTITY_TYPES = (ENTITY_PRODUCT, ENTITY_CATEGORY, ENTITY_TAG, ENTITY_ATTRIBUTE)


def _snapshot_name(revision: RevisionTable) -> Optional[str]:
    data = revision.data or {}
    translation = data.get("translation") or {}
    if translation.get("main_name"):
        return translation["main_name"]
    # Tags and attributes also carry a machine-friendly name on the entity itself
    entity = data.get(revision.entity_type) or {}
    return entity.get("name")


def _summaries(shop_id: UUID, entity_type: str, entity_id: UUID) -> List[RevisionSummary]:
    revisions = (
        db.session.query(RevisionTable)
        .filter(
            RevisionTable.shop_id == shop_id,
            RevisionTable.entity_type == entity_type,
            RevisionTable.entity_id == entity_id,
        )
        .order_by(RevisionTable.revision_no.desc())
        .all()
    )
    out = []
    for revision in revisions:
        summary = RevisionSummary.model_validate(revision)
        summary.name = _snapshot_name(revision)
        out.append(summary)
    return out


@router.get(
    "/revisions",
    response_model=List[RevisionSummary],
    tags=[AgentTag.EXPOSED, AgentTag.LARGE],
    operation_id="list_shop_revisions",
    summary="List all revisions in a shop",
    description=(
        "Shop-wide change feed: every recorded revision of every product, category, tag and attribute, "
        "newest first. Supports filtering by `entity_type` (product | category | tag | attribute), "
        "`entity_id`, `action` (create | update | delete | restore | baseline), `source` (rest | mcp) and "
        "`created_by`, plus `skip`/`limit` pagination (the total is returned in the Content-Range header). "
        "Use `get_revision` to inspect a revision's full snapshot."
    ),
)
def list_shop_revisions(
    shop_id: UUID,
    response: Response,
    entity_type: Optional[str] = Query(None, description="Filter: product | category | tag | attribute."),
    entity_id: Optional[UUID] = Query(None, description="Filter on one specific entity."),
    action: Optional[str] = Query(None, description="Filter: create | update | delete | restore | baseline."),
    source: Optional[str] = Query(None, description="Filter: rest | mcp."),
    created_by: Optional[str] = Query(None, description='Filter on actor, e.g. "api_key:<uuid>" or "cognito:<sub>".'),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> List[RevisionSummary]:
    if entity_type is not None and entity_type not in _ENTITY_TYPES:
        raise HTTPException(status_code=422, detail=f"entity_type must be one of {', '.join(_ENTITY_TYPES)}")

    query = db.session.query(RevisionTable).filter(RevisionTable.shop_id == shop_id)
    if entity_type is not None:
        query = query.filter(RevisionTable.entity_type == entity_type)
    if entity_id is not None:
        query = query.filter(RevisionTable.entity_id == entity_id)
    if action is not None:
        query = query.filter(RevisionTable.action == action)
    if source is not None:
        query = query.filter(RevisionTable.source == source)
    if created_by is not None:
        query = query.filter(RevisionTable.created_by == created_by)

    total = query.count()
    revisions = (
        query.order_by(RevisionTable.created_at.desc(), RevisionTable.revision_no.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    response.headers["Content-Range"] = f"revisions {skip}-{skip + len(revisions) - 1}/{total}"

    out = []
    for revision in revisions:
        summary = RevisionSummary.model_validate(revision)
        summary.name = _snapshot_name(revision)
        out.append(summary)
    return out


@router.get(
    "/revisions/{revision_id}",
    response_model=RevisionDetail,
    tags=[AgentTag.EXPOSED],
    operation_id="get_revision",
    summary="Get one revision by id",
    description=(
        "Returns one revision (of any entity type) by its id, including the full snapshot data. "
        "Use it to inspect entries from the `list_shop_revisions` feed."
    ),
)
def get_revision(shop_id: UUID, revision_id: UUID) -> RevisionDetail:
    revision = (
        db.session.query(RevisionTable)
        .filter(RevisionTable.shop_id == shop_id, RevisionTable.id == revision_id)
        .first()
    )
    if revision is None:
        raise HTTPException(status_code=404, detail=f"Revision {revision_id} not found")
    detail = RevisionDetail.model_validate(revision)
    detail.name = _snapshot_name(revision)
    return detail


@router.get(
    "/products/{product_id}/revisions",
    response_model=List[RevisionSummary],
    tags=[AgentTag.EXPOSED, AgentTag.LARGE],
    operation_id="list_product_revisions",
    summary="List product revisions",
    description=(
        "Returns the revision history of a product, newest first. Every change to the product "
        "(fields, translation, tags, attribute values, images) recorded one revision. Use "
        "`get_product_revision` to inspect a revision and `restore_product_revision` to roll back to it."
    ),
)
def list_product_revisions(shop_id: UUID, product_id: UUID) -> List[RevisionSummary]:
    return _summaries(shop_id, ENTITY_PRODUCT, product_id)


@router.get(
    "/products/{product_id}/revisions/{revision_no}",
    response_model=RevisionDetail,
    tags=[AgentTag.EXPOSED],
    operation_id="get_product_revision",
    summary="Get product revision",
    description="Returns one product revision including the full snapshot data (all fields, tags, attribute values and image references at that point in time).",
)
def get_product_revision(shop_id: UUID, product_id: UUID, revision_no: int) -> RevisionDetail:
    revision = (
        db.session.query(RevisionTable)
        .filter(
            RevisionTable.shop_id == shop_id,
            RevisionTable.entity_type == ENTITY_PRODUCT,
            RevisionTable.entity_id == product_id,
            RevisionTable.revision_no == revision_no,
        )
        .first()
    )
    if revision is None:
        raise HTTPException(status_code=404, detail=f"Revision {revision_no} not found for product {product_id}")
    detail = RevisionDetail.model_validate(revision)
    detail.name = _snapshot_name(revision)
    return detail


@router.post(
    "/products/{product_id}/revisions/{revision_no}/restore",
    response_model=RestoreReport,
    tags=[AgentTag.EXPOSED],
    operation_id="restore_product_revision",
    summary="Restore product to a revision",
    description=(
        "Rolls the product back to the state captured in the given revision: fields, translation, "
        "category, tags, attribute values and image references. Soft-deleted categories/tags/attributes "
        "referenced by the snapshot are automatically restored from the trash; references that were "
        "permanently purged are matched by name where possible, otherwise reported in `unresolved`. "
        "The restore itself is recorded as a new revision, so it can be undone too. Read the returned "
        "report to see what could not be brought back."
    ),
)
def restore_product_revision_endpoint(
    shop_id: UUID,
    product_id: UUID,
    revision_no: int,
    request: Request,
    force: bool = Query(
        False,
        description="Recreate the product from the snapshot even if it was permanently purged (user credentials required).",
    ),
    principal: Any = Depends(auth_required_any),
) -> RestoreReport:
    if force and isinstance(principal, ApiKeyTable):
        raise HTTPException(
            status_code=403,
            detail="Recreating a purged product requires user credentials; API keys cannot use force=true.",
        )
    created_by, source = actor(principal, request)
    return restore_product_revision(
        shop_id=shop_id,
        product_id=product_id,
        revision_no=revision_no,
        allow_recreate=force,
        created_by=created_by,
        source=source,
    )


@router.post(
    "/products/{product_id}/restore",
    response_model=RestoreReport,
    tags=[AgentTag.EXPOSED],
    operation_id="restore_product",
    summary="Restore product from trash",
    description=(
        "Brings a trashed (deleted) product back, including its tags and attribute values. "
        "If the product's category is also in the trash it is restored as well."
    ),
)
def restore_product_endpoint(
    shop_id: UUID,
    product_id: UUID,
    request: Request,
    principal: Any = Depends(auth_required_any),
) -> RestoreReport:
    created_by, source = actor(principal, request)
    return restore_product_from_trash(shop_id=shop_id, product_id=product_id, created_by=created_by, source=source)


@router.get(
    "/categories/{category_id}/revisions",
    response_model=List[RevisionSummary],
    summary="List category revisions",
    description="Returns the revision history of a category, newest first.",
)
def list_category_revisions(shop_id: UUID, category_id: UUID) -> List[RevisionSummary]:
    return _summaries(shop_id, ENTITY_CATEGORY, category_id)


@router.post(
    "/categories/{category_id}/restore",
    response_model=RestoreReport,
    tags=[AgentTag.EXPOSED],
    operation_id="restore_category",
    summary="Restore category from trash",
    description=(
        "Brings a trashed (deleted) category back. With `restore_products=true` (default) it also "
        "restores every product that was moved to the trash together with the category by a "
        "`delete_category` with `force=true`."
    ),
)
def restore_category_endpoint(
    shop_id: UUID,
    category_id: UUID,
    request: Request,
    restore_products: bool = Query(True, description="Also restore the products trashed together with this category."),
    principal: Any = Depends(auth_required_any),
) -> RestoreReport:
    created_by, source = actor(principal, request)
    return restore_category_from_trash(
        shop_id=shop_id,
        category_id=category_id,
        restore_products=restore_products,
        created_by=created_by,
        source=source,
    )


@router.get(
    "/trash",
    response_model=List[TrashItem],
    summary="List trashed products and categories",
    description="Returns all soft-deleted products and categories of the shop, so they can be inspected and restored.",
)
def list_trash(shop_id: UUID) -> List[TrashItem]:
    items: List[TrashItem] = []

    products = (
        db.session.query(ProductTable)
        .filter(ProductTable.shop_id == shop_id, ProductTable.deleted_at.isnot(None))
        .execution_options(include_deleted=True)
        .all()
    )
    for product in products:
        translation = (
            db.session.query(ProductTranslationTable).filter(ProductTranslationTable.product_id == product.id).first()
        )
        items.append(
            TrashItem(
                entity_type=ENTITY_PRODUCT,
                id=product.id,
                name=translation.main_name if translation else None,
                deleted_at=product.deleted_at,
                deleted_batch_id=product.deleted_batch_id,
            )
        )

    categories = (
        db.session.query(CategoryTable)
        .filter(CategoryTable.shop_id == shop_id, CategoryTable.deleted_at.isnot(None))
        .execution_options(include_deleted=True)
        .all()
    )
    for category in categories:
        items.append(
            TrashItem(
                entity_type=ENTITY_CATEGORY,
                id=category.id,
                name=category.translation.main_name if category.translation else None,
                deleted_at=category.deleted_at,
            )
        )

    items.sort(key=lambda item: (item.deleted_at is None, item.deleted_at), reverse=True)
    return items
