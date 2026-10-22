"""The recorder must be able to reset a populated demo twice without losing other shops."""

import json
from datetime import datetime, timezone

import pytest

from scripts.seed_demo_shop import DEMO_SHOP_ID, build_config, load_config, reset_demo_shop, validate_demo_database
from server.db import db
from server.db.models import AttributeTable, ProductTable, ShopTable, TagTable
from tests.unit_tests.factories.attribute import make_attribute, make_option, make_pav
from tests.unit_tests.factories.categories import make_category
from tests.unit_tests.factories.product import make_product
from tests.unit_tests.factories.shop import make_shop
from tests.unit_tests.factories.tag import make_tag


def test_demo_reset_cascades_trashed_and_related_data_and_preserves_other_shop():
    other = make_shop(random_shop_name=True)
    other_category = make_category(other)
    other_product = make_product(other, other_category)
    reset_demo_shop(db, build_config("First take"))
    category = make_category(DEMO_SHOP_ID)
    product = make_product(DEMO_SHOP_ID, category)
    attribute = make_attribute(DEMO_SHOP_ID)
    option = make_option(attribute, "blue")
    make_pav(product, attribute, option)
    make_tag(DEMO_SHOP_ID)
    db.session.query(ProductTable).filter_by(id=product).update({"deleted_at": datetime.now(timezone.utc)})
    db.session.commit()

    for _ in range(2):
        reset_demo_shop(db, build_config("Next take"))
        assert (
            db.session.query(ProductTable)
            .filter_by(shop_id=DEMO_SHOP_ID)
            .execution_options(include_deleted=True)
            .count()
            == 0
        )
        assert db.session.query(AttributeTable).filter_by(shop_id=DEMO_SHOP_ID).count() == 0
        assert db.session.query(TagTable).filter_by(shop_id=DEMO_SHOP_ID).count() == 0
        demo = db.session.query(ShopTable).filter_by(id=DEMO_SHOP_ID).one()
        assert demo.config["languages"]["main"]["static_texts"]["about"] == "Next take"
        assert db.session.query(ProductTable).filter_by(id=other_product).count() == 1


def test_demo_reset_rolls_back_if_recreation_fails(monkeypatch):
    from scripts import seed_demo_shop

    reset_demo_shop(db, build_config("Keep me"))
    category = make_category(DEMO_SHOP_ID)
    product = make_product(DEMO_SHOP_ID, category)

    def fail(*args):
        raise ValueError("invalid config")

    monkeypatch.setattr(seed_demo_shop, "_create_demo_shop", fail)
    with pytest.raises(ValueError, match="invalid config"):
        reset_demo_shop(db, build_config("Bad take"))
    assert db.session.query(ProductTable).filter_by(id=product).count() == 1


@pytest.mark.parametrize("name", ["shop", "production", "shop-test", ""])
def test_demo_guard_rejects_normal_databases(name):
    with pytest.raises(ValueError, match="Demo reset requires"):
        validate_demo_database(f"postgresql://localhost/{name}")


def test_config_file_can_explicitly_clear_about(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps(build_config("Original")))
    assert load_config(str(config))["languages"]["main"]["static_texts"]["about"] == "Original"
    assert load_config(str(config), "")["languages"]["main"]["static_texts"]["about"] == ""
