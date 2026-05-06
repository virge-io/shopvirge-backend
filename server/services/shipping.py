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
from typing import Any, Optional

from server.schemas.shipping import ShippingCalculation, ShippingLine


def resolve_vat_rate(product: Any, shop: Any) -> float:
    """Look up the VAT rate for a product, falling back to shop.vat_standard.

    Mirrors the resolution used elsewhere (mail rendering): the product's
    `tax_category` is the name of a Float column on the shop (e.g.
    ``vat_standard``, ``vat_lower_1``).
    """
    if product is not None and getattr(product, "tax_category", None):
        return getattr(shop, product.tax_category, shop.vat_standard)
    return shop.vat_standard


def build_rate_subtotals(order_info: list, shop: Any) -> dict[float, float]:
    """Sum cart inc-VAT line totals grouped by VAT rate.

    `order_info` may contain dicts or Pydantic items; both are accepted.
    """
    from server.crud.crud_product import product_crud

    subtotals: dict[float, float] = {}
    for raw in order_info:
        item = raw.model_dump() if hasattr(raw, "model_dump") else dict(raw)
        product = product_crud.get_id_by_shop_id(shop.id, item["product_id"])
        rate = resolve_vat_rate(product, shop)
        quantity = item.get("quantity", 1)
        line_total_inc = round(item["price"] * quantity, 2)
        subtotals[rate] = round(subtotals.get(rate, 0.0) + line_total_inc, 2)
    return subtotals


def allocate_shipping_lines(fee_inc_btw: float, rate_subtotals: dict[float, float]) -> list[ShippingLine]:
    """Split a single inc-VAT shipping fee proportionally across cart VAT rates.

    The rounding remainder (positive or negative) is folded into the last
    sorted rate so the per-line inc-VAT amounts sum exactly to ``fee_inc_btw``.
    """
    if fee_inc_btw <= 0 or not rate_subtotals:
        return []

    grand_total = sum(rate_subtotals.values())
    if grand_total <= 0:
        return []

    sorted_rates = sorted(rate_subtotals.keys())
    allocations: list[tuple[float, float]] = []
    allocated = 0.0
    for i, rate in enumerate(sorted_rates):
        if i == len(sorted_rates) - 1:
            amount_inc = round(fee_inc_btw - allocated, 2)
        else:
            amount_inc = round(fee_inc_btw * rate_subtotals[rate] / grand_total, 2)
            allocated = round(allocated + amount_inc, 2)
        if amount_inc > 0:
            allocations.append((rate, amount_inc))

    lines: list[ShippingLine] = []
    for rate, amount_inc in allocations:
        vat_divisor = 1 + rate / 100
        amount_ex = round(amount_inc / vat_divisor, 2)
        amount_btw = round(amount_inc - amount_ex, 2)
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
    fixed_fee = float(shipping_cfg.get("fixed_fee", 0.0) or 0.0)
    free_above_enabled = bool(shipping_cfg.get("free_shipping_above_enabled", False))
    free_above_amount = float(shipping_cfg.get("free_shipping_above_amount", 0.0) or 0.0)

    rate_subtotals = build_rate_subtotals(order_info, shop)
    cart_total_inc = round(sum(rate_subtotals.values()), 2)

    free_shipping_applied = False
    if free_above_enabled and free_above_amount > 0 and cart_total_inc >= free_above_amount:
        fee_inc_btw = 0.0
        free_shipping_applied = True
    else:
        fee_inc_btw = round(fixed_fee, 2)

    lines = allocate_shipping_lines(fee_inc_btw, rate_subtotals)
    fee_ex_btw = round(sum(line.amount_ex_btw for line in lines), 2)
    fee_btw = round(fee_inc_btw - fee_ex_btw, 2)

    return ShippingCalculation(
        enabled=True,
        method=method,
        fee_inc_btw=fee_inc_btw,
        fee_ex_btw=fee_ex_btw,
        fee_btw=fee_btw,
        free_shipping_applied=free_shipping_applied,
        free_shipping_threshold=free_above_amount if free_above_enabled else None,
        lines=lines,
    )
