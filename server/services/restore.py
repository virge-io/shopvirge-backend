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
"""Restore PIM entities from revision snapshots and from the trash.

Restore is designed to never crash on missing references. For every reference
in the snapshot (category, tags, attributes, options) the resolution order is:

1. by id, including soft-deleted rows — soft-deleted rows are resurrected
   (``deleted_at`` cleared) and reported in ``RestoreReport.resurrected``;
2. by denormalized name stored in the snapshot (attribute ``name`` and option
   ``value_key`` are unique per shop/attribute) — covers hard-purged rows that
   were recreated under a new id;
3. otherwise the reference is dropped and reported in
   ``RestoreReport.unresolved``.

Snapshot fields that no longer exist on the current model (model churn) are
skipped and reported in ``RestoreReport.skipped_fields``. Old snapshots are
up-converted through ``UPCONVERTERS`` before being applied: for every structural
schema bump N -> N+1 register a ``UPCONVERTERS[N] = lambda data: ...`` that
returns the version-N+1 shape. Plain column additions/removals never need an
up-converter.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Optional

import structlog
from fastapi import HTTPException
from sqlalchemy.inspection import inspect as sa_inspect

from server.db import db
from server.db.models import (
    AttributeOptionTable,
    AttributeTable,
    AttributeTranslationTable,
    CategoryTable,
    CategoryTranslationTable,
    ProductTable,
    ProductToTagTable,
    ProductTranslationTable,
    RevisionTable,
    TagTable,
    TagTranslationTable,
)
from server.schemas.revision import RestoreReport, ResurrectedEntity, UnresolvedReference
from server.services.revisions import (
    ENTITY_ATTRIBUTE,
    ENTITY_CATEGORY,
    ENTITY_PRODUCT,
    ENTITY_TAG,
    SCHEMA_VERSION,
    record_attribute_revision,
    record_category_revision,
    record_product_revision,
    record_tag_revision,
)

logger = structlog.get_logger(__name__)

# Structural snapshot up-converters: UPCONVERTERS[n] converts a version-n snapshot
# dict into the version-(n+1) shape. v1 is current, so this is empty.
UPCONVERTERS: dict[int, Callable[[dict], dict]] = {}

# Identity/lifecycle fields never applied from a snapshot
_NEVER_APPLY = {"id", "shop_id", "deleted_at", "deleted_batch_id", "created_at", "modified_at"}


def _upconvert(data: dict, from_version: int) -> dict:
    version = from_version
    while version < SCHEMA_VERSION:
        converter = UPCONVERTERS.get(version)
        if converter is None:
            raise HTTPException(
                status_code=422,
                detail=f"Cannot restore: no up-converter registered for snapshot schema_version {version}",
            )
        data = converter(data)
        version += 1
    return data


def _coerce(model: Any, key: str, value: Any) -> Any:
    """Coerce a JSON snapshot value back to the column's python type."""
    if value is None:
        return None
    column = sa_inspect(model).columns[key]
    try:
        python_type = column.type.python_type
    except NotImplementedError:
        return value
    if python_type is datetime and isinstance(value, str):
        return datetime.fromisoformat(value)
    if python_type is Decimal and isinstance(value, (int, float, str)):
        return Decimal(str(value))
    if python_type is uuid.UUID and isinstance(value, str):
        return uuid.UUID(value)
    return value


def _apply_columns(
    obj: Any, snapshot: dict, prefix: str, report: RestoreReport, skip: Optional[set[str]] = None
) -> None:
    """Apply snapshot keys that still exist as columns; report the rest as skipped."""
    current_columns = set(sa_inspect(type(obj)).columns.keys())
    for key, value in snapshot.items():
        if key in _NEVER_APPLY or (skip and key in skip):
            continue
        if key in current_columns:
            setattr(obj, key, _coerce(type(obj), key, value))
        else:
            report.skipped_fields.append(f"{prefix}.{key}")


def _get_revision(shop_id: uuid.UUID, entity_type: str, entity_id: uuid.UUID, revision_no: int) -> RevisionTable:
    revision = (
        db.session.query(RevisionTable)
        .filter(
            RevisionTable.shop_id == shop_id,
            RevisionTable.entity_type == entity_type,
            RevisionTable.entity_id == entity_id,
            RevisionTable.revision_no == revision_no,
        )
        .first()
    )
    if revision is None:
        raise HTTPException(status_code=404, detail=f"Revision {revision_no} not found for {entity_type} {entity_id}")
    return revision


