# utils.py
import grpc
from google.rpc import status_pb2
from google.protobuf.any_pb2 import Any
from pathlib import Path
from typing import Union, Dict


def abort_with_error_detail(
    context: grpc.ServicerContext,
    grpc_code: grpc.StatusCode,
    error_detail  # 类型：common_protos.error_pb2.ErrorDetail
):
    # 1. 构造 google.rpc.Status
    status = status_pb2.Status()
    status.code = grpc_code.value[0]
    status.message = error_detail.message

    any_detail = Any()
    any_detail.Pack(error_detail)

    status.details.append(any_detail)

    # 2. 序列化并 base64 编码（用于 trailer）
    serialized = status.SerializeToString()

    # 3. 设置 trailer（APISIX 依赖这个！）
    context.set_trailing_metadata([
        ('grpc-status-details-bin', serialized),
    ])
    # 4. 使用普通 abort（兼容所有 gRPC 版本）
    context.abort(grpc_code, error_detail.message)


def read_proto_files(path: Union[str, Path]) -> Dict[str, str]:
    """
    读取指定路径下的所有 .proto 文件内容。

    Args:
        path: 可以是：
              - 一个 .proto 文件路径（str 或 Path）
              - 一个目录路径（会递归查找所有 .proto 文件）

    Returns:
        dict: {relative_path: file_content}
              relative_path 是相对于输入 path 的路径（若 path 是文件，则 key 为文件名）

    Raises:
        FileNotFoundError: 如果 path 不存在
        ValueError: 如果 path 不是 .proto 文件且不是目录
    """
    path = Path(path).resolve()

    if not path.exists():
        raise FileNotFoundError(f"Path not found: {path}")

    if path.is_file():
        if path.suffix == ".proto":
            proto_files = [path]
            base_dir = path.parent
        else:
            raise ValueError(f"File is not a .proto file: {path}")
    elif path.is_dir():
        proto_files = list(path.rglob("*.proto"))
        base_dir = path
    else:
        raise ValueError(f"Path is neither a file nor a directory: {path}")

    result = {}
    for fp in sorted(proto_files):
        try:
            content = fp.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            raise ValueError(f"Failed to read {fp} as UTF-8: {e}")
        # 计算相对于 base_dir 的路径
        rel_path = fp.relative_to(base_dir).as_posix()
        result[rel_path] = content

    return result
