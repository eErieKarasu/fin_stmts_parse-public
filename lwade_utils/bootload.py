import sys
import os
from pathlib import Path
import subprocess
import importlib.util
from typing import List

from lwade_config import Config
from lwade_utils.path_utils import (
    GRPC_PACKAGE_INSTALL_PATH, SSE_PACKAGE_INSTALL_PATH,
    A2A_PACKAGE_INSTALL_PATH, MCP_PACKAGE_INSTALL_PATH)

_DEPENDENCE_DIR = {
    "grpc": GRPC_PACKAGE_INSTALL_PATH,
    "sse": SSE_PACKAGE_INSTALL_PATH,
    "a2a": A2A_PACKAGE_INSTALL_PATH,
    "mcp": MCP_PACKAGE_INSTALL_PATH
}


def install_dependencies(workspace_dir, package_dir):
    """安装用户依赖"""
    req_path = os.path.join(workspace_dir, "requirements.txt")
    if os.path.exists(req_path):
        skip_runtime_install = os.getenv("SKIP_RUNTIME_PIP_INSTALL", "").lower() in ("true", "1", "yes", "on")
        if skip_runtime_install:
            print("[System] Skipping runtime dependency installation because SKIP_RUNTIME_PIP_INSTALL is enabled.")
            return

        print("[System] Installing user dependencies...")

        if not os.path.exists(package_dir):
            os.makedirs(package_dir)
        try:
            subprocess.check_call([
                sys.executable, "-m", "pip", "install",
                "--no-cache-dir",
                "--trusted-host", Config.PIP_MIRROR_HOSTNAME,
                "-i", Config.PIP_MIRROR_URL,
                "--target", package_dir,
                "-r", req_path
            ])
        except subprocess.CalledProcessError as e:
            print(f"[System] Dependency installation failed: {e}")
            sys.exit(1)
    else:
        print("[System] No requirements.txt found, skipping.")


def load_entry_module(workspace_dir, service_type, entry_file):
    entry_script_path = os.path.join(workspace_dir, entry_file)
    if not os.path.exists(entry_script_path):
        raise FileNotFoundError(f"{entry_file} not found in workspace directory.")

    workspace_root = os.path.dirname(os.path.abspath(entry_script_path))
    sys.path.insert(0, workspace_root)
    sys.path.insert(0, os.path.dirname(workspace_root))
    dependencies_dir = _DEPENDENCE_DIR[service_type]
    sys.path.insert(0, dependencies_dir)

    workspace_name = os.path.basename(workspace_root)

    spec = importlib.util.spec_from_file_location(f"{workspace_name}_{service_type}_entry", entry_script_path)
    if spec and spec.loader:
        entry_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(entry_module)
        return entry_module
    else:
        raise ImportError("Failed to import entry module.")


def load_service_module(workspace_dir, service_type):
    service_script_path = os.path.join(workspace_dir, "service.py")
    if not os.path.exists(service_script_path):
        raise FileNotFoundError("service.py not found in workspace directory.")

    workspace_root = os.path.dirname(os.path.abspath(service_script_path))
    sys.path.insert(0, workspace_root)
    sys.path.insert(0, os.path.dirname(workspace_root))
    dependencies_dir = _DEPENDENCE_DIR[service_type]
    sys.path.insert(0, dependencies_dir)

    workspace_name = os.path.basename(workspace_root)

    spec = importlib.util.spec_from_file_location(f"{workspace_name}.service", service_script_path)
    if spec and spec.loader:
        service_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(service_module)
        return service_module
    else:
        raise ImportError("Failed to import service module.")


def check_required_files(source_path: str, required_files: List[str], check_object: str):
    source = Path(source_path).resolve()

    if not source.exists():
        print(f"{check_object} source path does not exist: {source_path}")
        return False

    missing_files = []

    for filename in required_files:
        file_path = source / filename
        if not file_path.exists():
            missing_files.append(filename)

    if missing_files:
        print(f"Missing files in {check_object} source path: {source_path}")
        for missing in missing_files:
            print(f"  - {missing}")
        return False

    print(f"{check_object} source path checked successfully.")
    return True


def check_custom_grpc_app(source_path: str):
    grpc_required_files = [
        "requirements.txt",
        "protos/ALL_IN_ONE.proto",
        "service.py"
    ]
    return check_required_files(source_path, grpc_required_files, "grpc_app")

def check_custom_sse_app(source_path: str):
    sse_required_files  = [
        "requirements.txt",
        "service.py"
    ]
    check_required_files(source_path, sse_required_files, "sse_app")
