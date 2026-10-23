import asyncio
from dataclasses import dataclass
import datetime
import json
import time

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from lwade_config import Config
from lwade_utils.log_utils import request_id_ctx
from lwade_utils.trace_utils import get_langfuse_client

import os
os.environ.setdefault("SW_AGENT_NAME", f"{Config.APPID}-sse")
os.environ.setdefault("SW_AGENT_COLLECTOR_BACKEND_SERVICES", Config.SW_OAP_ADDRESS)
os.environ.setdefault("SW_AGENT_PROTOCOL", "grpc")
os.environ.setdefault("SW_AGENT_LOGGING_LEVEL", "ERROR")
from skywalking import agent, Layer, Component
agent.start()

from skywalking.trace.context import get_context
from skywalking.trace.tags import TagHttpMethod, TagHttpURL, TagHttpStatusCode
from metrics_server import CONNECTIONS_TOTAL, CONNECTION_DURATION, ACTIVE_CONNECTIONS


@dataclass
class StreamChunk:
    """流式输出块数据结构"""
    content: str
    timestamp: str
    index: int


class ObservabilityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        # 跳过 /metrics 路由，避免 Prometheus 自身请求也被追踪/计数
        if request.url.path == "/metrics":
            return await call_next(request)

        req_id = request.headers.get("x-request-id") or request.headers.get("X-Request-Id", "N/A")
        request_id_ctx.set(req_id)

        response = await self.call_request(request, call_next)

        return response

    async def call_request(self, request, call_next):
        if Config.ENABLE_AUTO_TRACE_LANGFUSE:
            request_body = None
            if request.method == "POST":
                request_body = await request.body()

                async def new_receive():
                    yield {"type": "http.request", "body": request_body, "more_body": False}

                    while True:
                        yield {"type": "http.disconnect"}

                recv_gen = new_receive()

                request = Request(request.scope, receive=recv_gen.__anext__)
            else:
                request_body = None
            langfuse_client = get_langfuse_client()
            langfuse_observation = langfuse_client.start_observation(
                name=f"{request.method} {request.url.path}",
                input={
                    "body": json.loads(request_body) if request_body else None,
                    "query_params": dict(request.query_params),
                },
                metadata={
                    "headers": dict(request.headers),
                },
                as_type="generation")
        context = get_context()
        span = context.new_entry_span(op=request.url.path)
        span.start()
        span.layer = Layer.Http
        span.component = Component.FastAPI
        span.tag(TagHttpMethod(request.method))
        span.tag(TagHttpURL(str(request.url)))

        start_time = time.time()
        ACTIVE_CONNECTIONS.labels(operation=request.url.path, app=Config.APPID).inc()

        try:
            response = await call_next(request)
            captured = []
            original_body_iterator = response.body_iterator

            async def wrap_stream():
                chunk_index = 0
                try:
                    async for chunk in original_body_iterator:
                        if (Config.ENABLE_AUTO_TRACE_LANGFUSE and
                            (Config.LANGFUSE_SSE_TRACE_MAX_NUM == 0 or len(captured) < Config.LANGFUSE_SSE_TRACE_MAX_NUM)):
                            chunk_data = StreamChunk(
                                content=chunk.decode("utf-8", errors="ignore"),
                                timestamp=datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z",
                                index=chunk_index
                            )
                            captured.append(chunk_data)
                        chunk_index += 1
                        yield chunk
                finally:
                    if Config.ENABLE_AUTO_TRACE_LANGFUSE:
                        sse_report = {
                            "total_chunks": len(captured),
                            "chunks": captured
                        }
                        langfuse_observation.update(output=sse_report)
                        langfuse_observation.end()
                    self._finalize_observation(span, "success", request.url.path, start_time)

            response.body_iterator = wrap_stream()
        except asyncio.CancelledError as e:
            if span:
                span.tag(TagHttpStatusCode(200))
            self._finalize_observation(span, "cancelled", request.url.path, start_time)
            raise e
        except Exception as e:
            if span:
                span.raised()
                span.tag(TagHttpStatusCode(500))
            self._finalize_observation(span, "error", request.url.path, start_time)
            raise e

        return response

    def _finalize_observation(self, span, status, op, start_time):
        if span:
            if not span.end_time:  # 防止重复 stop
                span.stop()
        # === Prometheus: 更新指标 ===
        ACTIVE_CONNECTIONS.labels(operation=op, app=Config.APPID).dec()
        CONNECTIONS_TOTAL.labels(operation=op, status=status, app=Config.APPID).inc()
        CONNECTIONS_TOTAL.labels(operation=op, status="total", app=Config.APPID).inc()
        CONNECTION_DURATION.labels(operation=op, status=status, app=Config.APPID).observe(time.time() - start_time)

