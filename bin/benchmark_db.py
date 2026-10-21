#!/usr/bin/env python
# Copyright 2026 René Dohmen <acidjunk@gmail.com>
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
"""Benchmark the hot endpoints against a scratch copy of a database.

Boots the API in-process (``TestClient``), runs each scenario a few times and reports per endpoint the number of
SQL statements, SQL time, wall time, pool checkouts and how long a pooled connection was held. ``--explain`` adds
``EXPLAIN (ANALYZE, BUFFERS)`` for the foreign-key lookups, ``--scale N`` clones the benchmark shop's catalogue
into N synthetic shops first, ``--compare before.json`` renders a before/after table.

External services (Stripe, Discord, SMTP, Lambda) are stubbed; ``--external-delay`` makes the stubs sleep so the
report shows whether a pooled connection is held while they run. Point ``DATABASE_URI`` at a scratch copy — the
script writes orders, an API key and a few shop columns. See docs/development/benchmarking.md.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import statistics
import sys
import threading
import time
from pathlib import Path
from time import perf_counter
from typing import Any, Callable
from uuid import UUID, uuid4

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

FIELDS = ("statements", "sql_ms", "wall_ms", "checkouts", "held_ms")
CATALOGUE_TABLES = [
    # (table, parent fk -> parent table, shop-scoped?)
    ("categories", {}, True),
    ("category_translations", {"category_id": "categories"}, False),
    ("tags", {}, True),
    ("tag_translations", {"tag_id": "tags"}, False),
    ("attributes", {}, True),
    ("attribute_translations", {"attribute_id": "attributes"}, False),
    ("attribute_options", {"attribute_id": "attributes"}, False),
    ("products", {"category_id": "categories"}, True),
    ("product_translations", {"product_id": "products"}, False),
    ("products_to_tags", {"product_id": "products", "tag_id": "tags"}, True),
    (
        "product_attribute_values",
        {"product_id": "products", "attribute_id": "attributes", "option_id": "attribute_options"},
        False,
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--shop", type=UUID, help="shop to benchmark (default: the one with the most products)")
    parser.add_argument("--iterations", type=int, default=5, help="timed iterations per scenario (plus one warm-up)")
    parser.add_argument("--external-delay", type=float, default=0.0, help="seconds each stubbed external call sleeps")
    parser.add_argument("--explain", action="store_true", help="EXPLAIN ANALYZE the foreign-key lookups")
    parser.add_argument("--scale", type=int, default=0, help="clone the shop's catalogue into N synthetic shops first")
    parser.add_argument("--scale-only", action="store_true", help="only scale, do not benchmark")
    parser.add_argument("--json", type=Path, help="write the raw results here")
    parser.add_argument("--compare", type=Path, help="a previous --json file to render a before/after table against")
    parser.add_argument("--out", type=Path, help="write the markdown report here (default: stdout)")
    parser.add_argument("--label", default=None, help="label for this run in the report (default: git branch)")
    return parser.parse_args()


# --- Measuring ----------------------------------------------------------------------------------------------------


class Meter:
    """Counts statements and pool checkouts on an engine; ``reset`` before and ``snapshot`` after a request."""

    def __init__(self, engine: Any) -> None:
        from sqlalchemy import event

        self._lock = threading.Lock()
        self.reset()
        event.listen(engine, "before_cursor_execute", self._before)
        event.listen(engine, "after_cursor_execute", self._after)
        event.listen(engine, "checkout", self._checkout)
        event.listen(engine, "checkin", self._checkin)

    def reset(self) -> None:
        with getattr(self, "_lock", threading.Lock()):
            self.statements = 0
            self.sql_seconds = 0.0
            self.checkouts = 0
            self.held_seconds = 0.0
            self._statement_started: dict[int, float] = {}
            self._checked_out_at: dict[int, float] = {}

    def _before(self, conn, cursor, statement, parameters, context, executemany) -> None:
        with self._lock:
            self._statement_started[id(cursor)] = perf_counter()

    def _after(self, conn, cursor, statement, parameters, context, executemany) -> None:
        with self._lock:
            started = self._statement_started.pop(id(cursor), None)
            if started is not None:
                self.sql_seconds += perf_counter() - started
                self.statements += 1

    def _checkout(self, dbapi_connection, connection_record, connection_proxy) -> None:
        with self._lock:
            self.checkouts += 1
            self._checked_out_at[id(dbapi_connection)] = perf_counter()

    def _checkin(self, dbapi_connection, connection_record) -> None:
        with self._lock:
            started = self._checked_out_at.pop(id(dbapi_connection), None)
            if started is not None:
                self.held_seconds += perf_counter() - started

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            now = perf_counter()
            still_held = sum(now - started for started in self._checked_out_at.values())
            return {
                "statements": self.statements,
                "sql_ms": round(self.sql_seconds * 1000, 2),
                "checkouts": self.checkouts,
                "held_ms": round((self.held_seconds + still_held) * 1000, 2),
            }


def run_scenario(meter: Meter, call: Callable[[], int], iterations: int) -> dict[str, Any]:
    samples: list[dict[str, float]] = []
    status = None
    for i in range(iterations + 1):
        meter.reset()
        started = perf_counter()
        status = call()
        wall = perf_counter() - started
        sample = meter.snapshot()
        sample["wall_ms"] = round(wall * 1000, 2)
        if i > 0:  # drop the warm-up
            samples.append(sample)
    result = {field: round(statistics.median(sample[field] for sample in samples), 2) for field in FIELDS}
    result["status"] = status
    return result


# --- Stubs for everything that leaves the machine -----------------------------------------------------------------


def install_stubs(delay: float) -> None:
    import stripe

    import server.api.endpoints.orders.public as orders_public
    import server.api.helpers as helpers
    import server.mail as mail_module

    def external_call() -> None:
        if delay:
            time.sleep(delay)

    if hasattr(helpers, "sendMessageToWebSocketServer"):  # the Lambda push; gone on newer branches
        helpers.sendMessageToWebSocketServer = lambda payload: external_call()
    orders_public.post_discord_order_complete = lambda *args, **kwargs: external_call()

    class FakeSMTP:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def starttls(self) -> None:
            pass

        def login(self, **kwargs) -> None:
            pass

        def send_message(self, message) -> None:
            external_call()

        def quit(self) -> None:
            pass

        def close(self) -> None:
            pass

    mail_module.SMTP = FakeSMTP

    class FakeCustomer:
        id = "cus_bench"

    stripe.Customer.create = lambda **kwargs: (external_call(), FakeCustomer())[1]
    stripe.PaymentIntent.create = lambda **kwargs: (external_call(), {"client_secret": "pi_bench_secret"})[1]


# --- Data discovery on the scratch copy ---------------------------------------------------------------------------


def discover(conn: Any, shop_id: UUID | None) -> dict[str, Any]:
    cur = conn.cursor()
    if shop_id is None:
        cur.execute(
            "SELECT shop_id FROM products WHERE deleted_at IS NULL GROUP BY shop_id ORDER BY count(*) DESC LIMIT 1"
        )
        shop_id = cur.fetchone()[0]
    cur.execute("SELECT name FROM shops WHERE id = %s", (shop_id,))
    shop_name = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM products WHERE shop_id = %s AND deleted_at IS NULL", (shop_id,))
    product_count = cur.fetchone()[0]
    cur.execute(
        "SELECT category_id FROM products WHERE shop_id = %s AND deleted_at IS NULL AND category_id IS NOT NULL "
        "GROUP BY category_id ORDER BY count(*) DESC LIMIT 1",
        (shop_id,),
    )
    category_id = cur.fetchone()[0]
    cur.execute(
        "SELECT p.id FROM products p JOIN product_translations t ON t.product_id = p.id "
        "WHERE p.shop_id = %s AND p.deleted_at IS NULL AND p.price IS NOT NULL ORDER BY p.order_number, p.id LIMIT 10",
        (shop_id,),
    )
    cart_ids = [row[0] for row in cur.fetchall()]
    cur.execute(
        "SELECT pav.product_id FROM product_attribute_values pav JOIN products p ON p.id = pav.product_id "
        "WHERE p.shop_id = %s AND p.deleted_at IS NULL GROUP BY pav.product_id ORDER BY count(*) DESC LIMIT 1",
        (shop_id,),
    )
    row = cur.fetchone()
    product_with_attributes = row[0] if row else cart_ids[0]
    cur.execute("SELECT shop_id FROM orders GROUP BY shop_id ORDER BY count(*) DESC LIMIT 1")
    row = cur.fetchone()
    orders_shop_id = row[0] if row else shop_id
    cur.execute("SELECT id FROM orders WHERE shop_id = %s ORDER BY created_at DESC LIMIT 10", (orders_shop_id,))
    order_ids = [row[0] for row in cur.fetchall()]
    cur.execute(
        "SELECT a.id FROM accounts a JOIN orders o ON o.account_id = a.id WHERE a.shop_id = %s "
        "GROUP BY a.id ORDER BY count(*) DESC LIMIT 1",
        (orders_shop_id,),
    )
    row = cur.fetchone()
    account_with_orders = row[0] if row else None
    cur.execute("SELECT config->'toggles'->>'enable_stock_on_products' FROM shops WHERE id = %s", (shop_id,))
    stock_toggle = cur.fetchone()[0]
    cur.execute("SELECT id FROM products WHERE shop_id = %s AND deleted_at IS NULL", (shop_id,))
    all_product_ids = [row[0] for row in cur.fetchall()]
    cur.execute("SELECT id FROM tags WHERE shop_id = %s", (shop_id,))
    tag_ids = [row[0] for row in cur.fetchall()]
    cur.execute("SELECT id FROM attributes WHERE shop_id = %s", (shop_id,))
    attribute_ids = [row[0] for row in cur.fetchall()]
    cur.execute("SELECT count(*) FROM products")
    total_products = cur.fetchone()[0]
    return {
        "shop_id": shop_id,
        "shop_name": shop_name,
        "product_count": product_count,
        "total_products": total_products,
        "category_id": category_id,
        "cart_ids": cart_ids,
        "product_with_attributes": product_with_attributes,
        "orders_shop_id": orders_shop_id,
        "order_ids": order_ids,
        "account_with_orders": account_with_orders,
        "stock_toggle": stock_toggle,
        "all_product_ids": all_product_ids,
        "tag_ids": tag_ids,
        "attribute_ids": attribute_ids,
    }


def prepare_shop(conn: Any, data: dict[str, Any]) -> None:
    """Make the scratch copy's shop exercise every path: no IP allowlist, a Discord webhook, Stripe, stock."""
    cur = conn.cursor()
    cur.execute(
        "UPDATE shops SET allowed_ips = NULL, discord_webhook = %s, stripe_secret_key = %s WHERE id = %s",
        ("https://discord.invalid/bench", "sk_test_bench", data["shop_id"]),
    )
    cur.execute("UPDATE products SET stock = 100000 WHERE id = ANY(%s)", (data["cart_ids"],))
    conn.commit()


