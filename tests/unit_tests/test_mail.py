from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from server.db import db
from server.db.models import OrderTable, ShopTable
from server.mail import _compute_order_lines_for_email, send_order_confirmation_emails
from server.schemas.base import quantize_money
from tests.unit_tests.factories.account import make_account
from tests.unit_tests.factories.categories import make_category
from tests.unit_tests.factories.product import make_product


@pytest.fixture()
def mock_smtp(monkeypatch):
    """Replace server.mail.SMTP so send_order_confirmation_emails never opens a socket."""
    instance = MagicMock()
    smtp_cls = MagicMock(return_value=instance)
    monkeypatch.setattr("server.mail.SMTP", smtp_cls)
    return smtp_cls, instance


@pytest.fixture()
def completed_order(shop_with_config):
    shop_id = shop_with_config
    account_id = make_account(shop_id=shop_id, name="customer@example.com")
    category = make_category(shop_id=shop_id)
    product_1 = make_product(shop_id=shop_id, category_id=category, main_name="Widget A")
    product_2 = make_product(shop_id=shop_id, category_id=category, main_name="Widget B")
    order = OrderTable(
        shop_id=shop_id,
        account_id=account_id,
        customer_order_id=42,
        order_info=[
            {
                "description": "first line",
                "product_name": "Widget A",
                "price": 10.0,
                "quantity": 2,
                "product_id": str(product_1),
            },
            {
                "description": "second line",
                "product_name": "Widget B",
                "price": 5.0,
                "quantity": 1,
                "product_id": str(product_2),
            },
        ],
        total=25.0,
        status="complete",
        completed_at=datetime(2026, 4, 23, 12, 0, tzinfo=timezone.utc),
    )
    db.session.add(order)
    db.session.commit()
    return order.id


def test_send_order_confirmation_emails_renders_without_smtp(completed_order, shop_with_config, mock_smtp):
    smtp_cls, smtp_instance = mock_smtp
    order = db.session.get(OrderTable, completed_order)
    shop = db.session.get(ShopTable, shop_with_config)
    account = order.account

    send_order_confirmation_emails(order=order, shop=shop, account=account)

    # Customer + owner notification + owner copy of customer mail — three SMTP sessions.
    assert smtp_cls.call_count == 3
    assert smtp_instance.send_message.call_count == 3
    smtp_instance.quit.assert_called()

    subjects = [call.args[0]["Subject"] for call in smtp_instance.send_message.call_args_list]
    assert any(s.startswith("Orderbevestiging #42") for s in subjects), subjects
    assert any("Nieuwe bestelling #42" in s for s in subjects), subjects
    assert any(s.startswith("[KOPIE klantmail]") and "#42" in s for s in subjects), subjects

    recipients = [call.args[0]["To"] for call in smtp_instance.send_message.call_args_list]
    assert "customer@example.com" in recipients
    assert recipients.count("user@example.com") == 2  # owner notification + owner copy of customer mail


def test_send_order_confirmation_emails_skips_owner_without_contact_email(completed_order, shop_with_config, mock_smtp):
    """If the shop config has no contact.email, only the customer mail goes out."""
    smtp_cls, smtp_instance = mock_smtp
    shop = db.session.get(ShopTable, shop_with_config)
    config = dict(shop.config)
    contact = dict(config.get("contact", {}))
    contact["email"] = ""
    config["contact"] = contact
    shop.config = config
    db.session.commit()

    order = db.session.get(OrderTable, completed_order)
    send_order_confirmation_emails(order=order, shop=shop, account=order.account)

    assert smtp_cls.call_count == 1
    assert smtp_instance.send_message.call_count == 1
    assert smtp_instance.send_message.call_args.args[0]["To"] == "customer@example.com"


