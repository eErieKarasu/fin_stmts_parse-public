# interceptors.py
import threading

from lwade_config import config as cg
import grpc
from google.protobuf.json_format import MessageToDict
import logging
import os
import time
from lwade_utils.log_utils import get_custom_logger
from lwade_utils.trace_utils import get_langfuse_client

from metrics_server import REQUEST_COUNT, REQUEST_DURATION
from lwade_runner.grpc_runner.common_protos.error_pb2 import ErrorDetail
from lwade_runner.grpc_runner.utils import abort_with_error_detail


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in ("true", "1", "yes", "on")


SKYWALKING_ENABLED = _env_flag("ENABLE_SKYWALKING", False)

if SKYWALKING_ENABLED:
    os.environ.setdefault("SW_AGENT_NAME", f"{cg.APPID}-grpc")
    os.environ.setdefault("SW_AGENT_COLLECTOR_BACKEND_SERVICES", cg.SW_OAP_ADDRESS)
    os.environ.setdefault("SW_AGENT_PROTOCOL", "grpc")
    os.environ.setdefault("SW_AGENT_LOGGING_LEVEL", "ERROR")

    from skywalking import agent, Component, Layer
    from skywalking.trace.context import get_context

    agent.start()
else:
    agent = None
    Component = None
    Layer = None
    get_context = None

logger = get_custom_logger(__name__, "%(asctime)s - grpc - master - %(levelname)s - %(message)s")


def _start_skywalking_span(method_name: str, logger_with_id):
    if not SKYWALKING_ENABLED:
        return None

    try:
        sw_ctx = get_context()
        span = sw_ctx.new_local_span(op=method_name)
        span.layer = Layer.RPCFramework
        span.component = Component.Grpc
        span.peer = 'client'
        span.start()
        return span
    except Exception as e:
        logger_with_id.warning(f"Failed to create span: {e}")
        return None


class ObservabilityInterceptor(grpc.ServerInterceptor):
    def __init__(self, worker_instance):
        self.worker = worker_instance
        self._lock = threading.Lock()

    def check_version(self, version):
        pass

    def get_metadata_by_key(self, metadata, key):
        for k, v in metadata:
            if k.lower() == key.lower():
                return v
        return None

    def intercept_service(self, continuation, handler_call_details):
        handler = continuation(handler_call_details)
        if not handler or not hasattr(handler, 'unary_unary'):
            return handler
        method_name = handler_call_details.method

        # 不对 gRPC 反射方法进行拦截
        if method_name.startswith('/grpc.reflection'):
            return handler

        def wrapper(request, context):
            start_time = time.time()
            status = "success"

            # 从请求头中获取 request_id
            metadata = context.invocation_metadata()
            request_id = self.get_metadata_by_key(metadata, 'X-Request-Id') or 'N/A'

            # 创建带 request_id 的 logger
            logger_with_id = logging.LoggerAdapter(logger, {'request_id': request_id})

            span = _start_skywalking_span(method_name, logger_with_id)

            try:
                if cg.ENABLE_AUTO_TRACE_LANGFUSE:
                    langfuse_client = get_langfuse_client()
                    with langfuse_client.start_as_current_observation(
                            name=method_name,
                            input=MessageToDict(request),
                            metadata=metadata) as trace:
                        result = handler.unary_unary(request, context)
                        trace.update(output=MessageToDict(result))
                    return result
                else:
                    result = handler.unary_unary(request, context)
                    return result
            except Exception as e:
                status = "error"
                if span:
                    span.log(e)
                    span.error_occurred = True
                error = ErrorDetail(
                    code=10001,
                    message=str(e),
                    type="APP_EXECUTE_ERROR"
                )
                abort_with_error_detail(context, grpc.StatusCode.INTERNAL, error)
            finally:
                duration = time.time() - start_time
                REQUEST_COUNT.labels(method=method_name, status=status, app=cg.APPID).inc()
                REQUEST_DURATION.labels(method=method_name, app=cg.APPID).observe(duration)

                if span:
                    span.stop()

                with self._lock:
                    self.worker.request_count += 1
                    current_count = self.worker.request_count

                logger_with_id.info(
                    f"[Worker PID={self.worker.pid} PORT={self.worker.port}] "
                    f"Handled request {handler_call_details.method} in {duration:.3f}s. Status: {status} (Request usages: {current_count}/{self.worker.max_requests})")
                if current_count >= self.worker.max_requests and not self.worker.draining:
                    with self._lock:
                        if not self.worker.draining:
                            if SKYWALKING_ENABLED and agent:
                                agent.agent.stop()
                            self.worker._start_graceful_shutdown()

        return grpc.unary_unary_rpc_method_handler(
            wrapper,
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
        )
