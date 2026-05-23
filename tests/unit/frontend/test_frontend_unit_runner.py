from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def test_frontend_pure_utility_tests_pass():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not available")

    project_root = Path(__file__).resolve().parents[3]
    test_file = project_root / "tests" / "unit" / "frontend" / "frontend-utils.test.mjs"

    result = subprocess.run(
        [node, "--test", str(test_file)],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
