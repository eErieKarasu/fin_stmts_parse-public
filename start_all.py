import os
import subprocess
import sys

from lwade_utils.argparse_utils import BaseArgumentParser
from lwade_utils.runner_utils import AppRunner, RunnerType


def main():
    parser = BaseArgumentParser(
        description="Start app with specified runner type."
    )
    args = parser.parse_args()

    app_runners = AppRunner.parse(args.runner)

    processes = []

    metrics_server = subprocess.Popen([
        sys.executable,
        "-m",
        "metrics_server"
    ])
    processes.append(metrics_server)

    health_server = subprocess.Popen([
        sys.executable,
        "-m",
        "health_server"
    ])
    processes.append(health_server)

    if RunnerType.GRPC in app_runners:
        grpc_server = subprocess.Popen([
            sys.executable,
            "-m",
            "lwade_runner.grpc_runner.master",
            "--workspace-dir", args.grpc_app_path,
        ])
        processes.append(grpc_server)

    http_runners = [runner for runner in app_runners if runner != RunnerType.GRPC ]

    if http_runners:
        http_server = subprocess.Popen([
            sys.executable,
            "-m",
            "lwade_runner.http_runner.master",
            "--include-workers", ','.join([runner.value for runner in http_runners]),
            "--sse-workspace-dir", args.sse_app_path,
            "--a2a-workspace-dir", args.a2a_app_path,
            "--mcp-workspace-dir", args.mcp_app_path,
        ])
        processes.append(http_server)

    if os.getenv("ENABLE_FRONTEND", "false").lower() in ("true", "1", "yes", "on"):
        frontend_server = subprocess.Popen([
            sys.executable,
            "-m",
            "frontend.server",
        ])
        processes.append(frontend_server)

    try:
        for proc in processes:
            proc.wait()
    except KeyboardInterrupt:
        for proc in processes:
            proc.terminate()
        for proc in processes:
            proc.wait()

if __name__ == '__main__':
    main()
