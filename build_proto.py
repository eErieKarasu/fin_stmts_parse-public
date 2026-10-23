import argparse
from pathlib import Path
import subprocess
import sys


def build_proto(proto_path):
    proto_file = Path(proto_path).resolve()

    if not proto_file.exists():
        print(f"Error: {proto_file} does not exist")
        sys.exit(1)

    proto_dir = proto_file.parent
    app_dir = proto_dir.parent
    str(proto_file.relative_to(app_dir).as_posix())
    cmd = [
        sys.executable, '-m', 'grpc_tools.protoc',
        f'--proto_path={app_dir}',
        f'--python_out={app_dir}',
        f'--grpc_python_out={app_dir}',
        str(proto_file.relative_to(app_dir).as_posix())
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=proto_dir,
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            pb2_file = proto_dir / f"{proto_file.stem}_pb2.py"
            pb2_grpc_file = proto_dir / f"{proto_file.stem}_pb2_grpc.py"

            print(f"成功生成:")
            print(f"   {pb2_file.name}")
            print(f"   {pb2_grpc_file.name}")
            return True
        else:
            print(f"失败: {result.stderr.strip()}")
            return False

    except Exception as e:
        print(str(e))
        return False

def main():
    parser = argparse.ArgumentParser(
        description="Build gRPC proto files"
    )
    parser.add_argument(
        "--proto-path",
        type=str,
        required=True,
        help="Path to the proto files"
    )
    args = parser.parse_args()
    build_proto(args.proto_path)

if __name__ == "__main__":
    main()

