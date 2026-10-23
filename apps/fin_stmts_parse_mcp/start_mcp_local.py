import argparse
import os
import sys
from pathlib import Path

# Support the existing documented invocation from a clean source checkout.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import uvicorn

from lwade_runner.http_runner.mcp.worker import Worker


DEFAULT_WORKSPACE_DIR = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description="Start fin_stmts_parse_mcp as a local MCP HTTP server.")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind. Defaults to 127.0.0.1 for local MCP testing.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port to bind. Defaults to 8765.",
    )
    parser.add_argument(
        "--env",
        default="local",
        help="RUNNING_ENV value. Defaults to local.",
    )
    parser.add_argument(
        "--workspace-dir",
        default=str(DEFAULT_WORKSPACE_DIR),
        help="Workspace directory of the MCP app. Defaults to apps/fin_stmts_parse_mcp.",
    )
    args = parser.parse_args()

    os.environ["RUNNING_ENV"] = args.env

    app = Worker(args.workspace_dir).create_app()

    print(f"Starting fin_stmts_parse_mcp on http://{args.host}:{args.port}")
    print(f"RUNNING_ENV={args.env}")
    print(f"WORKSPACE_DIR={args.workspace_dir}")

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
