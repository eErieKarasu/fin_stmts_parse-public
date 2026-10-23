import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlparse


REPO_ROOT = Path(__file__).resolve().parents[3]
MCP_PACKAGE_DIR = REPO_ROOT / "packages" / "mcp"

if str(MCP_PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_PACKAGE_DIR))

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


DEFAULT_FILE = REPO_ROOT / "files" / "2024财报.pdf"


def _dump_payload(label: str, payload: Any) -> None:
    print(f"\n=== {label} ===")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _extract_tool_payload(tool_name: str, result: Any) -> Any:
    if getattr(result, "isError", False):
        raise RuntimeError(f"{tool_name} 调用失败: {result}")

    payload = getattr(result, "structuredContent", None)
    if payload is None:
        raise RuntimeError(f"{tool_name} 未返回 structuredContent")
    if isinstance(payload, dict) and set(payload.keys()) == {"result"}:
        return payload["result"]
    return payload


async def run_live_chain(url: str, file_path: Path, session_id: str) -> None:
    async with streamable_http_client(url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            tools = await session.list_tools()
            tool_names = [tool.name for tool in tools.tools]
            print("TOOLS=", tool_names)

            required_tools = {
                "parse_fin_stmts_markdown",
                "fin_stmts_parse_map",
                "fin_stmts_parse_inspect",
                "fin_stmts_parse_audit_firm",
            }
            missing_tools = sorted(required_tools - set(tool_names))
            if missing_tools:
                raise RuntimeError(f"MCP server 缺少必须工具: {missing_tools}")

            parse_result = await session.call_tool(
                "parse_fin_stmts_markdown",
                {
                    "session_id": session_id,
                    "files": [{"path": str(file_path)}],
                },
            )
            parse_payload = _extract_tool_payload(
                "parse_fin_stmts_markdown",
                parse_result,
            )
            _dump_payload("parse_fin_stmts_markdown", parse_payload)

            if not isinstance(parse_payload, list):
                raise RuntimeError("parse_fin_stmts_markdown 返回值必须是数组")

            map_result = await session.call_tool(
                "fin_stmts_parse_map",
                {
                    "session_id": session_id,
                    "parse_results": parse_payload,
                },
            )
            map_payload = _extract_tool_payload(
                "fin_stmts_parse_map",
                map_result,
            )
            _dump_payload("fin_stmts_parse_map", map_payload)

            if not isinstance(map_payload, list):
                raise RuntimeError("fin_stmts_parse_map 返回值必须是数组")

            inspect_result = await session.call_tool(
                "fin_stmts_parse_inspect",
                {
                    "session_id": session_id,
                    "map_results": map_payload,
                },
            )
            inspect_payload = _extract_tool_payload(
                "fin_stmts_parse_inspect",
                inspect_result,
            )
            _dump_payload("fin_stmts_parse_inspect", inspect_payload)


async def run_live_chain_with_remote_file(
    url: str,
    file_url: str,
    file_name: str,
    session_id: str,
) -> None:
    async with streamable_http_client(url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            tools = await session.list_tools()
            tool_names = [tool.name for tool in tools.tools]
            print("TOOLS=", tool_names)

            required_tools = {
                "parse_fin_stmts_markdown",
                "fin_stmts_parse_map",
                "fin_stmts_parse_inspect",
                "fin_stmts_parse_audit_firm",
            }
            missing_tools = sorted(required_tools - set(tool_names))
            if missing_tools:
                raise RuntimeError(f"MCP server 缺少必须工具: {missing_tools}")

            parse_result = await session.call_tool(
                "parse_fin_stmts_markdown",
                {
                    "session_id": session_id,
                    "files": [
                        {
                            "file_url": file_url,
                            "file_name": file_name,
                        }
                    ],
                },
            )
            parse_payload = _extract_tool_payload(
                "parse_fin_stmts_markdown",
                parse_result,
            )
            _dump_payload("parse_fin_stmts_markdown", parse_payload)

            if not isinstance(parse_payload, list):
                raise RuntimeError("parse_fin_stmts_markdown 返回值必须是数组")

            map_result = await session.call_tool(
                "fin_stmts_parse_map",
                {
                    "session_id": session_id,
                    "parse_results": parse_payload,
                },
            )
            map_payload = _extract_tool_payload(
                "fin_stmts_parse_map",
                map_result,
            )
            _dump_payload("fin_stmts_parse_map", map_payload)

            if not isinstance(map_payload, list):
                raise RuntimeError("fin_stmts_parse_map 返回值必须是数组")

            inspect_result = await session.call_tool(
                "fin_stmts_parse_inspect",
                {
                    "session_id": session_id,
                    "map_results": map_payload,
                },
            )
            inspect_payload = _extract_tool_payload(
                "fin_stmts_parse_inspect",
                inspect_result,
            )
            _dump_payload("fin_stmts_parse_inspect", inspect_payload)


def _derive_file_name_from_url(file_url: str) -> str:
    parsed = urlparse(file_url)
    candidate = os.path.basename(unquote(parsed.path)).strip()
    if candidate:
        return candidate
    return "input.pdf"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the real MCP chain: parse_fin_stmts_markdown -> fin_stmts_parse_map -> fin_stmts_parse_inspect.",
    )
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8765/",
        help="MCP server URL. For RUNNING_ENV=local the default path is root '/'.",
    )
    parser.add_argument(
        "--file",
        default=str(DEFAULT_FILE),
        help="Absolute or repo-relative path to the PDF/image file to parse.",
    )
    parser.add_argument(
        "--file-url",
        default=None,
        help="HTTP/HTTPS file URL to parse. When provided, this takes precedence over --file.",
    )
    parser.add_argument(
        "--file-name",
        default=None,
        help="Optional filename to send along with --file-url. Defaults to the basename derived from the URL.",
    )
    parser.add_argument(
        "--session-id",
        default="live-session",
        help="Session id required by all MCP tools.",
    )
    args = parser.parse_args()

    if args.file_url:
        file_name = args.file_name or _derive_file_name_from_url(args.file_url)
        print(f"REMOTE_FILE_URL={args.file_url}")
        print(f"REMOTE_FILE_NAME={file_name}")
        asyncio.run(
            run_live_chain_with_remote_file(
                args.url,
                args.file_url,
                file_name,
                args.session_id,
            )
        )
        return

    file_path = Path(args.file).expanduser()
    if not file_path.is_absolute():
        file_path = (REPO_ROOT / file_path).resolve()

    if not file_path.exists():
        raise FileNotFoundError(f"测试文件不存在: {file_path}")

    asyncio.run(run_live_chain(args.url, file_path, args.session_id))


if __name__ == "__main__":
    main()
