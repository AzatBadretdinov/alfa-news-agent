"""Test an exact local Git object, then stage only news_analysis in an ignored overlay.
No checkout, merge, fetch, push or tracked module changes.
"""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run(*args, **kwargs):
    return subprocess.run(args, cwd=ROOT, check=True, **kwargs)


def main():
    sha = json.loads((ROOT / "integration/sources.lock.json").read_text())["news_analysis_sha"]
    try:
        run("git", "cat-file", "-e", sha + "^{commit}")
    except subprocess.CalledProcessError:
        raise SystemExit("Pinned commit missing locally. Fetch repository branches explicitly, then retry.")
    if run("git", "diff", sha, "--", "company_context", stdout=subprocess.PIPE).stdout:
        raise SystemExit("company_context differs from audited source; review compatibility before staging")
    target = ROOT / "var/sources/news-analysis"
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="source-audit-", dir=target.parent) as directory:
        checkout = Path(directory)
        archive = run("git", "archive", sha, "company_context", "news_analysis", "tests", "data/training_v1", "data/training_v2", stdout=subprocess.PIPE).stdout
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(checkout, filter="data")
        subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=checkout,
                       env={**os.environ, "PYTHONPATH": str(checkout)}, check=True)
        stamp = {"sha": sha, "module": "news_analysis", "branch_tests": "passed"}
        if target.exists():
            if json.loads((target / "source.json").read_text()) != stamp:
                raise SystemExit("Existing overlay has a different source; inspect before replacing")
            expected = {p.relative_to(checkout / "news_analysis"): p.read_bytes() for p in (checkout / "news_analysis").rglob("*") if p.is_file() and "__pycache__" not in p.parts}
            actual = {p.relative_to(target / "news_analysis"): p.read_bytes() for p in (target / "news_analysis").rglob("*") if p.is_file() and "__pycache__" not in p.parts}
            if expected != actual:
                raise SystemExit("Overlay changed locally; inspect before replacing")
        else:
            staged = checkout / "staged"
            staged.mkdir()
            shutil.copytree(checkout / "news_analysis", staged / "news_analysis", ignore=shutil.ignore_patterns("__pycache__"))
            (staged / "source.json").write_text(json.dumps(stamp, indent=2) + "\n")
            staged.rename(target)
    print(f"Verified overlay: {target} @ {sha}")


if __name__ == "__main__":
    main()
