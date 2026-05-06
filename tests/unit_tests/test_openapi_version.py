"""Guard against silent OpenAPI schema drift.

The committed snapshot in ``tests/unit_tests/openapi_snapshot.json`` must
exactly match the current OpenAPI spec (schema **and** version). Any change
to the API surface — new endpoint, schema field, response shape — requires:

  1. Bumping ``APP_VERSION`` in ``server/main.py``.
  2. Regenerating the snapshot at that new version:

         MAIL_TEST_ENDPOINT_ENABLED=false PYTHONPATH=. python -c "import json; \\
         from fastapi import FastAPI; from starlette.responses import JSONResponse; \\
         from server.api.api import api_router; \\
         app = FastAPI(title='ShopVirge API', description='Backend for ShopVirge Shops.', \\
         openapi_url='/openapi.json', docs_url='/docs', redoc_url='/redoc', \\
         version='<new-version>', default_response_class=JSONResponse); \\
         app.include_router(api_router); \\
         json.dump(app.openapi(), open('tests/unit_tests/openapi_snapshot.json', 'w'), indent=2, sort_keys=True)"

The test generates the live spec in a subprocess with
``MAIL_TEST_ENDPOINT_ENABLED=false`` so its result is independent of the
local ``.env``. The ``/mail-test/*`` route (and its request/response schemas)
is a dev-only convenience, never part of the prod API surface, so excluding
it from this comparison is intentional.

The previous version of this guard only fired when ``current_version !=
snapshot_version``. Since the snapshot was committed at one version while
APP_VERSION had already been bumped, that condition was permanently true and
the assert passed for any schema change. Strict equality closes that gap.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN_PY = REPO_ROOT / "server" / "main.py"
SNAPSHOT_PATH = Path(__file__).parent / "openapi_snapshot.json"


def _app_version_from_main() -> str:
    match = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', MAIN_PY.read_text(), re.MULTILINE)
    assert match, f"APP_VERSION not found in {MAIN_PY}"
    return match.group(1)


# Generate the OpenAPI spec in a subprocess with MAIL_TEST_ENDPOINT_ENABLED
# forced off so the result is independent of the local .env (which often turns
# the dev-only mail-test route on). The router's conditional ``include_router``
# is evaluated at import time, so once the module is loaded with the wrong env
# it can't be re-evaluated cleanly inside the same pytest process. The script
# writes its JSON output to a file path passed on argv so structlog/stdout
# noise during import doesn't pollute the spec.
_OPENAPI_GEN_SCRIPT = """
import json, sys
from fastapi import FastAPI
from starlette.responses import JSONResponse
from server.api.api import api_router

app = FastAPI(
    title="ShopVirge API",
    description="Backend for ShopVirge Shops.",
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    version=sys.argv[1],
    default_response_class=JSONResponse,
)
app.include_router(api_router)
with open(sys.argv[2], "w") as fh:
    json.dump(app.openapi(), fh)
"""


def _current_openapi(version: str) -> dict:
    import tempfile

    env = {**os.environ, "MAIL_TEST_ENDPOINT_ENABLED": "false", "PYTHONPATH": str(REPO_ROOT)}
    with tempfile.NamedTemporaryFile("r", suffix=".json", delete=False) as out:
        out_path = out.name
    try:
        result = subprocess.run(
            [sys.executable, "-c", _OPENAPI_GEN_SCRIPT, version, out_path],
            env=env,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"OpenAPI generation subprocess failed (rc={result.returncode}):\n"
                f"--- stderr ---\n{result.stderr}\n--- stdout ---\n{result.stdout}"
            )
        with open(out_path) as fh:
            return json.load(fh)
    finally:
        Path(out_path).unlink(missing_ok=True)


def _strip_version(spec: dict) -> dict:
    return {**spec, "info": {**spec["info"], "version": ""}}


def _diff_summary(current: dict, snapshot: dict) -> str:
    """Best-effort human-readable summary of which paths changed."""
    cur_paths = set(current.get("paths", {}).keys())
    snap_paths = set(snapshot.get("paths", {}).keys())
    added = sorted(cur_paths - snap_paths)
    removed = sorted(snap_paths - cur_paths)
    bits = []
    if added:
        bits.append(f"added paths: {', '.join(added)}")
    if removed:
        bits.append(f"removed paths: {', '.join(removed)}")
    if not bits:
        bits.append("paths unchanged; schema component(s) differ")
    return "; ".join(bits)


def test_openapi_snapshot_in_sync():
    """Snapshot must match the current OpenAPI spec exactly (schema + version)."""
    current_version = _app_version_from_main()
    current = _current_openapi(current_version)
    snapshot = json.loads(SNAPSHOT_PATH.read_text())
    snapshot_version = snapshot.get("info", {}).get("version", "")

    # Sanity check first so the more useful error message wins.
    assert snapshot_version == current_version, (
        f"OpenAPI snapshot version {snapshot_version!r} does not match "
        f"APP_VERSION {current_version!r}. Bump APP_VERSION and/or regenerate "
        f"{SNAPSHOT_PATH.relative_to(REPO_ROOT)} so the two stay in sync."
    )

    if current == snapshot:
        return

    raise AssertionError(
        "OpenAPI snapshot is stale — the live schema differs from the committed one.\n"
        f"  Diff: {_diff_summary(current, snapshot)}\n"
        f"  Fix: bump APP_VERSION in server/main.py, then regenerate "
        f"{SNAPSHOT_PATH.relative_to(REPO_ROOT)} (see module docstring for the command)."
    )


def test_openapi_version_bumped_when_schema_changes():
    """Backstop: even if the snapshot got regenerated at the same version, the
    schema-vs-snapshot comparison after stripping versions must agree.

    With the strict snapshot check above this is largely belt-and-braces, but it
    keeps the version-bump intent visible in the test file and gives a focused
    error message for the most common failure mode."""
    current_version = _app_version_from_main()
    current = _current_openapi(current_version)
    snapshot = json.loads(SNAPSHOT_PATH.read_text())

    if _strip_version(current) == _strip_version(snapshot):
        return

    snapshot_version = snapshot["info"]["version"]
    assert current_version != snapshot_version, (
        f"OpenAPI schema changed but APP_VERSION in server/main.py is still {current_version!r}. "
        f"Bump APP_VERSION and regenerate {SNAPSHOT_PATH.relative_to(REPO_ROOT)}."
    )
