#!/usr/bin/env python
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
"""Regenerate ``tests/unit_tests/openapi_snapshot.json`` from the live app.

Run this after any change to the API surface (new endpoint, schema field,
response shape), together with an ``APP_VERSION`` bump in ``server/main.py``.
The drift guard in ``tests/unit_tests/test_openapi_version.py`` fails until the
snapshot and ``APP_VERSION`` agree.

    uv run python bin/regenerate_openapi_snapshot.py

The spec is produced by the *same* helpers the test uses, so a regenerated
snapshot is guaranteed to satisfy the guard rather than merely look right.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tests.unit_tests.test_openapi_version import (  # noqa: E402
    SNAPSHOT_PATH,
    _app_version_from_main,
    _current_openapi,
)


def main() -> int:
    version = _app_version_from_main()
    spec = _current_openapi(version)
    SNAPSHOT_PATH.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {SNAPSHOT_PATH.relative_to(REPO_ROOT)} at version {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
