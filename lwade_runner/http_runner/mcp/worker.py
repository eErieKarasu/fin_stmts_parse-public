# MCP Worker
import json
from json import JSONDecodeError
import os
import uvicorn

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from lwade_config import config
from lwade_utils.bootload import load_entry_module
from lwade_utils.path_utils import PROJECT_DIR


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 打印请求信息
        print(f"[MCP] Request: {request.method} {request.url.path}")
        print(f"[MCP] Query params: {dict(request.query_params)}")

        # 打印请求体
        if request.method == "POST":
            body = await request.body()
            if body:
                try:
                    print(f"[MCP] Request body: {json.loads(body)}")
                except:
                    print(f"[MCP] Request body: {body}")

        response = await call_next(request)

        # 打印响应体（流式响应需要特殊处理）
        if hasattr(response, 'body_iterator'):
            # 流式响应：包装 body_iterator 捕获数据
            captured = []
            original_iterator = response.body_iterator

            async def wrapped_iterator():
                try:
                    async for chunk in original_iterator:
                        captured.append(chunk)
                        yield chunk
                finally:
                    # 所有数据发送完后打印
                    if captured:
                        try:
                            full_body = b"".join(captured)
                            print(f"[MCP] Response body: {json.loads(full_body)}")
                        except:
                            print(f"[MCP] Response body: {full_body}")

            response.body_iterator = wrapped_iterator()
        elif hasattr(response, 'body') and response.body:
            try:
                print(f"[MCP] Response body: {json.loads(response.body)}")
            except:
                print(f"[MCP] Response body: {response.body}")

        return response


class Worker:
    def __init__(self, workspace_dir):
        self.workspace_dir = workspace_dir

    def read_manifest(self):
        try:
            manifest_path = os.path.join(self.workspace_dir, "manifest.json")
            if not os.path.exists(manifest_path):
                raise FileNotFoundError("manifest.json not found in workspace directory.")
            with open(manifest_path, "r") as file:
                data = json.load(file)
        except JSONDecodeError:
            raise ValueError("Invalid JSON format in manifest.json.")
        return data

    def create_app(self):

        manifest = self.read_manifest()
        mcp_entry = manifest.get("mcp_entry")
        if not mcp_entry:
            raise ValueError("Invalid manifest, 'mcp_entry' not found in manifest.json.")

        entry_file, entry_var = mcp_entry.split(":")
        mcp_entry_module = load_entry_module(self.workspace_dir, "mcp", entry_file)
        if not hasattr(mcp_entry_module, entry_var):
            raise ValueError(f"{entry_var} not found in service.py")

        mcp = getattr(mcp_entry_module, entry_var)
        if config.ENV == "local":
            path = f"/"
        else:
            path = f"/{config.APPID}/"
        mcp_app = mcp.http_app(path=path)
        # mcp_app.add_middleware(LoggingMiddleware)
        return mcp_app

if __name__ == '__main__':
    workspace_dir = os.getenv("WORKSPACE_DIR", os.path.join(PROJECT_DIR, "apps/mcp-app"))
    worker = Worker(workspace_dir)
    app = worker.create_app()
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8003,
        log_level="info",
    )