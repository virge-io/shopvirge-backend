#!/bin/bash

# Load .env file if it exists
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Check if required environment variables are set
if [ -z "$STRIPE_TEST_PUBLIC_KEY" ] || [ -z "$STRIPE_TEST_SECRET_KEY" ]; then
    echo "Error: STRIPE_TEST_PUBLIC_KEY or STRIPE_TEST_SECRET_KEY not set in .env"
    exit 1
fi

# Run the python script
PYTHONPATH=. python3 update_stripe_keys.py
