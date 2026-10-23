"""One local entry point for all three processes, with deterministic synthetic data."""
import argparse
import os
from pathlib import Path
import signal
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from integration.bootstrap import node_fixture
from smoke import smoke


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--native-providers", action="store_true", help="Run roles 2 and 3 as separate HTTP adapter processes")
    args = parser.parse_args()
    if not (ROOT / "dist/integration/index.js").is_file():
        raise SystemExit("Run npm run build first")
    processes, logs = [], []
    workspace = persistent(temporary=args.smoke)
    def stopping(*_):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, stopping)
    try:
        with workspace as directory:
            directory = Path(directory)
            port = free_port() if args.smoke else int(os.environ.get("PORT", "8000"))
            ml_port = free_port() if args.smoke else int(os.environ.get("ML_PORT", "8101"))
            mock_port = free_port() if args.smoke else int(os.environ.get("MOCK_PORT", "8102"))
            agent_port = free_port() if args.smoke else int(os.environ.get("AGENT_PORT", "8202"))
            env = {**os.environ, "HOST": "127.0.0.1", "LLM_MODE": "demo", "CONTEXT_MODE": "fixture",
                   "CONTEXT_DB": str(directory / "context.sqlite3"), "DATA_DIR": str(node_fixture(directory / "node-data")),
                   "DB_PATH": str(directory / "node.sqlite3"), "ML_URL": f"http://127.0.0.1:{ml_port}",
                   "RETRIEVAL_URL": f"http://127.0.0.1:{mock_port}", "AGENT_URL": f"http://127.0.0.1:{agent_port if args.native_providers else mock_port}"}
            # This runner intentionally uses fixtures/demo. Existing data and live models require explicit service commands.
            commands = [("ml", [sys.executable, "-m", "uvicorn", "integration.app:app", "--host", "127.0.0.1", "--port", str(ml_port)], {}),
                        ("mocks", ["node", "dist/integration/mock-server.js"], {"PORT": str(mock_port)}),
                        ("gateway", ["node", "dist/integration/index.js"], {"PORT": str(port)})]
            if args.native_providers:
                env.update(RETRIEVAL_MODE="http", AGENT_MODE="http")
                commands[1:2] = [
                    ("retrieval", ["node", "dist/integration/provider-server.js"], {"PORT": str(mock_port), "SERVICE_KIND": "retrieval", "DB_PATH": str(directory / "retrieval.sqlite3")}),
                    ("agent", ["node", "dist/integration/provider-server.js"], {"PORT": str(agent_port), "SERVICE_KIND": "agent", "DB_PATH": str(directory / "agent.sqlite3")}),
                ]
            for name, command, overrides in commands:
                logfile = (directory / (name + ".log")).open("w+")
                logs.append(logfile)
                processes.append(subprocess.Popen(command, cwd=ROOT, env={**env, **overrides}, stdout=logfile, stderr=subprocess.STDOUT))
            base = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + 45
            urls = [f"http://127.0.0.1:{ml_port}/v1/health", f"http://127.0.0.1:{mock_port}/v1/health", base + "/v1/health"]
            if args.native_providers:
                urls.insert(2, f"http://127.0.0.1:{agent_port}/v1/health")
            for url in urls:
                while True:
                    if any(p.poll() is not None for p in processes):
                        raise RuntimeError("A service exited during startup")
                    try:
                        with urlopen(url, timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        pass
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Startup timeout")
                    time.sleep(0.1)
            if args.smoke:
                smoke(base)
            else:
                print(f"Open {base}/integration | Ctrl+C stops all service processes", flush=True)
                while all(p.poll() is None for p in processes):
                    time.sleep(0.5)
                raise RuntimeError("A service exited; inspect var/integration/dev/*.log")
    except KeyboardInterrupt:
        pass
    except Exception:
        for log in logs:
            log.flush(); log.seek(0); print(log.read()[-8000:], file=sys.stderr)
        raise
    finally:
        for p in processes:
            if p.poll() is None: p.terminate()
        for p in processes:
            try: p.wait(timeout=5)
            except subprocess.TimeoutExpired: p.kill(); p.wait()
        for log in logs: log.close()
        workspace.cleanup()


class persistent:
    def __init__(self, temporary=False):
        self.temporary = temporary
        self.path = None
    def __enter__(self):
        if self.temporary:
            self.path = Path(tempfile.mkdtemp(prefix="alfa-smoke-", dir=ROOT / "var" if (ROOT / "var").exists() else ROOT))
            return self.path
        path = ROOT / "var/integration/dev"
        path.mkdir(parents=True, exist_ok=True)
        return path
    def __exit__(self, *_):
        pass
    def cleanup(self):
        if self.temporary and self.path:
            shutil.rmtree(self.path)


if __name__ == "__main__":
    main()
