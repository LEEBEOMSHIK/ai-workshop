import subprocess
import sys
from importlib.metadata import version

import pytest


@pytest.mark.integration
def test_pinned_paddle_runtime_packages_are_installed() -> None:
    assert version("paddlepaddle") == "3.2.2"
    assert version("paddleocr") == "3.7.0"


@pytest.mark.integration
def test_paddleocr_imports_in_a_fresh_worker_process() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", "import paddleocr; print(paddleocr.__version__)"],
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip().endswith("3.7.0")
