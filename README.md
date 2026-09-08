# Shop backend

A backend for serving pricelists.

📖 Full docs: <https://shopvirge.readthedocs.io/>

## Server

This project targets Python 3.11. Dependencies are managed with
[uv](https://docs.astral.sh/uv/) — `pyproject.toml` declares them and `uv.lock`
pins the exact resolved versions.

Install uv once (see the [uv install docs](https://docs.astral.sh/uv/getting-started/installation/)),
then create the environment and install everything:

```bash
uv sync --dev
```

That creates `.venv/` and installs the runtime dependencies plus the `dev` group
(which includes `test`). For a runtime-only install use `uv sync --no-dev`; add
`--group docs` when you also want the MkDocs toolchain.

Prefix commands with `uv run` to use that environment without activating it
(e.g. `uv run pytest`), or `source .venv/bin/activate` as usual.

A PostgreSQL user and two databases are required ('shop' is the password used by default).

```bash
createuser -sP shop
createdb shop -O shop
createdb shop-test -O shop  # only needed when your DB doesn't have Postgres superuser privileges.
```

Now you should be able to start a hot reloading, api server:
```bash
PYTHONPATH=. uv run uvicorn server.main:app --reload --port 8080
```

Or run a threaded server and auto-apply migrations on launch:
```bash
/bin/server
````

## Connecting Claude Code to the MCP server

Prod exposes a Model Context Protocol endpoint at `/mcp`. Claude Code can drive it via Cognito Hosted UI browser-login (recommended for humans) or with a per-shop API key (recommended for scripts). See [`docs/api/mcp.md`](docs/api/mcp.md) for the full reference, including how to mint API keys and add new MCP tools.

**Browser-login (Cognito):**

```bash
claude mcp add --transport http shopvirge https://api.shopvirge.com/mcp/ \
  --callback-port 7777
```

Then `/mcp` inside Claude Code → **Authenticate** → Cognito Hosted UI opens → log in → done. The callback port must match what's whitelisted on the `shopvirge-mcp` Cognito app client (currently `7777`).

**API-key (headless):**

```bash
claude mcp add --transport http shopvirge https://api.shopvirge.com/mcp/ \
  --header "X-API-Key: sv_…"
```

## Running tests
```bash
uv run pytest tests/unit_tests
```

`pytest` finds the repo root through `[tool.pytest.ini_options] pythonpath` in
`pyproject.toml`, so it does not need `PYTHONPATH=.`. alembic and uvicorn still do.

## Configuring the server

All configuration is done via ENV vars.

```bash
export SESSION_SECRET="SUPER_DUPER_SECRET"
export TESTING=False
```

> Note: FastAPI will detect and automatically load an existing `.env` file.

## DB Migrations

The database schema is maintained by migrations (see `/migrations` for the
definitions). Pending migrations are automatically applied when starting the
server.

There are 2 migration branches that move independently of one another. The data branch which contains
all needed data (e.g. examples etc.) and the Schema branch.

### Schema migration

Run this command prior to your first schema migration or let the webserver create you DB:

```bash
PYTHONPATH=. uv run alembic upgrade heads
```

Then, to create a new schema migration:

```bash
PYTHONPATH=. uv run alembic revision --autogenerate -m "New schema"
```

This opens a new migration in `/migrations/versions/`

The initial scheme was created with:

```bash
PYTHONPATH=. uv run alembic revision --autogenerate -m "Initial scheme" --head=schema@head --version-path=migrations/versions/schema
```

### General Migration

To create a data migration do the following:

```bash
PYTHONPATH=. uv run alembic revision --message "Name of the migration"
```

This will also create a new revision file where normal SQL can be written like so:

```python
conn = op.get_bind()
res = conn.execute("INSERT INTO products VALUES ('x', 'y', 'z')")
```

## Deploying

Deployment is AWS App Runner, configured by `apprunner.yaml` at the repo root. The build and pre-run steps install [uv](https://docs.astral.sh/uv/)
and run `uv sync --locked --no-dev`, so the deployed dependency set is exactly the
one pinned in `uv.lock`. Runtime configuration and secrets are read from the SSM
parameters listed under `run.secrets` in that file.

A `Dockerfile` is also provided and builds the same environment for container hosts.

## Reset staging DB

use the RDS superuser to execute this on the staging DB

```
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
REASSIGN OWNED BY rds_super_user TO priceliststaging;
```

Now a prepared prod dump can be imported.

# Creating a user

Users are not created from this repo. Authentication is AWS Cognito, and the user
pool, app clients and groups are managed outside this codebase — a user is granted
access to a shop by being added to a Cognito group named after that shop's UUID.
See [Authentication & Authorization](docs/api/authentication.md).

# Updating architecture diagrams

The C4 diagrams under `docs/diagrams/` are authored in [drawio](https://www.drawio.com/) (Apache 2.0, free). After editing a `.drawio` source, re-export it to SVG so the docs site picks up the change:

```bash
bin/export-diagrams.sh
```

The script shells out to the drawio desktop CLI, so drawio needs to be on your `PATH`.

## Install drawio desktop

### macOS

```bash
brew install --cask drawio
```

### Linux

Via snap (quickest on Ubuntu):

```bash
sudo snap install drawio
```

Or grab the `.deb` / `.AppImage` from the [drawio-desktop releases](https://github.com/jgraph/drawio-desktop/releases).

**Headless Linux** — on a server or CI job without an X display, drawio (Electron under the hood) refuses to launch. Wrap the export with `xvfb`:

```bash
sudo apt install xvfb
xvfb-run -a bin/export-diagrams.sh
```

### No install?

Open each `.drawio` at <https://app.diagrams.net> → **File → Export as → SVG…** and save the result into `docs/assets/diagrams/` under the matching base filename (e.g. `ShopVirge_C1.svg`).

# Running on Windows

## Server
## Install dependencies

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```bash
uv sync --dev
```

uv creates and manages `.venv\` for you. To activate it:

```bash
.venv\Scripts\activate
```

Or skip activation entirely and prefix commands with `uv run`.

## DB Setup

To make a superuser under the name "shop". Also recommended to make the **password** "shop" for simplicity:

```bash
createuser -sP shop
```

To make the database "shop" under the user "shop":

```bash
createdb shop -U shop
```

## DB Migration / Import DB dump if you can't do migration

Migration DIDN'T work for me, but I believe this is the line to do migration:

```bash
PYTHONPATH=. uv run alembic upgrade heads
```

So rather I imported the migration, asked for a dump from Rene and **import** it to the DB:
```bash
psql -U shop -d shop -f "{File path name for the import saved on your device}"
```

## Configuring the server (env file)
You will need an env file first, name should be something like `env` or `config.env` (my example uses this). This how you load the env file:
```bash
Get-Content .\config.env | ForEach-Object {
if ($_ -match '^\s*#') { return }  # Ignore comments
if ($_ -match '^\s*$') { return }  # Ignore empty lines
$name, $value = $_ -split '=', 2
[System.Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim(), [System.EnvironmentVariableTarget]::Process)
}
```
To confirm that the env file is retrieved correctly, check if the variables are correct by doing this:
```bash
echo $env:DATABASE_URI #can try other variables
```

## Running Tests
```bash
uv run pytest
```

## Start hot reloading Fastapi
```bash
uv run uvicorn server.main:app --host 127.0.0.1 --port 8080 --reload
```

Start non hot reloading Fastapi:
```bash
uv run uvicorn server.main:app --host 127.0.0.1 --port 8080
```

# License and copyright info

Copyright (C) 2024 René Dohmen <acidjunk@gmail.com>

Licensed under the Apache License Version 2.0. A copy of the LICENSE is included in the project.
There is a `licenses` folder that contains more detailed copyright info about the project and it's
components. Some work is based on, or inspired by, other Open Source projects, like
[orchestrator-core](https://github.com/workfloworchestrator/orchestrator-core) and
[nwa-stdlib](https://github.com/workfloworchestrator/nwa-stdlib) on which I collaborated.


# Quick launch shop-poc stack
In bin/launch-shop-poc.sh you can find a script that will launch the whole shop-poc stack with one command.
Move it to your projects folder and run it.
You might have to add a .env file to it knows where to find all the projects.
Assuming your projects folder is called `Projects` you can use:
```bash
mkdir -p ~/Projects/.Launch
cp ~/Projects/shop-backend/bin/launch-shop-poc-stack.sh ~/Projects/.Launch/
cp ~/Projects/shop-backend/bin/QuickLaunchShop-poc.md ~/Projects/.Launch/
chmod +x ~/Projects/.Launch/launch-shop-poc-stack.sh
```
And then add an alias because might as well: `alias lpoc="~/Projects/.Launch/launch-shop-poc-stack.sh -eu -fl"`
Also have a look at the QuickLaunchShop-poc.md guide file.
