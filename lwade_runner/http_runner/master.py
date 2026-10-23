# Http Master
import argparse
import os
import platform
import signal
import subprocess
import sys
import time

from health_server import register_process

from lwade_config import config
from lwade_utils.bootload import install_dependencies
from lwade_utils.log_utils import get_custom_logger
from lwade_utils.path_utils import (
    PROJECT_DIR,
    SSE_PACKAGE_INSTALL_PATH,
    A2A_PACKAGE_INSTALL_PATH,
    MCP_PACKAGE_INSTALL_PATH
)
from lwade_utils.runner_utils import RunnerType, AppRunner

logger = get_custom_logger(__name__, "%(asctime)s - http - master - %(levelname)s - %(message)s")

class Master:
    def __init__(self, include_workers, sse_workspace_dir, a2a_workspace_dir, mcp_workspace_dir):
        self.include_workers = include_workers
        self.sse_workspace_dir = sse_workspace_dir
        self.a2a_workspace_dir = a2a_workspace_dir
        self.mcp_workspace_dir = mcp_workspace_dir
        self.gunicorn_proc = None
        self.health_server = None

    def cleanup(self, signum=None, frame=None):
        print("\nShutting down...")
        if self.gunicorn_proc and self.gunicorn_proc.poll() is None:
            self.gunicorn_proc.terminate()
            try:
                self.gunicorn_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.gunicorn_proc.kill()
                self.gunicorn_proc.wait()
            print("👋 Gunicorn stopped.")
        sys.exit(0)

    def register_signal_handlers(self):
        """Register SIGINT/SIGTERM handlers."""
        signal.signal(signal.SIGINT, self.cleanup)
        signal.signal(signal.SIGTERM, self.cleanup)

    def serve(self):
        env = os.environ.copy()
        env["INCLUDE_WORKERS"] = self.include_workers

        worker_runners = AppRunner.parse(self.include_workers)
        if RunnerType.SSE in worker_runners:
            install_dependencies(self.sse_workspace_dir, SSE_PACKAGE_INSTALL_PATH)
            env["SSE_WORKSPACE_DIR"] = self.sse_workspace_dir
        if RunnerType.A2A in worker_runners:
            install_dependencies(self.a2a_workspace_dir, A2A_PACKAGE_INSTALL_PATH)
            env["A2A_WORKSPACE_DIR"] = self.a2a_workspace_dir
        if RunnerType.MCP in worker_runners:
            install_dependencies(self.mcp_workspace_dir, MCP_PACKAGE_INSTALL_PATH)
            env["MCP_WORKSPACE_DIR"] = self.mcp_workspace_dir

        if platform.system() == "Windows":
            cmd = [
                sys.executable, "-m", "uvicorn",
                "--workers", str(config.HTTP_WORKERS),
                "--host", "127.0.0.1",
                "--port", str(config.HTTP_PORT),
                "--log-level", "info",
                "lwade_runner.http_runner.worker:app",
            ]
        else:
            cmd = [
                sys.executable, "-m", "gunicorn",
                "-c", os.path.join(PROJECT_DIR, "lwade_runner/http_runner/gunicorn_config.py"),
                "lwade_runner.http_runner.worker:app",
            ]
        self.gunicorn_proc = subprocess.Popen(cmd, stdout=sys.stdout, stderr=subprocess.STDOUT, env=env)
        print(f"Started Gunicorn (PID={self.gunicorn_proc.pid}) serving FastAPI on :{config.HTTP_PORT}")
        register_process(self.gunicorn_proc.pid, "http-server-manager")

    def monitor_server(self):
        """Monitor Gunicorn process and exit if it dies unexpectedly."""
        try:
            while True:
                time.sleep(1)
                if self.gunicorn_proc.poll() is not None:
                    print(f"Gunicorn exited unexpectedly (code={self.gunicorn_proc.returncode})")
                    # break
        except KeyboardInterrupt:
            self.cleanup()

    def run(self):
        self.register_signal_handlers()
        self.serve()

        print("Http Master pid: ", os.getpid())
        print("Http Unicorn pid: ", self.gunicorn_proc.pid)

        print(f"FastAPI service with Gunicorn-level health check ready.")
        print(f"   - App: http://localhost:{config.HTTP_PORT}")
        print(f"   - Health: http://localhost:9002/health")
        print("\nPress Ctrl+C to stop.\n")
        self.monitor_server()


# ====== 4. 主函数 ======
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Http Master Runner")
    parser.add_argument(
        "--include-workers",
        type=str,
        default='sse,mcp,a2a',
        help="Http server worker(s). Supports single or comma-separated values.\n"
             "Examples:\n"
             "  --runner mcp            (Only mcp)\n"
             "  --runner mcp,sse        (mcp and sse)\n"
             "Valid types: " + ", ".join(RunnerType.get_http_worker_values())
    )
    parser.add_argument(
        "--sse-workspace-dir",
        help="Path to sse app directory"
    )
    parser.add_argument(
        "--a2a-workspace-dir",
        help="Path to a2a app directory"
    )
    parser.add_argument(
        "--mcp-workspace-dir",
        help="Path to mcp app directory"
    )
    args = parser.parse_args()

    runner = Master(
        include_workers=args.include_workers,
        sse_workspace_dir=args.sse_workspace_dir,
        a2a_workspace_dir=args.a2a_workspace_dir,
        mcp_workspace_dir=args.mcp_workspace_dir,
    )
    runner.run()
