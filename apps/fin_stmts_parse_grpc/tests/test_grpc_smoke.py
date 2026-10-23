#!/usr/bin/env python3

import argparse
import sys
from pathlib import Path

from google.protobuf.json_format import MessageToDict


TESTS_DIR = Path(__file__).resolve().parent
APP_DIR = TESTS_DIR.parent
APPS_DIR = APP_DIR.parent
PROJECT_DIR = APPS_DIR.parent

for path in (PROJECT_DIR, APP_DIR, APPS_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

import grpc

from lwade_config import config as lwade_config
from protos import fin_stmts_parse_pb2, fin_stmts_parse_pb2_grpc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test the migrated gRPC entrypoint.")
    parser.add_argument("--host", default="localhost", help="gRPC host")
    parser.add_argument("--port", type=int, default=lwade_config.GRPC_PORT, help="gRPC port")
    parser.add_argument("--file-name", required=True, help="Uploaded financial file name")
    parser.add_argument("--file-url", required=True, help="Resolvable file URL")
    parser.add_argument("--fns-no", default="FN191", help="Financial statement type")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    channel = grpc.insecure_channel(f"{args.host}:{args.port}")
    stub = fin_stmts_parse_pb2_grpc.FinStmtsParseStub(channel)

    request = fin_stmts_parse_pb2.ParseRequest(
        pubGloblJnno="smoke-test",
        seriNo="smoke-test",
        requestId="smoke-test",
        fnsId="smoke-test",
        fnsNo=args.fns_no,
        companyName="smoke-test",
        reportType="ANN",
        endDate="202612",
        finFiles=[
            {
                "fileName": args.file_name,
                "fileUrl": args.file_url,
            }
        ],
    )

    try:
        response = stub.parseFinStmts(request)
        print(MessageToDict(response, preserving_proto_field_name=True))
    finally:
        channel.close()


if __name__ == "__main__":
    main()