def _resolve_category(
    shop_id: uuid.UUID, cat_ref: Optional[dict], product: ProductTable, report: RestoreReport
) -> None:
    if not cat_ref or not (cat_ref.get("id") or cat_ref.get("name")):
        product.category_id = None
        return

    category = None
    if cat_ref.get("id"):
        category = (
            db.session.query(CategoryTable)
            .filter(CategoryTable.shop_id == shop_id, CategoryTable.id == uuid.UUID(cat_ref["id"]))
            .execution_options(include_deleted=True)
            .first()
        )
    if category is None and cat_ref.get("name"):
        category = (
            db.session.query(CategoryTable)
            .join(CategoryTranslationTable, CategoryTranslationTable.category_id == CategoryTable.id)
            .filter(CategoryTable.shop_id == shop_id, CategoryTranslationTable.main_name == cat_ref["name"])
            .execution_options(include_deleted=True)
            .first()
        )

    if category is None:
        product.category_id = None
        report.unresolved.append(UnresolvedReference(kind="category", id=cat_ref.get("id"), name=cat_ref.get("name")))
        return

    if category.deleted_at is not None:
        category.deleted_at = None
        report.resurrected.append(ResurrectedEntity(kind="category", id=category.id, name=cat_ref.get("name")))
    product.category_id = category.id


def _resolve_tags(shop_id: uuid.UUID, snapshot_tags: list, product: ProductTable, report: RestoreReport) -> None:
    resolved_tag_ids: list[uuid.UUID] = []
    for tag_ref in snapshot_tags or []:
        tag = None
        if tag_ref.get("id"):
            tag = (
                db.session.query(TagTable)
                .filter(TagTable.shop_id == shop_id, TagTable.id == uuid.UUID(tag_ref["id"]))
                .execution_options(include_deleted=True)
                .first()
            )
        if tag is None and tag_ref.get("name"):
            tag = (
                db.session.query(TagTable)
                .filter(TagTable.shop_id == shop_id, TagTable.name == tag_ref["name"])
                .execution_options(include_deleted=True)
                .first()
            )
        if tag is None:
            report.unresolved.append(UnresolvedReference(kind="tag", id=tag_ref.get("id"), name=tag_ref.get("name")))
            continue
        if tag.deleted_at is not None:
            tag.deleted_at = None
            report.resurrected.append(ResurrectedEntity(kind="tag", id=tag.id, name=tag.name))
        resolved_tag_ids.append(tag.id)

    # Replace-all semantics; products_to_tags has no unique constraint, so dedupe by
    # querying the existing links first.
    existing_links = db.session.query(ProductToTagTable).filter(ProductToTagTable.product_id == product.id).all()
    existing_by_tag = {}
    for link in existing_links:
        if link.tag_id in existing_by_tag or link.tag_id not in resolved_tag_ids:
            db.session.delete(link)
        else:
            existing_by_tag[link.tag_id] = link
    for tag_id in resolved_tag_ids:
        if tag_id not in existing_by_tag:
            db.session.add(ProductToTagTable(shop_id=shop_id, product_id=product.id, tag_id=tag_id))


