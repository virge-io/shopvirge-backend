# Shop backend

A backend for serving pricelists.

## Server

This project only works with Python 3.10 and higher.
If you want to use a virtual environment first create the environment:

```bash
python3 -m venv .venv
source venv/bin/activate
```

You can install the required libraries with pip. The following command will install all the required
libraries for the project. Check out the different files under requirements to more specifically see
which library is used and for what reason.

```bash
pip install -r ./requirements/all.txt
```

A PostgreSQL user and two databases are required ('shop' is the password used by default).

```bash
createuser -sP shop
createdb shop -O shop
createdb shop-test -O shop  # only needed when your DB doesn't have Postgres superuser privileges.
```

Now you should be able to start a hot reloading, api server:
```bash
PYTHONPATH=. uvicorn server.main:app --reload --port 8080
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
PYTHONPATH=. pytest tests/unit_tests
```

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
PYTHONPATH=. alembic upgrade heads
```

Then, to create a new schema migration:

```bash
PYTHONPATH=. alembic revision --autogenerate -m "New schema"
```

This opens a new migration in `/migrations/versions/`

The initial scheme was created with:

```bash
PYTHONPATH=. alembic revision --autogenerate -m "Initial scheme" --head=schema@head --version-path=migrations/versions/schema
```

### General Migration

To create a data migration do the following:

```bash
PYTHONPATH=. alembic revision --message "Name of the migration"
```

This will also create a new revision file where normal SQL can be written like so:

```python
conn = op.get_bind()
res = conn.execute("INSERT INTO products VALUES ('x', 'y', 'z')")
```

## Manual deploy

Activate a python env with SAM installed, fire up Docker if it's not already running and run:

```
sam validate
sam build --use-container --debug
sam package --s3-bucket YOUR_S3_BUCKET \
--output-template-file out.yml --region eu-central-1
```

And then deploy it with:

```
sam deploy --template-file out.yml \
--stack-name fastapi-postgres-boilerplate \
--region eu-central-1 --no-fail-on-empty-changeset \
--capabilities CAPABILITY_IAM
```

A more detailed explanation about the deployment on Amazon lambda can be found on: 
[renedohmen.nl/deploy-fastapi-on-amazon-serverless](https://www.renedohmen.nl/deploy-fastapi-on-amazon-serverless/)

## Reset staging DB

use the RDS superuser to execute this on the staging DB

```
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
REASSIGN OWNED BY rds_super_user TO priceliststaging;
```

Now a prepared prod dump can be imported.

## Deployment problems

Deployment is still a bit rough and I set the needed ENV vars from a local script.

So after a deployment check if the login works in the swagger GUI. Sometimes the ENV var get reset and you have to 
run the `set-env.py` script for that environment. 

Currently, problems happened when:
- upgrading to a new python version via the SAM template
- when a build fails to deploy correctly (Noticed: when I added "-e requirement for pydantic-forms")

Running the `set-env.py` sets vars immediately without the need to restart something.

# Create a user

Set up the ENV var for FIRST_USER and run this command:

```bash
PYTHONPATH=. python server/create_initial_user.py
```

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
To create a virtual environment:
```bash
python -m venv venv    
```

To start venv (virtual environment)
```bash
venv\Scripts\activate  
```
The "venv" can change depending on your folder. **Sometimes** it can also be like:
```bash
.\.venv\Scripts\activate   
```

## Install Requirements

```bash
pip install -r requirements/all.txt
```

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
alembic upgrade heads
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
pytest
```

## Start hot reloading Fastapi
```bash
uvicorn server.main:app --host 127.0.0.1 --port 8080 --reload  
```

Start non hot reloading Fastapi:
```bash
uvicorn server.main:app --host 127.0.0.1 --port 8080 
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