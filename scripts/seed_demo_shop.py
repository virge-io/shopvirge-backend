#!/usr/bin/env python3
"""Seed the empty demo shop used for recorded agent demos.

Modelled on ``seed_jvj_eval.py`` (the eval seed, which lives on the
``feature/mcp-category-partial-and-order-reads`` branch). It creates ONE shop with a fixed id, a
valid storefront config and an About text, and deliberately NO products and NO categories: the
demo agent creates those on camera.

The shop id is fixed because Cognito group membership *is* the shop UUID; a generated id would
lock the demo user out of the shop.

The default shop that migration 1b485cfea981 inserts (name 'shop') is replaced by the demo shop, so
the demo DB ends up with exactly one shop.

Idempotent: re-running purges everything that hangs off the demo shop (rows are really deleted,
not trashed, so SKUs are free again), then recreates the shop. Only the shop with ``DEMO_SHOP_ID``
is touched, so it is safe on a shared DB, but the intended target is a dedicated ``shop_demo`` DB.

Usage:
    cd shop-virge-backend
    # one-off: create the DB and its schema
    createdb shop_demo -O shop
    DATABASE_URI=postgresql://shop:shop@localhost/shop_demo PYTHONPATH=. alembic upgrade heads
    # every run: reset the demo shop
    DATABASE_URI=postgresql://shop:shop@localhost/shop_demo PYTHONPATH=. python scripts/seed_demo_shop.py

    --check       validate the config against ConfigurationV1 and exit (no database needed)
    --config FILE use the JSON in FILE as the shop config instead of the built-in one (it is still
                  validated); handy to clone the config of an existing demo shop
    --about TEXT  markdown for the About page (default: $DEMO_SHOP_ABOUT, else empty)
"""

from __future__ import annotations

import argparse
import json
import os
from uuid import UUID

from server.schemas.shop import ConfigurationV1, ShopType

DEMO_SHOP_ID = UUID("51799a20-6a7c-4867-9545-fed56051a203")
DEMO_SHOP_NAME = "Demo Shop"

# The About text is what get_shop_about hands the agent, so it is the place to give the demo
# agent context about the shop. Empty by default; recorded scenarios pass their own via --about or
# DEMO_SHOP_ABOUT (start.sh demo forwards it).
DEFAULT_ABOUT = ""


def build_config(about: str = DEFAULT_ABOUT) -> dict:
    """Built-in demo config, validated through ConfigurationV1 so a bad value fails here, not in the storefront."""
    raw = {
        "short_shop_name": "Demo Shop",
        "logo": "",
        "main_banner": "",
        "languages": {
            "main": {
                "language_name": "English",
                "menu_items": {
                    "about": "About",
                    "cart": "Cart",
                    "checkout": "Checkout",
                    "products": "Products",
                    "contact": "Contact",
                    "policies": "Policies",
                    "terms": "Terms",
                    "privacy_policy": "Privacy policy",
                    "return_policy": "Return policy",
                    "website": "Website",
                    "phone": "Phone",
                    "email": "Email",
                    "address": "Address",
                },
                "static_texts": {
                    "about": about,
                    "terms": "Terms of the demo shop.",
                    "privacy_policy": "Privacy policy of the demo shop.",
                    "return_policy": "Return policy of the demo shop.",
                },
            }
        },
        "contact": {
            "company": "Demo Shop",
            "website": "https://shopvirge.com",
            "phone": "+31201234567",
            "email": "demo@example.com",
            "address": "Demostraat 1",
            "zip_code": "1011AA",
            "city": "Amsterdam",
        },
        "toggles": {
            "show_nav_categories": True,
            "language_alt1_enabled": False,
            "language_alt2_enabled": False,
        },
    }
    return ConfigurationV1.model_validate(raw).model_dump(mode="json", exclude_none=True)


def load_config(path: str | None, about: str = DEFAULT_ABOUT) -> dict:
    if path is None:
        return build_config(about)
    with open(path) as fh:
        raw = json.load(fh)
    # A config file keeps its own About text unless one is given explicitly.
    if about:
        raw["languages"]["main"]["static_texts"]["about"] = about
    return ConfigurationV1.model_validate(raw).model_dump(mode="json", exclude_none=True)


