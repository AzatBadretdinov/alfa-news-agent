"""Create the parent of pytest's configured var/pytest temp directory on a fresh checkout."""
from pathlib import Path


def pytest_configure():
    (Path(__file__).resolve().parents[1] / "var").mkdir(parents=True, exist_ok=True)
