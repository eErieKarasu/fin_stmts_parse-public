#!/usr/bin/env python3
"""Tiny local frontend server and MCP proxy for fin_stmts_parse."""

from __future__ import annotations

import asyncio
import html
import json
import mimetypes
import os
import shutil
import sys
import tempfile
import traceback
import uuid
import warnings
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    import cgi


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
MCP_PACKAGE_DIR = REPO_ROOT / "packages" / "mcp"
APPS_DIR = REPO_ROOT / "apps"
DEFAULT_MCP_URL = os.environ.get("FIN_STMTS_MCP_URL", "http://127.0.0.1:8765/mcp")
DEFAULT_HOST = os.environ.get("FRONTEND_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("FRONTEND_PORT", "5173"))
MCP_URL_PLACEHOLDER = "__FIN_STMTS_MCP_URL__"

if str(MCP_PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_PACKAGE_DIR))

if str(APPS_DIR) not in sys.path:
    sys.path.insert(0, str(APPS_DIR))

from fin_stmts_parse.utils.s3_client import S3Client


ProgressSink = Callable[[dict[str, Any]], None]


def emit_progress(
    progress_callback: ProgressSink | None,
    message: str,
    *,
    tool: str = "frontend",
    progress: float | None = None,
    total: float | None = None,
) -> None:
    if progress_callback is None:
        return
    event: dict[str, Any] = {
        "type": "progress",
        "tool": tool,
        "message": message,
    }
    if progress is not None:
        event["progress"] = progress
    if total is not None:
        event["total"] = total
    progress_callback(event)


async def call_tool(
    mcp_url: str,
    name: str,
    arguments: dict[str, Any],
    *,
    progress_callback: ProgressSink | None = None,
) -> Any:
    from fastmcp import Client

    async def handle_progress(
        progress: float,
        total: float | None,
        message: str | None,
    ) -> None:
        emit_progress(
            progress_callback,
            message or "",
            tool=name,
            progress=float(progress),
            total=float(total) if total is not None else None,
        )

    async with Client(mcp_url) as client:
        result = await client.call_tool(
            name,
            arguments,
            progress_handler=handle_progress if progress_callback is not None else None,
        )
    return extract_tool_payload(result)


def extract_tool_payload(result: Any) -> Any:
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict) and "result" in structured:
        return structured["result"]
    if structured is not None:
        return structured

    data = getattr(result, "data", None)
    if is_json_like(data):
        return data

    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if not text:
            continue
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            continue

    return data


def is_json_like(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, dict):
        return True
    if isinstance(value, list):
        return all(is_json_like(item) for item in value)
    return False


async def run_pipeline(
    payload: dict[str, Any],
    progress_callback: ProgressSink | None = None,
) -> dict[str, Any]:
    mcp_url = str(payload.get("mcp_url") or DEFAULT_MCP_URL)
    session_id = str(payload.get("session_id") or "").strip()
    parse_results = payload.get("parse_results")

    if not session_id:
        raise ValueError("session_id 不能为空")
    if not isinstance(parse_results, list):
        raise ValueError("parse_results 必须是 parse_fin_stmts_markdown 的顶层返回数组")

    return await run_map_inspect_pipeline(
        mcp_url=mcp_url,
        session_id=session_id,
        parse_results=parse_results,
        report_status=str(payload.get("report_status") or "1"),
        progress_callback=progress_callback,
    )


async def run_inspect_pipeline(
    payload: dict[str, Any],
    progress_callback: ProgressSink | None = None,
) -> dict[str, Any]:
    mcp_url = str(payload.get("mcp_url") or DEFAULT_MCP_URL)
    session_id = str(payload.get("session_id") or "").strip()
    map_results = payload.get("map_results")

    if not session_id:
        raise ValueError("session_id 不能为空")
    if not is_complete_map_results(map_results):
        raise ValueError("map_results 必须是 fin_stmts_parse_map 的完整输出")

    inspect_result = await call_tool(
        mcp_url,
        "fin_stmts_parse_inspect",
        {
            "map_results": map_results,
            "session_id": session_id,
            "report_status": str(payload.get("report_status") or "1"),
        },
        progress_callback=progress_callback,
    )
    return {"inspect_result": inspect_result}


def _build_sdoss_object_key(file_name: str) -> str:
    date_prefix = datetime.now().strftime("%Y%m%d")
    return f"llm/fin_parse_input/{date_prefix}/{uuid.uuid4()}_{file_name}"


