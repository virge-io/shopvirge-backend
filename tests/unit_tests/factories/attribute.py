from server.db import db
from server.db.models import (
    AttributeOptionTable,
    AttributeOptionTranslationTable,
    AttributeTable,
    AttributeTranslationTable,
    ProductAttributeValueTable,
)


def make_attribute(shop_id, name="size", unit=None):
    attr = AttributeTable(shop_id=shop_id, name=name, unit=unit)
    db.session.add(attr)
    db.session.commit()
    return attr.id


def make_option(attribute_id, value_key: str):
    opt = AttributeOptionTable(attribute_id=attribute_id, value_key=value_key)
    db.session.add(opt)
    db.session.commit()
    return opt.id


def make_attribute_with_translation(shop_id, name="size", unit=None, main_name=None, alt1_name=None, alt2_name=None):
    attr = AttributeTable(shop_id=shop_id, name=name, unit=unit)
    db.session.add(attr)
    db.session.flush()
    translation = AttributeTranslationTable(
        attribute_id=attr.id,
        main_name=main_name or name,
        alt1_name=alt1_name,
        alt2_name=alt2_name,
    )
    db.session.add(translation)
    db.session.commit()
    return attr.id


def make_option_with_translation(attribute_id, value_key: str, main_name=None, alt1_name=None, alt2_name=None):
    opt = AttributeOptionTable(attribute_id=attribute_id, value_key=value_key)
    db.session.add(opt)
    db.session.flush()
    translation = AttributeOptionTranslationTable(
        option_id=opt.id,
        main_name=main_name or value_key,
        alt1_name=alt1_name,
        alt2_name=alt2_name,
    )
    db.session.add(translation)
    db.session.commit()
    return opt.id


def make_pav(product_id, attribute_id, option_id=None):
    pav = ProductAttributeValueTable(product_id=product_id, attribute_id=attribute_id, option_id=option_id)
    db.session.add(pav)
    db.session.commit()
    return pav.id