def _resolve_attribute_values(
    shop_id: uuid.UUID, snapshot_values: list, product: ProductTable, report: RestoreReport
) -> None:
    from server.db.models import ProductAttributeValueTable

    desired: set[tuple[uuid.UUID, Optional[uuid.UUID]]] = set()
    for value_ref in snapshot_values or []:
        attribute = None
        if value_ref.get("attribute_id"):
            attribute = (
                db.session.query(AttributeTable)
                .filter(AttributeTable.shop_id == shop_id, AttributeTable.id == uuid.UUID(value_ref["attribute_id"]))
                .execution_options(include_deleted=True)
                .first()
            )
        if attribute is None and value_ref.get("attribute_name"):
            attribute = (
                db.session.query(AttributeTable)
                .filter(AttributeTable.shop_id == shop_id, AttributeTable.name == value_ref["attribute_name"])
                .execution_options(include_deleted=True)
                .first()
            )
        if attribute is None:
            report.unresolved.append(
                UnresolvedReference(
                    kind="attribute", id=value_ref.get("attribute_id"), name=value_ref.get("attribute_name")
                )
            )
            continue
        if attribute.deleted_at is not None:
            attribute.deleted_at = None
            report.resurrected.append(ResurrectedEntity(kind="attribute", id=attribute.id, name=attribute.name))

        option = None
        wants_option = bool(value_ref.get("option_id") or value_ref.get("option_value_key"))
        if value_ref.get("option_id"):
            option = (
                db.session.query(AttributeOptionTable)
                .filter(
                    AttributeOptionTable.id == uuid.UUID(value_ref["option_id"]),
                    AttributeOptionTable.attribute_id == attribute.id,
                )
                .execution_options(include_deleted=True)
                .first()
            )
        if option is None and value_ref.get("option_value_key"):
            option = (
                db.session.query(AttributeOptionTable)
                .filter(
                    AttributeOptionTable.attribute_id == attribute.id,
                    AttributeOptionTable.value_key == value_ref["option_value_key"],
                )
                .execution_options(include_deleted=True)
                .first()
            )
        if wants_option and option is None:
            report.unresolved.append(
                UnresolvedReference(
                    kind="attribute_option", id=value_ref.get("option_id"), name=value_ref.get("option_value_key")
                )
            )
            continue
        if option is not None and option.deleted_at is not None:
            option.deleted_at = None
            report.resurrected.append(ResurrectedEntity(kind="attribute_option", id=option.id, name=option.value_key))

        desired.add((attribute.id, option.id if option else None))

    # Replace-all: diff against existing PAVs so the unique constraint can never fire.
    existing = (
        db.session.query(ProductAttributeValueTable).filter(ProductAttributeValueTable.product_id == product.id).all()
    )
    existing_keys = set()
    for pav in existing:
        key = (pav.attribute_id, pav.option_id)
        if key not in desired or key in existing_keys:
            db.session.delete(pav)
        else:
            existing_keys.add(key)
    for attribute_id, option_id in desired - existing_keys:
        db.session.add(
            ProductAttributeValueTable(product_id=product.id, attribute_id=attribute_id, option_id=option_id)
        )


def restore_product_revision(
    *,
    shop_id: uuid.UUID,
    product_id: uuid.UUID,
    revision_no: int,
    allow_recreate: bool = False,
    created_by: Optional[str] = None,
    source: str = "rest",
) -> RestoreReport:
    """Re-apply a product revision snapshot. Commits on success, rolls back on error."""
    report = RestoreReport(restored=False, entity_type=ENTITY_PRODUCT, entity_id=product_id)
    report.restored_from_revision_no = revision_no

    revision = _get_revision(shop_id, ENTITY_PRODUCT, product_id, revision_no)
    data = _upconvert(dict(revision.data), revision.schema_version)

    product = (
        db.session.query(ProductTable)
        .filter(ProductTable.shop_id == shop_id, ProductTable.id == product_id)
        .execution_options(include_deleted=True)
        .with_for_update()
        .first()
    )
    # Control-flow errors are raised before the mutation phase so the rollback
    # handler below only ever fires on genuine mid-mutation failures.
    if product is None and not allow_recreate:
        raise HTTPException(
            status_code=410,
            detail=(
                "Product was permanently purged. Retry with force=true (user credentials required) "
                "to recreate it from the snapshot."
            ),
        )

    try:
        if product is None:
            product = ProductTable(id=product_id, shop_id=shop_id)
            db.session.add(product)
            report.warnings.append("Product row was purged; recreated from the snapshot.")

        if product.deleted_at is not None:
            report.resurrected.append(ResurrectedEntity(kind="product", id=product.id))
        product.deleted_at = None
        product.deleted_batch_id = None

        # category_id is deliberately skipped here: it may point at a purged category,
        # so it is resolved (and possibly resurrected) by _resolve_category below.
        _apply_columns(product, data.get("product") or {}, "product", report, skip={"category_id"})
        product.modified_at = datetime.now(timezone.utc)

        translation_data = data.get("translation")
        if translation_data:
            translation = (
                db.session.query(ProductTranslationTable)
                .filter(ProductTranslationTable.product_id == product.id)
                .first()
            )
            if translation is None:
                translation = ProductTranslationTable(
                    product_id=product.id,
                    main_name=translation_data.get("main_name") or "",
                    main_description=translation_data.get("main_description") or "",
                    main_description_short=translation_data.get("main_description_short") or "",
                )
                db.session.add(translation)
            _apply_columns(translation, translation_data, "translation", report)

        db.session.flush()
        _resolve_category(shop_id, data.get("category"), product, report)
        _resolve_tags(shop_id, data.get("tags") or [], product, report)
        _resolve_attribute_values(shop_id, data.get("attribute_values") or [], product, report)

        new_revision = record_product_revision(product, action="restore", created_by=created_by, source=source)
        report.new_revision_no = new_revision.revision_no
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    report.restored = True
    return report


