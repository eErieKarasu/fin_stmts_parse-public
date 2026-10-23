import argparse
import os

from lwade_utils.path_utils import PROJECT_DIR
from lwade_utils.runner_utils import RunnerType


class BaseArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_base_arguments()
        self.formatter_class = argparse.RawTextHelpFormatter

    def _add_base_arguments(self):
        """Add basic arguments"""
        self.add_argument(
            "--runner",
            type=str,
            default="all",
            help="Runner type(s). Supports single or comma-separated values.\n"
                 "Examples:\n"
                 "  --runner grpc            (Only gRPC)\n"
                 "  --runner grpc,sse        (gRPC and SSE)\n"
                 "  --runner all             (All runners, default)\n"
                 "Valid types: " + ", ".join(RunnerType.get_all_values())
        )
        self.add_argument(
            "--grpc-app-path",
            default=os.path.join(PROJECT_DIR, "apps/grpc-app"),
            help="Path to custom gRPC app directory or file"
        )
        self.add_argument(
            "--sse-app-path",
            default=os.path.join(PROJECT_DIR, "apps/sse-app"),
            help="Path to custom SSE app directory or file"
        )
        self.add_argument(
            "--a2a-app-path",
            default=os.path.join(PROJECT_DIR, "apps/a2a-app"),
            help="Path to custom A2A app directory or file"
        )
        self.add_argument(
            "--mcp-app-path",
            default=os.path.join(PROJECT_DIR, "apps/mcp-app"),
            help="Path to custom MCP app directory or file"
        )