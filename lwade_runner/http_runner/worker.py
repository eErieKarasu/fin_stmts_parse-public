import os
from contextlib import asynccontextmanager
from contextlib import AsyncExitStack

import uvicorn
from fastapi import FastAPI

from lwade_config import config
from lwade_runner.http_runner.mcp.worker import Worker as MCPWorker
from lwade_runner.http_runner.a2a.worker import Worker as A2AWorker
from lwade_runner.http_runner.sse.worker import Worker as SSEWorker
from lwade_utils.path_utils import PROJECT_DIR
from lwade_utils.runner_utils import AppRunner, RunnerType

workers = os.getenv("INCLUDE_WORKERS", ", ".join(RunnerType.get_http_worker_values()))
mcp_workspace = os.getenv("MCP_WORKSPACE_DIR", os.path.join(PROJECT_DIR, "apps/mcp-app"))
a2a_workspace = os.getenv("A2A_WORKSPACE_DIR", os.path.join(PROJECT_DIR, "apps/a2a-app"))
sse_workspace = os.getenv("SSE_WORKSPACE_DIR", os.path.join(PROJECT_DIR, "apps/sse-app"))

http_workers = AppRunner.parse(workers)

# 先创建所有 worker 和 app，收集到字典
apps = {}

if RunnerType.SSE in http_workers:
    sse_worker = SSEWorker(sse_workspace)
    apps['sse'] = sse_worker.create_app()

if RunnerType.A2A in http_workers:
    a2a_worker = A2AWorker(a2a_workspace)
    apps['a2a'] = a2a_worker.create_app()

if RunnerType.MCP in http_workers:
    mcp_worker = MCPWorker(mcp_workspace)
    apps['mcp'] = mcp_worker.create_app()


# 创建合并的 lifespan，同时管理所有子 app 的生命周期
@asynccontextmanager
async def combined_lifespan(app: FastAPI):
    async with AsyncExitStack() as stack:
        for name, sub_app in apps.items():
            if hasattr(sub_app, 'lifespan'):
                await stack.enter_async_context(sub_app.lifespan(app))
        yield


# 使用合并的 lifespan 创建 FastAPI
app = FastAPI(lifespan=combined_lifespan)

# mount 所有 app
for path, sub_app in apps.items():
    app.mount(f"/{path}", sub_app)


if __name__ == '__main__':
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=config.HTTP_PORT,
        log_level="info",
    )