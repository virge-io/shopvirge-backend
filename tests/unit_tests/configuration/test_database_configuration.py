import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, [10, 5, 30.0, 300]),
        ({"DB_POOL_SIZE": "5", "DB_MAX_OVERFLOW": "0", "DB_POOL_TIMEOUT": "10"}, [5, 0, 10.0, 300]),
        ({"DB_POOL_SIZE": "2", "DB_MAX_OVERFLOW": "3", "DB_POOL_TIMEOUT": "0.5"}, [2, 3, 0.5, 300]),
        ({"DB_POOL_SIZE": "0"}, None),
        ({"DB_POOL_SIZE": "-1"}, None),
        ({"DB_POOL_SIZE": "invalid"}, None),
        ({"DB_MAX_OVERFLOW": "-1"}, None),
        ({"DB_POOL_TIMEOUT": "0"}, None),
        ({"DB_POOL_TIMEOUT": "-1"}, None),
        ({"DB_POOL_TIMEOUT": "inf"}, None),
        ({"DB_POOL_TIMEOUT": "nan"}, None),
    ],
)
def test_database_pool_configuration(tmp_path: Path, overrides: dict[str, str], expected: list[float] | None) -> None:
    # A fresh process exercises startup configuration without opening a DB connection
    # or loading a developer's .env file.
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"DB_POOL_SIZE", "DB_MAX_OVERFLOW", "DB_POOL_TIMEOUT"}
    }
    env.update(overrides)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[3])
    env["DATABASE_URI"] = "postgresql://shop:shop@localhost/shop-test"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json; from server.db.database import Database; "
            "db = Database('postgresql://shop:shop@localhost/shop-test'); "
            "print(json.dumps([db.engine.pool.size(), db.engine.pool._max_overflow, "
            "db.engine.pool.timeout(), db.engine.pool._recycle])); "
            "db.engine.dispose()",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if expected is None:
        assert result.returncode != 0
        assert "ValidationError" in result.stderr
        assert next(iter(overrides)) in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == expected