def restore_product_from_trash(
    *,
    shop_id: uuid.UUID,
    product_id: uuid.UUID,
    created_by: Optional[str] = None,
    source: str = "rest",
) -> RestoreReport:
    """Undelete a trashed product. The row still holds all its data (tags/attribute
    values were never removed), so this only clears ``deleted_at``."""
    report = RestoreReport(restored=False, entity_type=ENTITY_PRODUCT, entity_id=product_id)

    product = (
        db.session.query(ProductTable)
        .filter(ProductTable.shop_id == shop_id, ProductTable.id == product_id)
        .execution_options(include_deleted=True)
        .with_for_update()
        .first()
    )
    if product is None:
        raise HTTPException(
            status_code=404,
            detail="Product not found (it may have been permanently purged; use a revision restore with force=true).",
        )
    if product.deleted_at is None:
        report.warnings.append("Product was not in the trash; nothing to do.")
        report.restored = True
        return report

    try:
        product.deleted_at = None
        product.deleted_batch_id = None
        report.resurrected.append(ResurrectedEntity(kind="product", id=product.id))

        # If the product's category is itself trashed the product would stay invisible
        # in category listings — resurrect it as well.
        if product.category_id is not None:
            category = (
                db.session.query(CategoryTable)
                .filter(CategoryTable.id == product.category_id)
                .execution_options(include_deleted=True)
                .first()
            )
            if category is not None and category.deleted_at is not None:
                category.deleted_at = None
                report.resurrected.append(ResurrectedEntity(kind="category", id=category.id))

        new_revision = record_product_revision(product, action="restore", created_by=created_by, source=source)
        report.new_revision_no = new_revision.revision_no
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    report.restored = True
    return report


def restore_tag_revision(
    *,
    shop_id: uuid.UUID,
    tag_id: uuid.UUID,
    revision_no: int,
    allow_recreate: bool = False,
    created_by: Optional[str] = None,
    source: str = "rest",
) -> RestoreReport:
    """Re-apply a tag revision snapshot. Commits on success, rolls back on error."""
    report = RestoreReport(restored=False, entity_type=ENTITY_TAG, entity_id=tag_id)
    report.restored_from_revision_no = revision_no

    revision = _get_revision(shop_id, ENTITY_TAG, tag_id, revision_no)
    data = _upconvert(dict(revision.data), revision.schema_version)

    tag = (
        db.session.query(TagTable)
        .filter(TagTable.shop_id == shop_id, TagTable.id == tag_id)
        .execution_options(include_deleted=True)
        .with_for_update()
        .first()
    )
    if tag is None and not allow_recreate:
        raise HTTPException(
            status_code=410,
            detail=(
                "Tag was permanently purged. Retry with force=true (user credentials required) "
                "to recreate it from the snapshot."
            ),
        )

    try:
        if tag is None:
            tag = TagTable(id=tag_id, shop_id=shop_id)
            db.session.add(tag)
            report.warnings.append("Tag row was purged; recreated from the snapshot.")

        if tag.deleted_at is not None:
            report.resurrected.append(ResurrectedEntity(kind="tag", id=tag.id, name=tag.name))
        tag.deleted_at = None

        _apply_columns(tag, data.get("tag") or {}, "tag", report)

        translation_data = data.get("translation")
        if translation_data:
            translation = db.session.query(TagTranslationTable).filter(TagTranslationTable.tag_id == tag.id).first()
            if translation is None:
                translation = TagTranslationTable(tag_id=tag.id, main_name=translation_data.get("main_name") or "")
                db.session.add(translation)
            _apply_columns(translation, translation_data, "translation", report)

        new_revision = record_tag_revision(tag, action="restore", created_by=created_by, source=source)
        report.new_revision_no = new_revision.revision_no
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    report.restored = True
    return report


