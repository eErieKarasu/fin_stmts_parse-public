# build_image.py
import os
import sys
import shutil
import subprocess
from pathlib import Path

from lwade_utils.argparse_utils import BaseArgumentParser
from lwade_utils.runner_utils import AppRunner, RunnerType


MARKER = "# >>> INSERT_SUB_DOCKERFILE_HERE <<<"

APP_CONFIG = {
    RunnerType.GRPC: {
        "arg_name": "grpc_app_path",
        "flag": "--grpc-app-path",
        "required_files": ["requirements.txt", "protos/ALL_IN_ONE.proto", "service.py"],
        "target_dir": Path("apps/grpc-app"),
    },
    RunnerType.SSE: {
        "arg_name": "sse_app_path",
        "flag": "--sse-app-path",
        "required_files": ["requirements.txt", "service.py"],
        "target_dir": Path("apps/sse-app"),
    },
    RunnerType.A2A: {
        "arg_name": "a2a_app_path",
        "flag": "--a2a-app-path",
        "required_files": ["requirements.txt", "service.py"],
        "target_dir": Path("apps/a2a-app"),
    },
    RunnerType.MCP: {
        "arg_name": "mcp_app_path",
        "flag": "--mcp-app-path",
        "required_files": ["requirements.txt", "service.py"],
        "target_dir": Path("apps/mcp-app"),
    },
}


def read_file_content(filepath):
    path = Path(filepath).expanduser()
    if not path.exists():
        print(f"Error: The file '{filepath}' does not exist.")
        sys.exit(1)

    with path.open("r", encoding="utf-8") as file:
        content = file.read()

    return content.replace("\r\n", "\n").replace("\r", "\n")


def copy_source_to_target(source_path: str, target_dir: Path):
    """
    将 source_path (文件或目录) 复制到 target_dir 并覆盖已有内容。
    """
    source = Path(source_path).resolve()
    if not source.exists():
        raise FileNotFoundError(f"Source path '{source}' does not exist.")

    if target_dir.exists():
        shutil.rmtree(target_dir)

    target_dir.parent.mkdir(parents=True, exist_ok=True)

    if source.is_file():
        shutil.copy2(source, target_dir)
    elif source.is_dir():
        shutil.copytree(source, target_dir)


def resolve_app_source_path(source_path: str) -> Path:
    source = Path(source_path).expanduser().resolve()
    if not source.exists():
        print(f"Error: App path does not exist: {source_path}")
        sys.exit(1)
    if not source.is_dir():
        print(f"Error: App path must be a directory: {source_path}")
        sys.exit(1)
    return source


def ensure_required_files(source: Path, runner: RunnerType):
    required_files = APP_CONFIG[runner]["required_files"]
    missing_files = [filename for filename in required_files if not (source / filename).exists()]
    if missing_files:
        print(f"Error: Invalid {runner.value} app directory: {source}")
        for filename in missing_files:
            print(f"  - missing: {filename}")
        sys.exit(1)


def resolve_image_app_path(source: Path, runner: RunnerType, repo_root: Path) -> tuple[str, bool]:
    try:
        return source.relative_to(repo_root).as_posix(), True
    except ValueError:
        return APP_CONFIG[runner]["target_dir"].as_posix(), False


def discover_sub_dockerfiles(runners, source_paths):
    discovered = []
    seen = set()

    for runner in runners:
        candidate = source_paths[runner] / "my.dockerfile"
        if not candidate.is_file():
            continue

        resolved = candidate.resolve()
        if resolved in seen:
            continue

        seen.add(resolved)
        discovered.append(resolved)

    return discovered


def render_dockerfile(main_content: str, sub_dockerfiles):
    if sub_dockerfiles:
        sub_sections = [read_file_content(path) for path in sub_dockerfiles]
        sub_content = "\n".join(section for section in sub_sections if section.strip())
        injected = f"\n{sub_content}\n" if sub_content else ""

        if MARKER in main_content:
            return main_content.replace(MARKER, injected)

        print("[!] Warning: MARKER not found in Dockerfile. Appending sub-dockerfile content to the end.")
        return main_content + injected

    return main_content.replace(MARKER, "")


