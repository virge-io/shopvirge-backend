#!/usr/bin/env python3
"""Reset the dedicated demo database to one empty fixed-ID demo shop.

Run after migrations with DATABASE_URI pointing at shop_demo (or shop_demo_*).
--check validates configuration without connecting to a database. --config FILE
loads storefront configuration; --about TEXT overrides its About text, including
an explicit empty string. The reset is atomic and uses the shop-owned foreign
key cascades, including related and soft-deleted rows. Unrelated shops remain.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any
from uuid import UUID

from sqlalchemy.engine import make_url

from server.db.database import Database
from server.schemas.shop import ConfigurationV1, ShopType

DEMO_SHOP_ID = UUID("51799a20-6a7c-4867-9545-fed56051a203")
DEMO_SHOP_NAME = "Demo Shop"

# The About text is what get_shop_about hands the agent, so it is the place to give the demo
# agent context about the shop. Empty by default; recorded scenarios pass their own via --about or
# DEMO_SHOP_ABOUT (start.sh demo forwards it).
DEFAULT_ABOUT = ""


def build_config(about: str = DEFAULT_ABOUT) -> dict[str, Any]:
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


def load_config(path: str | None, about: str | None = None) -> dict[str, Any]:
    if path is None:
        return build_config(about or DEFAULT_ABOUT)
    with open(path) as fh:
        raw = json.load(fh)
    # A config file keeps its own About text unless one is given explicitly.
    if about is not None:
        raw["languages"]["main"]["static_texts"]["about"] = about
    return ConfigurationV1.model_validate(raw).model_dump(mode="json", exclude_none=True)


def validate_demo_database(uri: str) -> None:
    """Refuse to reset the normal development or production database."""
    name = make_url(uri).database or ""
    if name != "shop_demo" and not name.startswith("shop_demo_"):
        raise ValueError("Demo reset requires a database named shop_demo or shop_demo_*")


def reset_demo_shop(db: Database, config: dict[str, Any]) -> None:
    """Atomically replace demo/bootstrap shops, leaving unrelated shops untouched."""
    from server.db import models

    with db.session.begin_nested():
        bootstrap_ids = [
            row.id
            for row in db.session.query(models.ShopTable).filter_by(name="shop", description="Default shop").all()
        ]
        db.session.query(models.ShopTable).filter(
            models.ShopTable.id.in_([DEMO_SHOP_ID, *bootstrap_ids])
        ).execution_options(include_deleted=True).delete(synchronize_session="fetch")
        _create_demo_shop(db, config)
    db.session.commit()


def _create_demo_shop(db: Database, config: dict[str, Any]) -> None:
    """Create the demo's empty shop using validated storefront configuration."""
    from server.db import models

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
    db.session.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="validate the config and exit")
    parser.add_argument("--config", help="JSON file with the shop config to use instead of the built-in one")
    parser.add_argument(
        "--about",
        default=os.environ.get("DEMO_SHOP_ABOUT"),
        help="markdown for the shop's About page (default: $DEMO_SHOP_ABOUT, else empty)",
    )
    args = parser.parse_args()

    config = load_config(args.config, args.about)
    if args.check:
        print("Config is valid.")  # noqa: T201 -- CLI output
        return

    # Imported late so --check works without a database or the full app settings.
    from server.db import db, init_database
    from server.settings import app_settings

    validate_demo_database(str(app_settings.DATABASE_URI))
    init_database(app_settings)
    reset_demo_shop(db, config)
    print(f"Done. {DEMO_SHOP_NAME!r}: 0 products, 0 categories.")  # noqa: T201 -- CLI output


if __name__ == "__main__":
    main()
