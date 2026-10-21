---
title: Benchmarking database load
description: Measure SQL statements, SQL time and connection hold time per endpoint with bin/benchmark_db.py, and compare a branch against main.
---

# Benchmarking database load

## At a glance

`bin/benchmark_db.py` boots the API in-process against a **copy** of a database, runs the hot endpoints a few
times each and reports, per endpoint: the number of SQL statements, the time spent in SQL, the wall time, how often
a pooled connection was checked out and for how long it was held. Run it once on `main` and once on your branch,
then `--compare` the two JSON files to get the before/after table for your PR. `--explain` adds
`EXPLAIN (ANALYZE, BUFFERS)` for the lookups behind the catalogue's foreign-key indexes.

The script never touches the database it is pointed at beyond what the endpoints themselves write (orders, an API
key), so always point it at a scratch copy.

## Make a scratch copy of the dev database

```bash
export PGPASSWORD=shop
psql -h localhost -U shop -d postgres -c 'CREATE DATABASE shop_bench OWNER shop;'
pg_dump -h localhost -U shop --no-owner --no-privileges shop | psql -h localhost -U shop -d shop_bench -q
```

`pg_dump | psql` works even while a dev server holds connections on `shop`; `CREATE DATABASE … TEMPLATE shop`
does not.

Optionally grow the catalogue so index effects show at a realistic size. This clones the biggest shop's
catalogue (categories, products, translations, tags, attributes, options, values) into *N* synthetic shops:

```bash
DATABASE_URI=postgresql://shop:shop@localhost/shop_bench uv run python bin/benchmark_db.py --scale 20 --scale-only
```

## Run

```bash
# on main
git worktree add ../shopvirge-main main
cp bin/benchmark_db.py ../shopvirge-main/bin/
(cd ../shopvirge-main && DATABASE_URI=postgresql://shop:shop@localhost/shop_bench \
  PYTHONPATH=. ../shopvirge-backend/venv/bin/python bin/benchmark_db.py --explain --json /tmp/before.json)

# on your branch
DATABASE_URI=postgresql://shop:shop@localhost/shop_bench uv run python bin/benchmark_db.py \
  --explain --json /tmp/after.json --compare /tmp/before.json --out /tmp/benchmark.md
```

The app runs its startup migrations against the target database, so the "after" run applies any migration your
branch adds (the "before" run on `main` leaves the database as it was). Re-create the copy before running `main`
again.

Useful flags:

| Flag | Effect |
| --- | --- |
| `--shop UUID` | Benchmark this shop instead of the one with the most products. |
| `--iterations N` | Timed iterations per scenario after one warm-up (default 5; medians are reported). |
| `--external-delay S` | Make the stubbed Stripe/Discord/SMTP/Lambda calls sleep *S* seconds, to show whether a pooled connection is held during them. |
| `--explain` | Add `EXPLAIN (ANALYZE, BUFFERS)` for the foreign-key lookups. |
| `--compare before.json` | Render a before/after markdown table instead of a single-run table. |

External services are always stubbed: no Stripe, Discord, SMTP or Lambda traffic leaves the machine.

## Reading the numbers

| Column | Meaning |
| --- | --- |
| statements | SQL statements the request executed (`before_cursor_execute`). A number that grows with the catalogue is an N+1. |
| sql ms | Time spent executing those statements. |
| wall ms | Request wall time through the in-process test client. |
| checkouts | How many times the request took a connection from the pool. More than one means the code released and re-acquired it. |
| held ms | Total time the request held a pooled connection. This is the number that matters for pool exhaustion: `held ms × requests per second` is the pool size you need. |

For the `EXPLAIN` section, look at the top plan node (`Seq Scan` versus `Index Scan`/`Bitmap Heap Scan`) and the
execution time; the effect is small on the dev copy and large with `--scale`.

## Regression guard

`tests/unit_tests/test_query_budget.py` asserts that the hot endpoints issue the same number of statements for a
small and a larger catalogue, and keeps each under a fixed budget. Use the `query_counter` fixture from
`tests/unit_tests/conftest.py` when you add a list endpoint.

## Troubleshooting

- **`CREATE DATABASE` fails with "being accessed by other users"** — use the `pg_dump | psql` recipe above.
- **`alembic` errors at startup** — the target database is at a newer migration than the checked-out code (you
  ran the branch before `main`). Re-create the copy.
- **Order scenarios return 400 `NOT_ON_SHOP_WIFI`** — the benchmark shop has an IP allowlist; pick another shop
  with `--shop` or clear `shops.allowed_ips` on the copy.