def test_send_order_confirmation_emails_swallows_render_errors(shop_with_config, mock_smtp):
    """send_order_confirmation_emails is wrapped in try/except — a broken order must not raise."""
    smtp_cls, _ = mock_smtp
    shop = db.session.get(ShopTable, shop_with_config)

    broken_order = MagicMock()
    broken_order.id = "bad"
    broken_order.order_info = None  # triggers TypeError in _compute_order_lines_for_email
    broken_order.customer_order_id = 1
    broken_order.completed_at = None

    account = MagicMock()
    account.name = "x@example.com"
    account.details = None

    send_order_confirmation_emails(order=broken_order, shop=shop, account=account)
    assert smtp_cls.call_count == 0


def test_compute_order_lines_treats_stored_price_as_vat_inclusive(completed_order, shop_with_config):
    """Stored order_info price includes VAT — ex-VAT must divide out the rate, not add it on top.

    The first order line is Widget A at price 10.00 x 2, VAT 21% (shop.vat_standard).
    After the fix, price_inc_btw == 10.00 (as stored), price_ex_btw == 10.00 / 1.21 ≈ 8.26,
    and line_total_inc_btw == 20.00. Prior to the fix, price_inc_btw came out as 12.10
    because ex was treated as the ground truth and VAT was stacked on top.
    """
    order = db.session.get(OrderTable, completed_order)
    shop = db.session.get(ShopTable, shop_with_config)

    lines = _compute_order_lines_for_email(order.order_info, shop)

    widget_a = next(line for line in lines if line["product_name"] == "Widget A")
    assert widget_a["btw_rate"] == shop.vat_standard
    assert widget_a["price_inc_btw"] == Decimal("10.00"), "stored price must be surfaced as the inc-VAT price"
    assert widget_a["price_ex_btw"] == quantize_money(Decimal("10") / Decimal("1.21"))
    assert widget_a["line_total_inc_btw"] == Decimal("20.00")
    assert widget_a["line_total_ex_btw"] == quantize_money(Decimal("20") / Decimal("1.21"))

    widget_b = next(line for line in lines if line["product_name"] == "Widget B")
    assert widget_b["price_inc_btw"] == Decimal("5.00")
    assert widget_b["price_ex_btw"] == quantize_money(Decimal("5") / Decimal("1.21"))
    assert widget_b["line_total_inc_btw"] == Decimal("5.00")


def test_customer_mail_shows_completed_at_in_europe_amsterdam_for_nl(completed_order, shop_with_config, mock_smtp):
    """NL mails render order.completed_at in Europe/Amsterdam, not UTC.

    The fixture sets completed_at = 2026-04-23 12:00 UTC. In late April the
    Netherlands is on CEST (UTC+2), so the rendered date string must read 14:00,
    not 12:00. Without conversion the mail would show the customer a time two
    hours behind the moment they actually placed the order.
    """
    _, smtp_instance = mock_smtp
    order = db.session.get(OrderTable, completed_order)
    shop = db.session.get(ShopTable, shop_with_config)

    send_order_confirmation_emails(order=order, shop=shop, account=order.account)

    customer_call = next(
        call for call in smtp_instance.send_message.call_args_list if call.args[0]["To"] == "customer@example.com"
    )
    message = customer_call.args[0]
    html_parts = [part for part in message.walk() if part.get_content_type() == "text/html"]
    assert html_parts, "no HTML part in customer mail"
    html_body = html_parts[0].get_payload(decode=True).decode("utf-8")

    assert "23-04-2026 14:00" in html_body, "expected Amsterdam-local time in NL mail body"
    assert "23-04-2026 12:00" not in html_body, "UTC value must not leak into NL mail"


def test_compute_order_lines_zero_vat_is_lossless(completed_order, shop_with_config):
    """With a 0% VAT rate, ex and inc figures must be identical (no division by zero fragility)."""
    shop = db.session.get(ShopTable, shop_with_config)
    shop.vat_standard = Decimal("0")
    db.session.commit()

    order = db.session.get(OrderTable, completed_order)
    lines = _compute_order_lines_for_email(order.order_info, shop)

    for line in lines:
        assert line["price_ex_btw"] == line["price_inc_btw"]
        assert line["line_total_ex_btw"] == line["line_total_inc_btw"]
