# Copyright 2024 René Dohmen <acidjunk@gmail.com>
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
from decimal import Decimal
from typing import Any, Optional

from server.schemas.base import quantize_money
from server.schemas.shipping import ShippingCalculation, ShippingLine


def resolve_vat_rate(product: Any, shop: Any) -> Decimal:
    """Look up the VAT rate for a product, falling back to shop.vat_standard.

    Mirrors the resolution used elsewhere (mail rendering): the product's
    `tax_category` is the name of a Numeric column on the shop (e.g.
    ``vat_standard``, ``vat_lower_1``).
    """
    if product is not None and getattr(product, "tax_category", None):
        rate = getattr(shop, product.tax_category, shop.vat_standard)
    else:
        rate = shop.vat_standard
    return rate if isinstance(rate, Decimal) else Decimal(str(rate))


def build_rate_subtotals(order_info: list, shop: Any) -> dict[Decimal, Decimal]:
    """Sum cart inc-VAT line totals grouped by VAT rate.

    `order_info` may contain dicts or Pydantic items; both are accepted.
    """
    from server.crud.crud_product import product_crud

    subtotals: dict[Decimal, Decimal] = {}
    for raw in order_info:
        item = raw.model_dump() if hasattr(raw, "model_dump") else dict(raw)
        product = product_crud.get_id_by_shop_id(shop.id, item["product_id"])
        rate = resolve_vat_rate(product, shop)
        quantity = item.get("quantity", 1)
        price = item["price"] if isinstance(item["price"], Decimal) else Decimal(str(item["price"]))
        line_total_inc = quantize_money(price * quantity)
        subtotals[rate] = quantize_money(subtotals.get(rate, Decimal("0")) + line_total_inc)
    return subtotals


def allocate_shipping_lines(fee_ex_btw: Decimal, rate_subtotals: dict[Decimal, Decimal]) -> list[ShippingLine]:
    """Split an ex-VAT shipping fee proportionally across cart VAT rates and add VAT per rate.

    The rounding remainder (positive or negative) is folded into the last
    sorted rate so the per-line ex-VAT amounts sum exactly to ``fee_ex_btw``.
    """
    if fee_ex_btw <= 0 or not rate_subtotals:
        return []

    grand_total = sum(rate_subtotals.values(), Decimal("0"))
    if grand_total <= 0:
        return []

    sorted_rates = sorted(rate_subtotals.keys())
    allocations: list[tuple[Decimal, Decimal]] = []
    allocated = Decimal("0")
    for i, rate in enumerate(sorted_rates):
        if i == len(sorted_rates) - 1:
            amount_ex = quantize_money(fee_ex_btw - allocated)
        else:
            amount_ex = quantize_money(fee_ex_btw * rate_subtotals[rate] / grand_total)
            allocated = quantize_money(allocated + amount_ex)
        if amount_ex > 0:
            allocations.append((rate, amount_ex))

    lines: list[ShippingLine] = []
    for rate, amount_ex in allocations:
        amount_btw = quantize_money(amount_ex * rate / Decimal("100"))
        amount_inc = quantize_money(amount_ex + amount_btw)
        lines.append(
            ShippingLine(
                btw_rate=rate,
                amount_ex_btw=amount_ex,
                amount_inc_btw=amount_inc,
                amount_btw=amount_btw,
            )
        )
    return lines


def compute_shipping_for_cart(order_info: list, shop: Any) -> Optional[ShippingCalculation]:
    """Compute the shipping fee and per-VAT-rate breakdown for a cart.

    The configured ``fixed_fee`` is interpreted as ex-VAT; VAT is added on top
    proportionally across the cart's VAT rates. When ``vat_calculation_enabled``
    is ``False``, the fee is added flat (no VAT split, no per-rate lines).

    Returns ``None`` when shipping is not configured or not enabled on the shop.
    Returns a ``ShippingCalculation`` with ``fee_inc_btw=0`` and
    ``free_shipping_applied=True`` when the free-shipping threshold is met.
    """
    import json

    config = shop.config or {}
    if isinstance(config, str):
        config = json.loads(config) if config else {}
    shipping_cfg = config.get("shipping") or {}
    if not shipping_cfg or not shipping_cfg.get("enabled"):
        return None

    method = shipping_cfg.get("method", "fixed")
    fixed_fee = Decimal(str(shipping_cfg.get("fixed_fee", "0") or "0"))
    vat_enabled = bool(shipping_cfg.get("vat_calculation_enabled", True))
    free_above_enabled = bool(shipping_cfg.get("free_shipping_above_enabled", False))
    free_above_amount = Decimal(str(shipping_cfg.get("free_shipping_above_amount", "0") or "0"))

    rate_subtotals = build_rate_subtotals(order_info, shop)
    cart_total_inc = quantize_money(sum(rate_subtotals.values(), Decimal("0")))

    free_shipping_applied = False
    if free_above_enabled and free_above_amount > 0 and cart_total_inc >= free_above_amount:
        return ShippingCalculation(
            enabled=True,
            method=method,
            fee_inc_btw=Decimal("0.00"),
            fee_ex_btw=Decimal("0.00"),
            fee_btw=Decimal("0.00"),
            free_shipping_applied=True,
            free_shipping_threshold=free_above_amount,
            lines=[],
        )

    if not vat_enabled:
        fee = quantize_money(fixed_fee)
        return ShippingCalculation(
            enabled=True,
            method=method,
            fee_inc_btw=fee,
            fee_ex_btw=fee,
            fee_btw=Decimal("0.00"),
            free_shipping_applied=False,
            free_shipping_threshold=free_above_amount if free_above_enabled else None,
            lines=[],
        )

    fee_ex_btw = quantize_money(fixed_fee)
    lines = allocate_shipping_lines(fee_ex_btw, rate_subtotals)
    if lines:
        fee_inc_btw = quantize_money(sum((line.amount_inc_btw for line in lines), Decimal("0")))
        fee_ex_btw = quantize_money(sum((line.amount_ex_btw for line in lines), Decimal("0")))
        fee_btw = quantize_money(fee_inc_btw - fee_ex_btw)
    else:
        fee_inc_btw = fee_ex_btw
        fee_btw = Decimal("0.00")

    return ShippingCalculation(
        enabled=True,
        method=method,
        fee_inc_btw=fee_inc_btw,
        fee_ex_btw=fee_ex_btw,
        fee_btw=fee_btw,
        free_shipping_applied=False,
        free_shipping_threshold=free_above_amount if free_above_enabled else None,
        lines=lines,
    )