# --- EXPLAIN for the foreign-key lookups ---------------------------------------------------------------------------


def explain_queries(conn: Any, data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    cur = conn.cursor()
    cases = [
        (
            "product_translations: IN (all products of the shop)",
            "product_translations",
            "SELECT * FROM product_translations WHERE product_id = ANY(%s)",
            (data["all_product_ids"],),
        ),
        (
            "product_translations: single product_id (lazy load)",
            "product_translations",
            "SELECT * FROM product_translations WHERE product_id = %s",
            (data["cart_ids"][0],),
        ),
        (
            "category_translations: single category_id",
            "category_translations",
            "SELECT * FROM category_translations WHERE category_id = %s",
            (data["category_id"],),
        ),
        (
            "tag_translations: IN (tags of the shop)",
            "tag_translations",
            "SELECT * FROM tag_translations WHERE tag_id = ANY(%s)",
            (data["tag_ids"] or [uuid4()],),
        ),
        (
            "attribute_translations: IN (attributes of the shop)",
            "attribute_translations",
            "SELECT * FROM attribute_translations WHERE attribute_id = ANY(%s)",
            (data["attribute_ids"] or [uuid4()],),
        ),
        (
            "orders: by account_id",
            "orders",
            "SELECT * FROM orders WHERE account_id = %s",
            (data["account_with_orders"] or uuid4(),),
        ),
        (
            "accounts: by (shop_id, name)",
            "accounts",
            "SELECT * FROM accounts WHERE shop_id = %s AND name = %s",
            (data["orders_shop_id"], "bench@example.com"),
        ),
    ]
    results = {}
    for name, table, sql, params in cases:
        cur.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}", params)
        plan = cur.fetchone()[0][0]
        scan = _find_scan(plan["Plan"], table)
        results[name] = {
            "node": plan["Plan"]["Node Type"],
            "scan": f"{scan['Node Type']}" + (f" ({scan['Index Name']})" if scan.get("Index Name") else "")
            if scan
            else "-",
            "rows": scan.get("Actual Rows") if scan else None,
            "ms": round(plan["Execution Time"], 3),
        }
    conn.rollback()
    return results