def _default_shop_ids(db, models) -> list[UUID]:
    """Ids of the shop created by migration 1b485cfea981 (random uuid4, name 'shop', description 'Default shop')."""
    rows = db.session.query(models.ShopTable.id).filter_by(name="shop", description="Default shop").all()
    return [r for (r,) in rows if r != DEMO_SHOP_ID]


def _purge_shop(db, models, shop_id: UUID) -> None:
    """Really delete a shop and everything under it, children first (most FKs have no ON DELETE CASCADE)."""
    # Soft-deleted (trashed) rows are hidden by a global filter but still hold FKs, so include them.
    product_ids = [
        p
        for (p,) in db.session.query(models.ProductTable.id)
        .filter_by(shop_id=shop_id)
        .execution_options(include_deleted=True)
        .all()
    ]
    category_ids = [
        c
        for (c,) in db.session.query(models.CategoryTable.id)
        .filter_by(shop_id=shop_id)
        .execution_options(include_deleted=True)
        .all()
    ]

    # Anything referencing products / categories / the shop goes first. Tags, attributes and
    # revisions are not seeded and the demo agent does not create them, but a previous take might.
    # If a delete below trips an FK, add that table here rather than switching to a blanket TRUNCATE.
    db.session.query(models.OrderTable).filter_by(shop_id=shop_id).delete(synchronize_session=False)
    db.session.query(models.Account).filter_by(shop_id=shop_id).delete(synchronize_session=False)
    if product_ids:
        db.session.query(models.ProductTranslationTable).filter(
            models.ProductTranslationTable.product_id.in_(product_ids)
        ).delete(synchronize_session=False)
    db.session.query(models.ProductTable).filter_by(shop_id=shop_id).execution_options(include_deleted=True).delete(
        synchronize_session=False
    )
    if category_ids:
        db.session.query(models.CategoryTranslationTable).filter(
            models.CategoryTranslationTable.category_id.in_(category_ids)
        ).delete(synchronize_session=False)
    db.session.query(models.CategoryTable).filter_by(shop_id=shop_id).execution_options(include_deleted=True).delete(
        synchronize_session=False
    )
    db.session.query(models.ShopTable).filter_by(id=shop_id).delete(synchronize_session=False)
    db.session.commit()


def _create_demo_shop(db, models, config: dict) -> None:
    shop = models.ShopTable(
        id=DEMO_SHOP_ID,
        name=DEMO_SHOP_NAME,
        description="Demo shop for recorded agent demos",
        stripe_public_key="string",
        vat_standard=21,
        vat_lower_1=9,
        vat_lower_2=5,
        vat_lower_3=2,
        vat_special=12,
        vat_zero=0,
        config=config,
        config_version=1,
        shop_type=ShopType.trial().model_dump(mode="json", exclude_none=True),
        # The storefront links are rewritten by the shop-demo prompt, so these are only informational.
        internal_url="http://localhost:3001/en",
        external_url="http://localhost:3001/en",
    )
    db.session.add(shop)
    db.session.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="validate the config and exit")
    parser.add_argument("--config", help="JSON file with the shop config to use instead of the built-in one")
    parser.add_argument(
        "--about",
        default=os.environ.get("DEMO_SHOP_ABOUT", DEFAULT_ABOUT),
        help="markdown for the shop's About page (default: $DEMO_SHOP_ABOUT, else empty)",
    )
    args = parser.parse_args()

    config = load_config(args.config, args.about)
    if args.check:
        print("Config is valid.")
        return

    # Imported late so --check works without a database or the full app settings.
    from server.db import db, init_database
    from server.db import models
    from server.settings import app_settings

    init_database(app_settings)
    print(f"Seeding demo shop {DEMO_SHOP_ID} into {app_settings.DATABASE_URI}")
    # The migration-created default shop becomes the demo shop: it is replaced by the fixed-id one,
    # so only one shop is left and its id matches the Cognito group.
    for default_id in _default_shop_ids(db, models):
        print(f"Replacing migration default shop {default_id}")
        _purge_shop(db, models, default_id)
    _purge_shop(db, models, DEMO_SHOP_ID)
    _create_demo_shop(db, models, config)

    products = db.session.query(models.ProductTable).filter_by(shop_id=DEMO_SHOP_ID).count()
    categories = db.session.query(models.CategoryTable).filter_by(shop_id=DEMO_SHOP_ID).count()
    print(f"Done. {DEMO_SHOP_NAME!r}: {products} products, {categories} categories.")


if __name__ == "__main__":
    main()
