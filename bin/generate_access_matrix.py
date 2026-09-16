#!/usr/bin/env python
# Copyright 2026 René Dohmen <acidjunk@gmail.com>
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
"""Regenerate ``docs/api/access-matrix.md`` from the live route table.

Run this after any change to a route's mounting (tier, guard, MCP exposure).
The drift guard in ``tests/unit_tests/test_access_matrix.py`` fails until the
page matches.

    uv run python bin/generate_access_matrix.py

The page is produced by the *same* code the test uses, so a regenerated page
is guaranteed to satisfy the guard.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tests.unit_tests.test_access_matrix import DOC_PATH, render, routes  # noqa: E402


def main() -> int:
    found = routes()
    DOC_PATH.write_text(render(found))
    print(f"Wrote {DOC_PATH.relative_to(REPO_ROOT)} ({len(found)} routes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