def restore_tag_from_trash(
    *,
    shop_id: uuid.UUID,
    tag_id: uuid.UUID,
    created_by: Optional[str] = None,
    source: str = "rest",
) -> RestoreReport:
    """Undelete a trashed tag. Its product links were never removed, so this only clears ``deleted_at``."""
    report = RestoreReport(restored=False, entity_type=ENTITY_TAG, entity_id=tag_id)

    tag = (
        db.session.query(TagTable)
        .filter(TagTable.shop_id == shop_id, TagTable.id == tag_id)
        .execution_options(include_deleted=True)
        .with_for_update()
        .first()
    )
    if tag is None:
        raise HTTPException(
            status_code=404,
            detail="Tag not found (it may have been permanently purged; use a revision restore with force=true).",
        )
    if tag.deleted_at is None:
        report.warnings.append("Tag was not in the trash; nothing to do.")
        report.restored = True
        return report

    try:
        tag.deleted_at = None
        report.resurrected.append(ResurrectedEntity(kind="tag", id=tag.id, name=tag.name))
        new_revision = record_tag_revision(tag, action="restore", created_by=created_by, source=source)
        report.new_revision_no = new_revision.revision_no
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    report.restored = True
    return report


def _restore_attribute_options(attribute: AttributeTable, snapshot_options: list, report: RestoreReport) -> None:
    """Make the attribute's options match the snapshot (replace-all semantics).

    Options are matched by id first (soft-deleted ones are resurrected), then by
    ``value_key``. Purged options are recreated under their snapshot id, so option
    references inside old product revisions resolve again. Live options that are
    not in the snapshot are moved to the trash, never purged — their product
    attribute values survive for a later restore.
    """
    existing = (
        db.session.query(AttributeOptionTable)
        .filter(AttributeOptionTable.attribute_id == attribute.id)
        .execution_options(include_deleted=True)
        .with_for_update()
        .all()
    )
    by_id = {option.id: option for option in existing}
    by_key = {option.value_key: option for option in existing}

    desired_ids: set[uuid.UUID] = set()
    for option_ref in snapshot_options or []:
        ref_id = uuid.UUID(option_ref["id"]) if option_ref.get("id") else None
        option = by_id.get(ref_id) if ref_id else None
        if option is None:
            option = by_key.get(option_ref.get("value_key"))
        if option is None:
            option = AttributeOptionTable(id=ref_id, attribute_id=attribute.id, value_key=option_ref.get("value_key"))
            db.session.add(option)
            db.session.flush()
            report.warnings.append(f"Option '{option_ref.get('value_key')}' was purged; recreated from the snapshot.")
        else:
            if option.deleted_at is not None:
                option.deleted_at = None
                report.resurrected.append(
                    ResurrectedEntity(kind="attribute_option", id=option.id, name=option.value_key)
                )
            option.value_key = option_ref.get("value_key")
        desired_ids.add(option.id)

    now = datetime.now(timezone.utc)
    for option in existing:
        if option.id not in desired_ids and option.deleted_at is None:
            option.deleted_at = now
            report.warnings.append(f"Option '{option.value_key}' is not in the snapshot; moved to the trash.")


def restore_attribute_revision(
    *,
    shop_id: uuid.UUID,
    attribute_id: uuid.UUID,
    revision_no: int,
    allow_recreate: bool = False,
    created_by: Optional[str] = None,
    source: str = "rest",
) -> RestoreReport:
    """Re-apply an attribute revision snapshot (attribute, translation and options).

    Commits on success, rolls back on error.
    """
    report = RestoreReport(restored=False, entity_type=ENTITY_ATTRIBUTE, entity_id=attribute_id)
    report.restored_from_revision_no = revision_no

    revision = _get_revision(shop_id, ENTITY_ATTRIBUTE, attribute_id, revision_no)
    data = _upconvert(dict(revision.data), revision.schema_version)

    attribute = (
        db.session.query(AttributeTable)
        .filter(AttributeTable.shop_id == shop_id, AttributeTable.id == attribute_id)
        .execution_options(include_deleted=True)
        .with_for_update()
        .first()
    )
    if attribute is None and not allow_recreate:
        raise HTTPException(
            status_code=410,
            detail=(
                "Attribute was permanently purged. Retry with force=true (user credentials required) "
                "to recreate it from the snapshot."
            ),
        )

    try:
        if attribute is None:
            attribute = AttributeTable(id=attribute_id, shop_id=shop_id)
            db.session.add(attribute)
            report.warnings.append("Attribute row was purged; recreated from the snapshot.")

        if attribute.deleted_at is not None:
            report.resurrected.append(ResurrectedEntity(kind="attribute", id=attribute.id, name=attribute.name))
        attribute.deleted_at = None

        _apply_columns(attribute, data.get("attribute") or {}, "attribute", report)

        translation_data = data.get("translation")
        if translation_data:
            translation = (
                db.session.query(AttributeTranslationTable)
                .filter(AttributeTranslationTable.attribute_id == attribute.id)
                .first()
            )
            if translation is None:
                translation = AttributeTranslationTable(
                    attribute_id=attribute.id, main_name=translation_data.get("main_name") or ""
                )
                db.session.add(translation)
            _apply_columns(translation, translation_data, "translation", report)

        db.session.flush()
        _restore_attribute_options(attribute, data.get("options") or [], report)

        new_revision = record_attribute_revision(attribute, action="restore", created_by=created_by, source=source)
        report.new_revision_no = new_revision.revision_no
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    report.restored = True
    return report