async def _upload_files_to_sdoss(
    files: list[dict[str, str]],
    progress_callback: ProgressSink | None = None,
) -> list[dict[str, str]]:
    """把本地文件上传到 sdoss，返回 [{fileUrl, fileName}]，失败时抛异常。"""
    url_files: list[dict[str, str]] = []
    total = len(files)
    for index, file_info in enumerate(files, start=1):
        local_path = file_info["path"]
        file_name = file_info["fileName"]
        object_key = _build_sdoss_object_key(file_name)
        emit_progress(
            progress_callback,
            f"正在上传文件至 sdoss（{index}/{total}）",
            progress=index,
            total=total,
        )

        file_url = await asyncio.to_thread(
            S3Client.upload_file,
            local_path,
            object_key,
            days=10,
            config_key="oss",
            expires=3600,
        )
        if not file_url:
            raise RuntimeError(f"上传 sdoss 失败: {file_name}")
        url_files.append({"fileUrl": file_url, "fileName": file_name})

    return url_files


async def run_upload_pipeline(
    payload: dict[str, Any],
    progress_callback: ProgressSink | None = None,
) -> dict[str, Any]:
    mcp_url = str(payload.get("mcp_url") or DEFAULT_MCP_URL)
    session_id = str(payload.get("session_id") or "").strip()
    files = payload.get("files")
    use_sdoss = str(payload.get("use_sdoss") or "").strip() == "1"

    if not session_id:
        raise ValueError("session_id 不能为空")
    if not isinstance(files, list) or not files:
        raise ValueError("请至少上传一个文件")

    if use_sdoss:
        mcp_files = await _upload_files_to_sdoss(files, progress_callback)
    else:
        mcp_files = files

    parse_results = await call_tool(
        mcp_url,
        "parse_fin_stmts_markdown",
        {"files": mcp_files, "session_id": session_id},
        progress_callback=progress_callback,
    )
    if not isinstance(parse_results, list):
        raise ValueError("parse_fin_stmts_markdown 返回结构异常：未取得顶层数组")

    return await run_map_inspect_pipeline(
        mcp_url=mcp_url,
        session_id=session_id,
        parse_results=parse_results,
        report_status=str(payload.get("report_status") or "0"),
        progress_callback=progress_callback,
    )


async def run_map_pipeline(
    *,
    mcp_url: str,
    session_id: str,
    parse_results: list[Any],
    progress_callback: ProgressSink | None = None,
) -> list[Any]:
    map_results = await call_tool(
        mcp_url,
        "fin_stmts_parse_map",
        {"parse_results": parse_results, "session_id": session_id},
        progress_callback=progress_callback,
    )
    if not is_complete_map_results(map_results):
        raise ValueError("fin_stmts_parse_map 返回结构异常：未取得完整 mapped_results")
    return map_results


async def run_map_inspect_pipeline(
    *,
    mcp_url: str,
    session_id: str,
    parse_results: list[Any],
    report_status: str,
    progress_callback: ProgressSink | None = None,
) -> dict[str, Any]:
    map_results = await run_map_pipeline(
        mcp_url=mcp_url,
        session_id=session_id,
        parse_results=parse_results,
        progress_callback=progress_callback,
    )

    inspect_result = await call_tool(
        mcp_url,
        "fin_stmts_parse_inspect",
        {
            "map_results": map_results,
            "session_id": session_id,
            "report_status": report_status,
        },
        progress_callback=progress_callback,
    )
    return {
        "parse_results": parse_results,
        "map_results": map_results,
        "inspect_result": inspect_result,
    }


