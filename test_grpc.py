#!/usr/bin/env python3

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List

import grpc
from google.protobuf.json_format import MessageToDict


REPO_ROOT = Path(__file__).resolve().parent
GRPC_APP_DIR = REPO_ROOT / "apps" / "fin_stmts_parse_grpc"
APPS_DIR = REPO_ROOT / "apps"
FIN_PARSE_APP_DIR = REPO_ROOT / "apps" / "fin_stmts_parse"

for path in (REPO_ROOT, GRPC_APP_DIR, APPS_DIR, FIN_PARSE_APP_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from lwade_config import config as lwade_config
from protos import fin_stmts_parse_pb2, fin_stmts_parse_pb2_grpc
from fin_stmts_parse.utils.s3_client import S3Client


# 直接修改这里的值即可，无需命令行传参。
CONFIG: Dict[str, Any] = {
    "env": "dev",
    "host": "127.0.0.1",
    "port": lwade_config.GRPC_PORT,
    "file": str(REPO_ROOT / "files" / "example-report.pdf"),
    "input_mode": "local",  # local | sdoss | both
    "s3_prefix": "llm/report_gen/manual_tests/grpc",
    "s3_config_key": "oss",
    "cleanup_uploaded": False,
    "fns_no": "FN191",
    "report_type": "ANN",
    "end_date": "202612",
    "company_name": "smoke-test",
}


def _resolve_local_file(config: Dict[str, Any]) -> Path:
    file_path = Path(str(config.get("file", "") or "")).expanduser()
    if not file_path.is_absolute():
        file_path = (REPO_ROOT / file_path).resolve()

    if not file_path.exists():
        raise FileNotFoundError(f"测试文件不存在: {file_path}")

    return file_path


def _normalize_input_modes(config: Dict[str, Any]) -> List[str]:
    raw_mode = str(config.get("input_mode", "both")).strip().lower() or "both"
    if raw_mode == "both":
        return ["local", "sdoss"]
    if raw_mode in {"local", "sdoss"}:
        return [raw_mode]
    raise ValueError(f"不支持的 input_mode: {raw_mode}")


def _upload_file_to_s3(local_file: Path, config: Dict[str, Any]) -> tuple[str, str, str]:
    env = str(config.get("env", "dev")).strip() or "dev"
    os.environ["RUNNING_ENV"] = env

    s3_prefix = str(config.get("s3_prefix", "llm/report_gen/manual_tests/grpc")).strip().rstrip("/")
    s3_config_key = str(config.get("s3_config_key", "oss")).strip() or "oss"
    file_name = local_file.name
    object_key = f"{s3_prefix}/{uuid.uuid4()}_{file_name}"

    file_url = S3Client.upload_file(str(local_file), object_key, config_key=s3_config_key)
    if not file_url:
        raise RuntimeError(f"S3 上传失败: {local_file}")

    return object_key, file_url, file_name


def _build_file_input(
    mode: str,
    local_file: Path,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    file_name = local_file.name
    if mode == "local":
        return {
            "mode": mode,
            "file_name": file_name,
            "file_url": str(local_file),
            "object_key": None,
        }

    object_key, file_url, uploaded_file_name = _upload_file_to_s3(local_file, config)
    return {
        "mode": mode,
        "file_name": uploaded_file_name,
        "file_url": file_url,
        "object_key": object_key,
    }


def _print_request(
    *,
    mode: str,
    host: str,
    port: int,
    local_file: Path,
    file_input: Dict[str, Any],
    fns_no: str,
    report_type: str,
    end_date: str,
) -> None:
    print(f"\n=== REQUEST ({mode}) ===")
    print(
        json.dumps(
            {
                "env": os.getenv("RUNNING_ENV"),
                "host": host,
                "port": port,
                "localFile": str(local_file),
                "inputMode": mode,
                "s3ObjectKey": file_input.get("object_key"),
                "fileName": file_input["file_name"],
                "fileUrl": file_input["file_url"],
                "fnsNo": fns_no,
                "reportType": report_type,
                "endDate": end_date,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _call_grpc(
    *,
    host: str,
    port: int,
    company_name: str,
    fns_no: str,
    report_type: str,
    end_date: str,
    file_input: Dict[str, Any],
) -> Dict[str, Any]:
    channel = grpc.insecure_channel(f"{host}:{port}")
    stub = fin_stmts_parse_pb2_grpc.FinStmtsParseStub(channel)

    request = fin_stmts_parse_pb2.ParseRequest(
        pubGloblJnno="local-call",
        seriNo="local-call",
        requestId=f"local-call-{uuid.uuid4()}",
        fnsId="local-call",
        fnsNo=fns_no,
        companyName=company_name,
        reportType=report_type,
        endDate=end_date,
        finFiles=[
            {
                "fileName": file_input["file_name"],
                "fileUrl": file_input["file_url"],
            }
        ],
    )

    try:
        response = stub.parseFinStmts(request)
        return MessageToDict(response, preserving_proto_field_name=True)
    finally:
        channel.close()


def _cleanup_uploaded_file(file_input: Dict[str, Any], config: Dict[str, Any]) -> None:
    object_key = file_input.get("object_key")
    if not object_key:
        return
    S3Client.delete_file(object_key, config_key=str(config.get("s3_config_key", "oss")))


def main() -> None:
    env = str(CONFIG.get("env", "dev")).strip() or "dev"
    os.environ["RUNNING_ENV"] = env

    local_file = _resolve_local_file(CONFIG)
    input_modes = _normalize_input_modes(CONFIG)
    host = str(CONFIG.get("host", "127.0.0.1"))
    port = int(CONFIG.get("port", lwade_config.GRPC_PORT))
    fns_no = str(CONFIG.get("fns_no", "FN191"))
    report_type = str(CONFIG.get("report_type", "ANN"))
    end_date = str(CONFIG.get("end_date", "202612"))
    company_name = str(CONFIG.get("company_name", "smoke-test"))

    uploaded_inputs: List[Dict[str, Any]] = []

    try:
        for mode in input_modes:
            file_input = _build_file_input(mode, local_file, CONFIG)
            if file_input.get("object_key"):
                uploaded_inputs.append(file_input)

            _print_request(
                mode=mode,
                host=host,
                port=port,
                local_file=local_file,
                file_input=file_input,
                fns_no=fns_no,
                report_type=report_type,
                end_date=end_date,
            )

            response_payload = _call_grpc(
                host=host,
                port=port,
                company_name=company_name,
                fns_no=fns_no,
                report_type=report_type,
                end_date=end_date,
                file_input=file_input,
            )

            print(f"\n=== RESPONSE ({mode}) ===")
            print(json.dumps(response_payload, ensure_ascii=False, indent=2))
    finally:
        if bool(CONFIG.get("cleanup_uploaded", False)):
            for file_input in uploaded_inputs:
                _cleanup_uploaded_file(file_input, CONFIG)


if __name__ == "__main__":
    main()
