"""Render-only email regressions, independent of the API/database fixtures."""

from html import unescape
from pathlib import Path

import jinja2
import pytest


@pytest.fixture()
def template_env():
    root = Path(__file__).resolve().parents[2] / "server/mail_templates"
    return jinja2.Environment(loader=jinja2.FileSystemLoader(root), autoescape=True, undefined=jinja2.StrictUndefined)


@pytest.fixture()
def order_context():
    return {
        "customer_order_id": 42,
        "customer_company_name": "Customer company",
        "customer_name": "Alex Example",
        "customer_address": "Example street 1",
        "customer_postal_code": "1234 AB",
        "customer_city": "Amsterdam",
        "customer_country": "Nederland",
        "customer_btw_number": "CUSTOMER-VAT-123",
        "customer_email": "customer@example.com",
        "shop_name": "Example shop",
        "shop_company": "Shop company",
        "shop_address": "Shop street 2",
        "shop_zip_code": "5678 CD",
        "shop_city": "Amsterdam",
        "shop_phone": "",
        "shop_email": "shop@example.com",
        "kvk_number": "",
        "btw_number": "SHOP-VAT-456",
        "order_lines": [],
        "shipping_lines": [],
        "shipping_fee_inc_btw": 0,
        "total_ex_btw": 0,
        "total_btw": 0,
        "total_inc_btw": 0,
        "completed_at": "03-11-2026 12:00",
    }


@pytest.mark.parametrize("language", ["nl", "en"])
def test_customer_vat_is_only_in_footer(template_env, order_context, language):
    html = template_env.get_template(f"{language}/mail_order_confirmation_customer.html.j2").render(**order_context)
    before_footer, separator, footer = html.partition("<hr ")
    assert separator
    assert "CUSTOMER-VAT-123" not in before_footer
    assert footer.count("CUSTOMER-VAT-123") == 1
    assert "SHOP-VAT-456" in footer


@pytest.mark.parametrize("language", ["nl", "en"])
@pytest.mark.parametrize("audience", ["customer", "owner"])
def test_missing_details_and_escaping(template_env, order_context, language, audience):
    template = template_env.get_template(f"{language}/mail_order_confirmation_{audience}.html.j2")
    for key in order_context:
        if key.startswith("customer_") and key != "customer_order_id":
            order_context[key] = ""
    html = template.render(**order_context)
    assert "None" not in html
    assert "<style" not in html.split("<body", 1)[1]
    order_context["customer_address"] = '<script>alert("unsafe")</script>'
    html = template.render(**order_context)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_long_identifiers_have_wrapping_opportunities_and_stay_escaped(template_env):
    macro = template_env.get_template("macros.html.j2").module.breakable
    value = "x" * 160 + "<&>"
    result = str(macro(value))
    assert "&#8203;" in result
    assert "&lt;" in result
    assert unescape(result).replace("\u200b", "") == value
    assert max(len(part) for part in unescape(result).split("\u200b")) <= 16