def is_complete_map_results(value: Any) -> bool:
    return (
        isinstance(value, list)
        and all(
            isinstance(item, dict) and isinstance(item.get("mapped_results"), list)
            for item in value
        )
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "FinStmtsFrontend/1.0"

    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path)
        if path == "/":
            path = "/index.html"

        file_path = (ROOT / path.lstrip("/")).resolve()
        if not file_path.is_file() or ROOT not in file_path.parents:
            self.send_error(404)
            return

        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        data = read_frontend_asset(file_path)
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/upload-stream":
            self.handle_upload_stream()
            return
        if path in {"/api/pipeline-stream", "/api/inspect-stream"}:
            self.handle_json_stream(path)
            return
        if path == "/api/upload":
            self.handle_upload()
            return
        if path not in {"/api/pipeline", "/api/inspect"}:
            self.send_error(404)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            runner = run_inspect_pipeline if path == "/api/inspect" else run_pipeline
            response = asyncio.run(runner(payload))
            self.write_json(200, response)
        except Exception as exc:  # noqa: BLE001 - proxy should surface user-facing failures.
            self.log_exception(path, exc)
            self.write_json(500, {"error": str(exc)})

    def handle_json_stream(self, path: str) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception as exc:  # noqa: BLE001 - proxy should surface user-facing failures.
            self.log_exception(path, exc)
            self.write_json(500, {"error": str(exc)})
            return

        runner = run_inspect_pipeline if path == "/api/inspect-stream" else run_pipeline
        self.write_stream_headers()
        self.run_streamed(lambda progress: runner(payload, progress))

    def handle_upload(self) -> None:
        try:
            with tempfile.TemporaryDirectory(prefix="fin-stmts-upload-") as upload_dir:
                payload = self.read_upload_payload(upload_dir)
                response = asyncio.run(run_upload_pipeline(payload))
                self.write_json(200, response)
        except Exception as exc:  # noqa: BLE001 - proxy should surface user-facing failures.
            self.log_exception("/api/upload", exc)
            self.write_json(500, {"error": str(exc)})

    def handle_upload_stream(self) -> None:
        try:
            with tempfile.TemporaryDirectory(prefix="fin-stmts-upload-") as upload_dir:
                payload = self.read_upload_payload(upload_dir)
                self.write_stream_headers()
                self.run_streamed(lambda progress: run_upload_pipeline(payload, progress))
        except Exception as exc:  # noqa: BLE001 - proxy should surface user-facing failures.
            self.log_exception("/api/upload-stream", exc)
            if not getattr(self, "_stream_started", False):
                self.write_json(500, {"error": str(exc)})

    def read_upload_payload(self, upload_dir: str) -> dict[str, Any]:
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
            },
        )
        files = self.save_uploads(form, upload_dir)
        return {
            "mcp_url": self.get_form_value(form, "mcp_url", DEFAULT_MCP_URL),
            "session_id": self.get_form_value(form, "session_id", ""),
            "report_status": self.get_form_value(form, "report_status", "1"),
            "use_sdoss": self.get_form_value(form, "use_sdoss", "0"),
            "files": files,
        }

    @staticmethod
    def get_form_value(form: cgi.FieldStorage, key: str, default: str) -> str:
        value = form.getfirst(key, default)
        return str(value or default).strip()

    @staticmethod
    def save_uploads(form: cgi.FieldStorage, upload_dir: str) -> list[dict[str, str]]:
        fields: list[Any] = []
        for key in ("files", "file"):
            if key not in form:
                continue
            value = form[key]
            fields.extend(value if isinstance(value, list) else [value])

        saved_files: list[dict[str, str]] = []
        used_names: set[str] = set()
        for field in fields:
            filename = sanitize_filename(getattr(field, "filename", ""))
            if not filename:
                continue
            filename = make_unique_filename(filename, used_names)
            target = Path(upload_dir) / filename
            with target.open("wb") as output:
                shutil.copyfileobj(field.file, output)
            saved_files.append({"path": str(target), "fileName": filename})

        return saved_files

    def write_json(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def write_stream_headers(self) -> None:
        self._stream_started = True
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

    def write_stream_event(self, event: dict[str, Any]) -> None:
        data = json.dumps(event, ensure_ascii=False, default=str).encode("utf-8") + b"\n"
        self.wfile.write(data)
        self.wfile.flush()

    def run_streamed(
        self,
        runner_factory: Callable[[ProgressSink], Any],
    ) -> None:
        try:
            response = asyncio.run(runner_factory(self.write_stream_event))
            self.write_stream_event({"type": "result", "payload": response})
        except Exception as exc:  # noqa: BLE001 - stream should surface user-facing failures.
            self.log_exception(self.path, exc)
            self.write_stream_event({"type": "error", "error": str(exc)})

    def log_exception(self, path: str, exc: Exception) -> None:
        print(
            f"[frontend] {self.address_string()} - {path} failed: "
            f"{type(exc).__name__}: {exc}"
        )
        traceback.print_exc()

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[frontend] {self.address_string()} - {fmt % args}")


def sanitize_filename(filename: str) -> str:
    candidate = Path(str(filename or "").strip()).name
    return candidate or "upload"


def make_unique_filename(filename: str, used_names: set[str]) -> str:
    candidate = filename
    stem = Path(filename).stem or "upload"
    suffix = Path(filename).suffix
    counter = 1
    while candidate in used_names:
        candidate = f"{stem}_{counter}{suffix}"
        counter += 1
    used_names.add(candidate)
    return candidate


def read_frontend_asset(file_path: Path) -> bytes:
    data = file_path.read_bytes()
    if file_path.name != "index.html":
        return data

    safe_mcp_url = html.escape(DEFAULT_MCP_URL, quote=True).encode("utf-8")
    return data.replace(MCP_URL_PLACEHOLDER.encode("utf-8"), safe_mcp_url)


def main() -> None:
    server = ThreadingHTTPServer((DEFAULT_HOST, DEFAULT_PORT), Handler)
    print(f"Frontend: http://{DEFAULT_HOST}:{DEFAULT_PORT}")
    print(f"Default MCP URL: {DEFAULT_MCP_URL}")
    server.serve_forever()


if __name__ == "__main__":
    main()