def restore_attribute_from_trash(
    *,
    shop_id: uuid.UUID,
    attribute_id: uuid.UUID,
    created_by: Optional[str] = None,
    source: str = "rest",
) -> RestoreReport:
    """Undelete a trashed attribute. Its options and product values were never
    removed, so this only clears ``deleted_at``. Options that were trashed
    individually stay in the trash (restore a revision to bring those back)."""
    report = RestoreReport(restored=False, entity_type=ENTITY_ATTRIBUTE, entity_id=attribute_id)

    attribute = (
        db.session.query(AttributeTable)
        .filter(AttributeTable.shop_id == shop_id, AttributeTable.id == attribute_id)
        .execution_options(include_deleted=True)
        .with_for_update()
        .first()
    )
    if attribute is None:
        raise HTTPException(
            status_code=404,
            detail="Attribute not found (it may have been permanently purged; use a revision restore with force=true).",
        )
    if attribute.deleted_at is None:
        report.warnings.append("Attribute was not in the trash; nothing to do.")
        report.restored = True
        return report

    try:
        attribute.deleted_at = None
        report.resurrected.append(ResurrectedEntity(kind="attribute", id=attribute.id, name=attribute.name))
        new_revision = record_attribute_revision(attribute, action="restore", created_by=created_by, source=source)
        report.new_revision_no = new_revision.revision_no
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    report.restored = True
    return report


def restore_category_from_trash(
    *,
    shop_id: uuid.UUID,
    category_id: uuid.UUID,
    restore_products: bool = True,
    created_by: Optional[str] = None,
    source: str = "rest",
) -> RestoreReport:
    """Undelete a trashed category, optionally with the batch of products that was
    trashed together with it (category delete with ``force=true``)."""
    report = RestoreReport(restored=False, entity_type=ENTITY_CATEGORY, entity_id=category_id)

    category = (
        db.session.query(CategoryTable)
        .filter(CategoryTable.shop_id == shop_id, CategoryTable.id == category_id)
        .execution_options(include_deleted=True)
        .with_for_update()
        .first()
    )
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found (it may have been permanently purged).")
    if category.deleted_at is None:
        report.warnings.append("Category was not in the trash; nothing to do.")
        report.restored = True
        return report

    try:
        category.deleted_at = None
        category_name = category.translation.main_name if category.translation else None
        report.resurrected.append(ResurrectedEntity(kind="category", id=category.id, name=category_name))

        if restore_products:
            # The cascade delete stamped a batch id on every product it trashed and
            # stored it in the category's delete revision.
            last_delete = (
                db.session.query(RevisionTable)
                .filter(
                    RevisionTable.entity_type == ENTITY_CATEGORY,
                    RevisionTable.entity_id == category_id,
                    RevisionTable.action == "delete",
                )
                .order_by(RevisionTable.revision_no.desc())
                .first()
            )
            batch_id = (last_delete.data or {}).get("deleted_batch_id") if last_delete else None
            if batch_id:
                products = (
                    db.session.query(ProductTable)
                    .filter(ProductTable.shop_id == shop_id, ProductTable.deleted_batch_id == uuid.UUID(batch_id))
                    .execution_options(include_deleted=True)
                    .with_for_update()
                    .all()
                )
                for product in products:
                    product.deleted_at = None
                    product.deleted_batch_id = None
                    report.resurrected.append(ResurrectedEntity(kind="product", id=product.id))
                    record_product_revision(product, action="restore", created_by=created_by, source=source)
            elif last_delete is not None:
                report.warnings.append(
                    "No product batch found on the category's delete revision; only the category was restored."
                )

        new_revision = record_category_revision(category, action="restore", created_by=created_by, source=source)
        report.new_revision_no = new_revision.revision_no
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    report.restored = True
    return report