def build_with_custom_apps(
        name: str,
        tag: str,
        runners,
        grpc_app_path: str = None,
        sse_app_path: str = None,
        a2a_app_path: str = None,
        mcp_app_path: str = None,
        sub_dockerfile: str = None,
    ):
    """
    使用用户提供的 app 目录覆盖默认目录，构建包含 lwade 框架和业务代码的镜像。
    """
    original_cwd = os.getcwd()
    script_dir = Path(__file__).resolve().parent
    temp_context = script_dir / ".temp_build_context"
    source_paths = {}
    app_paths = {
        RunnerType.GRPC: grpc_app_path,
        RunnerType.SSE: sse_app_path,
        RunnerType.A2A: a2a_app_path,
        RunnerType.MCP: mcp_app_path,
    }

    if temp_context.exists():
        shutil.rmtree(temp_context)
    temp_context.mkdir()

    try:
        for item in script_dir.iterdir():
            if item.name == ".temp_build_context":
                continue

            dest = temp_context / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)

        print("[*] App workspace mapping:")
        for runner in runners:
            source = resolve_app_source_path(app_paths[runner])
            ensure_required_files(source, runner)
            source_paths[runner] = source

            image_app_path, is_internal = resolve_image_app_path(source, runner, script_dir)
            if is_internal:
                print(f"    - {runner.value}: {image_app_path} (in-repo path)")
                continue

            target_dir = temp_context / APP_CONFIG[runner]["target_dir"]
            copy_source_to_target(str(source), target_dir)
            print(f"    - {runner.value}: {image_app_path} (bundled from external path)")

        main_content = read_file_content(script_dir / "Dockerfile")

        if sub_dockerfile:
            sub_dockerfiles = [Path(sub_dockerfile).expanduser()]
            print(f"[*] Using explicit sub-dockerfile: {sub_dockerfiles[0]}")
        else:
            sub_dockerfiles = discover_sub_dockerfiles(runners, source_paths)
            if sub_dockerfiles:
                print("[*] Auto-discovered sub-dockerfile(s):")
                for path in sub_dockerfiles:
                    print(f"    - {path}")
            else:
                print("[*] No sub-dockerfile provided. Building base image.")

        final_dockerfile = render_dockerfile(main_content, sub_dockerfiles)

        os.chdir(temp_context)
        cmd = [
            "docker", "build",
            "-f", "-",
            "-t", f"{os.getenv('IMAGE_REPOSITORY', name)}:{tag}",
            "--network", "host",
        ]
        print("Building image with command:")
        for runner in runners:
            image_app_path, _ = resolve_image_app_path(source_paths[runner], runner, script_dir)
            build_arg_name = f"{runner.value.upper()}_APP_IMAGE_PATH"
            cmd.extend(["--build-arg", f"{build_arg_name}={image_app_path}"])

        cmd.append(".")

        print(" ".join(cmd))

        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True
        )
        process.stdin.write(final_dockerfile)
        process.stdin.close()

        for line in process.stdout:
            print(line, end="")

        process.wait()

        if process.returncode != 0:
            print(f"\n[!] Docker build failed with exit code {process.returncode}")
            sys.exit(1)

        print(f"\n[+] Successfully built image: example.invalid/llm/lwade-app/{name}:{tag}")

    finally:
        if temp_context.exists():
            shutil.rmtree(temp_context)

        os.chdir(original_cwd)


def validate_args(args):
    try:
        runners = AppRunner.parse(args.runner)
    except (TypeError, ValueError) as exc:
        print(f"Error: {exc}")
        sys.exit(1)

    missing = []
    for runner in runners:
        config = APP_CONFIG[runner]
        if not getattr(args, config["arg_name"]):
            missing.append(config["flag"])

    if missing:
        print(f"Error: Missing required arguments for runner '{args.runner}': {', '.join(missing)}")
        sys.exit(1)

    return runners


def main():
    parser = BaseArgumentParser(
        description="Build Docker image with custom gRPC/SSE apps."
    )
    parser.add_argument(
        "--name",
        required=True,
        help="Docker image name (e.g., example.invalid/llm/lwade-app/{name}:{tag})"
    )
    parser.add_argument(
        "--tag",
        required=True,
        help="Docker image tag (e.g., example.invalid/llm/lwade-app/{name}:{tag})"
    )
    parser.add_argument(
        "--sub-dockerfile",
        default=None,
        help="Path to the sub-dockerfile to inject"
    )
    args = parser.parse_args()

    runners = validate_args(args)

    build_with_custom_apps(
        args.name,
        args.tag,
        runners=runners,
        grpc_app_path=args.grpc_app_path if RunnerType.GRPC in runners else None,
        sse_app_path=args.sse_app_path if RunnerType.SSE in runners else None,
        a2a_app_path=args.a2a_app_path if RunnerType.A2A in runners else None,
        mcp_app_path=args.mcp_app_path if RunnerType.MCP in runners else None,
        sub_dockerfile=args.sub_dockerfile,
    )


if __name__ == "__main__":
    main()
