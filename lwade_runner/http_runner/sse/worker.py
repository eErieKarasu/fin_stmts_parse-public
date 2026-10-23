# SSE Worker
import os

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import makefun

from lwade_config import config
from lwade_runner.http_runner.sse.middleware import ObservabilityMiddleware
from lwade_runner.http_runner.sse.utils import openai_streaming_wrapper
from lwade_utils.bootload import load_service_module
from lwade_utils.log_utils import get_custom_logger
from lwade_utils.path_utils import PROJECT_DIR

logger = get_custom_logger(__name__, "%(asctime)s - sse - worker - %(levelname)s - %(message)s")


class Worker:
    def __init__(self, workspace_dir: str):
        self.workspace_dir = workspace_dir
        self.app = None
        self._initialized = False

    def _setup_middleware(self):
        self.app.add_middleware(ObservabilityMiddleware)

    def _make_sse_endpoint(self, func):
        async def event(request: Request):
            async for item in func(request):
                yield item

        @makefun.wraps(func)
        async def sse_endpoint(request: Request):
            if config.ENABLE_OPENAI_SSE_RESPONSE:
                decorator = openai_streaming_wrapper(model=config.SSE_MODEL_NAME,
                                                     completion_id_prefix=config.SSE_COMPLETION_ID_PREFIX)
                decorated_func = decorator(func)
                response_stream = decorated_func(request)
            else:
                response_stream = event(request)

            return StreamingResponse(
                response_stream,
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                }
            )

        return sse_endpoint

    def _load_and_register_routes(self):
        service_module = load_service_module(self.workspace_dir, "sse")

        router = getattr(service_module, "__router__", None)
        if not router:
            raise ValueError("Service file has no __router__ defined.")

        if config.ENV == "local":
            root_path = f"/"
        else:
            root_path = f"/{config.APPID}/"
        for route in router.routes:
            modified_path = root_path + route.path.lstrip('/')
            wrapped_endpoint = self._make_sse_endpoint(route.endpoint)
            self.app.add_api_route(modified_path, wrapped_endpoint, methods=route.methods,
                              response_model=route.response_model)

    def create_app(self):
        """创建并配置 FastAPI 应用"""
        if self.app is not None:
            return self.app

        self.app = FastAPI()
        self._load_and_register_routes()
        self._setup_middleware()
        return self.app


if __name__ == '__main__':
    workspace_dir = os.getenv("WORKSPACE_DIR", os.path.join(PROJECT_DIR, "apps/mcp-app"))
    worker = Worker(workspace_dir)
    app = worker.create_app()