def _find_scan(node: dict[str, Any], table: str) -> dict[str, Any] | None:
    if node.get("Relation Name") == table:
        return node
    for child in node.get("Plans", []):
        found = _find_scan(child, table)
        if found:
            return found
    return None


# --- Scaling the catalogue ----------------------------------------------------------------------------------------


def scale_catalogue(conn: Any, shop_id: UUID, factor: int) -> None:
    """Clone the shop's catalogue ``factor`` times into synthetic shops (new ids, foreign keys remapped)."""
    from psycopg2.extras import Json, RealDictCursor, execute_values

    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM shops WHERE id = %s", (shop_id,))
    shop_row = dict(cur.fetchone())
    source_rows: dict[str, list[dict[str, Any]]] = {}
    for table, parents, shop_scoped in CATALOGUE_TABLES:
        if shop_scoped:
            cur.execute(f"SELECT * FROM {table} WHERE shop_id = %s", (shop_id,))  # noqa: S608 -- table from CATALOGUE_TABLES
        else:
            parent_column, parent_table = next(iter(parents.items()))
            parent_ids = [row["id"] for row in source_rows[parent_table]]
            cur.execute(f"SELECT * FROM {table} WHERE {parent_column} = ANY(%s)", (parent_ids,))  # noqa: S608
        source_rows[table] = [dict(row) for row in cur.fetchall()]

    def encode(value: Any) -> Any:
        return Json(value) if isinstance(value, (dict, list)) else value

    for copy in range(1, factor + 1):
        suffix = f" (bench copy {copy} {uuid4().hex[:6]})"
        new_shop_id = uuid4()
        shop_copy = {
            **shop_row,
            "id": new_shop_id,
            "name": shop_row["name"] + suffix,
            "description": (shop_row["description"] or "") + suffix,
        }
        columns = list(shop_copy)
        execute_values(
            cur,
            f"INSERT INTO shops ({', '.join(columns)}) VALUES %s",  # noqa: S608 -- names from CATALOGUE_TABLES/information_schema
            [tuple(encode(shop_copy[column]) for column in columns)],
        )
        id_maps: dict[str, dict[UUID, UUID]] = {}
        for table, parents, _shop_scoped in CATALOGUE_TABLES:
            rows = source_rows[table]
            if not rows:
                id_maps[table] = {}
                continue
            id_map = {row["id"]: uuid4() for row in rows}
            id_maps[table] = id_map
            columns = list(rows[0])
            values = []
            for row in rows:
                copy_row = dict(row)
                copy_row["id"] = id_map[row["id"]]
                if "shop_id" in copy_row:
                    copy_row["shop_id"] = new_shop_id
                for column, parent_table in parents.items():
                    if copy_row.get(column) is not None:
                        copy_row[column] = id_maps[parent_table].get(copy_row[column], copy_row[column])
                if table == "products":
                    copy_row["short_id"] = str(copy_row["id"])[:12]
                values.append(tuple(encode(copy_row[column]) for column in columns))
            execute_values(cur, f"INSERT INTO {table} ({', '.join(columns)}) VALUES %s", values, page_size=500)  # noqa: S608 -- names from CATALOGUE_TABLES
    conn.commit()
    cur.execute("ANALYZE")
    conn.commit()


