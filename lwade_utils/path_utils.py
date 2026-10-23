import os

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GRPC_PACKAGE_INSTALL_PATH = os.path.normpath(os.path.join(PROJECT_DIR, "packages/grpc"))
SSE_PACKAGE_INSTALL_PATH = os.path.normpath(os.path.join(PROJECT_DIR, "packages/sse"))
A2A_PACKAGE_INSTALL_PATH = os.path.normpath(os.path.join(PROJECT_DIR, "packages/a2a"))
MCP_PACKAGE_INSTALL_PATH = os.path.normpath(os.path.join(PROJECT_DIR, "packages/mcp"))
