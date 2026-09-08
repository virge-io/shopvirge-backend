#!/bin/bash

set -ex

pip3 install uv==0.11.19
uv sync --locked --no-dev
uv run python -m uvicorn server.main:app --port 8000 --host 0.0.0.0