# --- Report ---------------------------------------------------------------------------------------------------------


def render(results: dict[str, Any], compare: dict[str, Any] | None) -> str:
    meta = results["meta"]
    lines = [
        f"### Benchmark: `{meta['label']}`" + (f" vs `{compare['meta']['label']}`" if compare else ""),
        "",
        f"Shop `{meta['shop_name']}` ({meta['product_count']} products; {meta['total_products']} products in the "
        f"database), {meta['iterations']} iterations (median), external calls stubbed"
        + (f" with a {meta['external_delay']} s delay" if meta["external_delay"] else "")
        + ".",
        "",
    ]
    if compare:
        lines.append("| scenario | statements | sql ms | wall ms | checkouts | held ms |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
        for name, after in results["scenarios"].items():
            before = compare["scenarios"].get(name)
            cells = []
            for field in FIELDS:
                if before is None:
                    cells.append(f"{after[field]}")
                else:
                    cells.append(f"{before[field]} → **{after[field]}**")
            lines.append(f"| {name} | " + " | ".join(cells) + " |")
    else:
        lines.append("| scenario | status | statements | sql ms | wall ms | checkouts | held ms |")
        lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: |")
        for name, row in results["scenarios"].items():
            lines.append(f"| {name} | {row['status']} | " + " | ".join(str(row[field]) for field in FIELDS) + " |")
    if results.get("explain"):
        lines += ["", "#### EXPLAIN ANALYZE of the foreign-key lookups", ""]
        if compare and compare.get("explain"):
            lines.append("| query | scan before | ms before | scan after | ms after |")
            lines.append("| --- | --- | ---: | --- | ---: |")
            for name, after in results["explain"].items():
                before = compare["explain"].get(name, {})
                lines.append(
                    f"| {name} | {before.get('scan', '-')} | {before.get('ms', '-')} | {after['scan']} | {after['ms']} |"
                )
        else:
            lines.append("| query | top node | scan | rows | ms |")
            lines.append("| --- | --- | --- | ---: | ---: |")
            for name, row in results["explain"].items():
                lines.append(f"| {name} | {row['node']} | {row['scan']} | {row['rows']} | {row['ms']} |")
    return "\n".join(lines) + "\n"


def _git_branch() -> str:
    import shutil
    import subprocess

    git = shutil.which("git")
    if git is None:
        return ""
    completed = subprocess.run([git, "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True)  # noqa: S603
    return completed.stdout.strip()


# --- Main -----------------------------------------------------------------------------------------------------------


def main() -> int:
    args = parse_args()
    db_uri = os.environ.get("DATABASE_URI")
    if not db_uri:
        print("Set DATABASE_URI to a scratch copy of the database (never the dev or prod database).", file=sys.stderr)
        return 2
    if db_uri.rstrip("/").endswith(("/shop", "/shop-test")):
        print("Refusing to benchmark the dev or test database; point DATABASE_URI at a copy.", file=sys.stderr)
        return 2
    os.environ.setdefault("MCP_ENABLED", "false")
    os.environ["MAIL_ENABLED"] = "true"
    os.environ["SHOP_MAIL_ENABLED"] = "true"
    os.environ.setdefault("SENTRY_DSN", "")

    import psycopg2
    from psycopg2.extras import register_uuid

    register_uuid()
    raw = psycopg2.connect(db_uri)
    data = discover(raw, args.shop)
    if args.scale:
        print(f"Scaling: cloning shop {data['shop_name']} x{args.scale} ...", file=sys.stderr)
        scale_catalogue(raw, data["shop_id"], args.scale)
        data = discover(raw, data["shop_id"])
        if args.scale_only:
            print(f"Done: {data['total_products']} products in the database.", file=sys.stderr)
            return 0
    prepare_shop(raw, data)

    import structlog
    from fastapi.testclient import TestClient

    from server.crud.crud_api_key import api_key_crud
    from server.db import db
    from server.main import app  # noqa: E402 -- settings must come from the environment set above
    from server.security import Principal, current_principal

    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.CRITICAL))
    logging.disable(logging.CRITICAL)
    install_stubs(args.external_delay)
    admin = lambda: Principal(kind="user", subject="bench", groups=("admins",))  # noqa: E731
    app.dependency_overrides[current_principal] = admin

    label = args.label or _git_branch() or "run"
    results: dict[str, Any] = {
        "meta": {
            "label": label,
            "shop_name": data["shop_name"],
            "shop_id": str(data["shop_id"]),
            "product_count": data["product_count"],
            "total_products": data["total_products"],
            "iterations": args.iterations,
            "external_delay": args.external_delay,
            "stock_toggle": data["stock_toggle"],
        },
        "scenarios": {},
    }

    with TestClient(app) as client:  # runs the startup migrations against the scratch copy
        meter = Meter(db.wrapped_database.engine)
        shop = data["shop_id"]
        cart = [str(product_id) for product_id in data["cart_ids"]]
        order_lines = [{"product_id": pid, "product_name": "bench", "quantity": 1} for pid in cart]

        def get(url: str, **kwargs: Any) -> Callable[[], int]:
            return lambda: client.get(url, **kwargs).status_code

        def post(url: str, body: Any) -> Callable[[], int]:
            return lambda: client.post(url, json=body).status_code

        def create_order() -> int:
            return client.post(
                "/orders/", json={"shop_id": str(shop), "account_name": "bench@example.com", "order_info": order_lines}
            ).status_code

        def complete_order() -> int:
            created = client.post(
                "/orders/", json={"shop_id": str(shop), "account_name": "bench@example.com", "order_info": order_lines}
            )
            order_id = created.json()["id"]
            meter.reset()  # measure only the PATCH
            return client.patch(f"/orders/{order_id}", json={"status": "complete"}).status_code

        _, plaintext = api_key_crud.mint(shop_id=shop, name="bench")

        def api_key_request() -> int:
            app.dependency_overrides.pop(current_principal, None)
            try:
                return client.get(f"/shops/{shop}/products/?limit=1", headers={"X-API-Key": plaintext}).status_code
            finally:
                app.dependency_overrides[current_principal] = admin

        scenarios: dict[str, Callable[[], int]] = {
            "GET /prices/?lang=main (full catalogue)": get(f"/shops/{shop}/prices/?lang=main"),
            "GET /prices/?lang=alt1": get(f"/shops/{shop}/prices/?lang=alt1"),
            "POST /prices/ (cart of 10)": post(f"/shops/{shop}/prices/?lang=main", {"products": cart}),
            "GET /products/?limit=100": get(f"/shops/{shop}/products/?limit=100"),
            "GET /products/with_attributes?limit=100": get(f"/shops/{shop}/products/with_attributes?limit=100"),
            "GET /categories/{id}/products?limit=100": get(
                f"/shops/{shop}/categories/{data['category_id']}/products?limit=100"
            ),
            "GET /products/{id}/with_attributes": get(
                f"/shops/{shop}/products/{data['product_with_attributes']}/with_attributes"
            ),
            "GET /orders/check/{10 ids}": get("/orders/check/" + ",".join(str(i) for i in data["order_ids"])),
            "GET /orders/shop/{id}/complete?limit=100": get(
                f"/orders/shop/{data['orders_shop_id']}/complete?limit=100"
            ),
            "POST /orders/quote (10 lines)": post("/orders/quote", {"shop_id": str(shop), "order_info": order_lines}),
            "POST /orders/ (10 lines, new account once)": create_order,
            "PATCH /orders/{id} status=complete": complete_order,
            "GET /products/?limit=1 with X-API-Key": api_key_request,
        }
        for name, call in scenarios.items():
            print(f"  {name} ...", file=sys.stderr)
            results["scenarios"][name] = run_scenario(meter, call, args.iterations)

    if args.explain:
        results["explain"] = explain_queries(raw, data)

    compare = json.loads(args.compare.read_text()) if args.compare else None
    report = render(results, compare)
    if args.json:
        args.json.write_text(json.dumps(results, indent=2, default=str))
    if args.out:
        args.out.write_text(report)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
