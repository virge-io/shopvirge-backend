#!/bin/bash
set -e
cd -- "$(dirname -- "$0")"
if [ -d ".venv" ]; then
    echo "Activating venv found in '.venv/'"
    # shellcheck disable=SC1091
    source .venv/bin/activate
else
    echo "Activating venv found in 'venv/'"
    # shellcheck disable=SC1091
    source venv/bin/activate
fi

# FastAPI will autoload .env so this will only handle other known locations that devs can have
# shellcheck disable=SC2002
if [ -f "env" ]; then
    echo "Loading ENV vars from 'env' file"
    # shellcheck disable=SC2046
    export $(cat env | grep -v ^# | xargs)
fi

if [ "$1" = "dev" ]; then
    echo "Starting auto-reloading webserver"
    PYTHONPATH=. uvicorn server.main:app --reload --port 8080 --host 0.0.0.0
elif [ "$1" = "demo" ]; then
    # Same port as dev, but on the dedicated demo DB. An exported DATABASE_URI wins over .env.
    # The demo shop is reset (no products, no categories) on every start; stop the dev server first.
    # Optional second argument: the shop's About text (else $DEMO_SHOP_ABOUT, else empty).
    export DATABASE_URI="${DEMO_DATABASE_URI:-postgresql://shop:shop@localhost/shop_demo}"
    export DEMO_SHOP_ABOUT="${2:-${DEMO_SHOP_ABOUT:-}}"
    echo "Demo mode: resetting the dedicated demo shop"
    PYTHONPATH=. python -c 'import os; from scripts.seed_demo_shop import validate_demo_database; validate_demo_database(os.environ["DATABASE_URI"])'
    PYTHONPATH=. alembic upgrade heads
    PYTHONPATH=. python scripts/seed_demo_shop.py
    echo "Starting webserver (no reload) on the demo database"
    PYTHONPATH=. uvicorn server.main:app --port 8080 --host 0.0.0.0
else
    echo "Starting threaded webserver"
    bin/server
fi
