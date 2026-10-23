# metrics_server.py
import os

from lwade_config import config

from fastapi import FastAPI, Response

from lwade_utils.log_utils import get_uvicorn_log_config


current_dir = os.path.dirname(os.path.abspath(__file__))
shared_metrics_dir = os.path.join(current_dir, "metrics")
os.makedirs(shared_metrics_dir, exist_ok=True)

os.environ.setdefault("PROMETHEUS_MULTIPROC_DIR", shared_metrics_dir)
from prometheus_client import Counter, Histogram, Gauge, multiprocess, CollectorRegistry, generate_latest

# 创建自定义registry
registry = CollectorRegistry()
multiprocess.MultiProcessCollector(registry)

# 定义指标并注册到自定义registry
REQUEST_COUNT = Counter(
    "grpc_requests_total",
    "Total number of gRPC requests",
    labelnames=["method", "status", "app"],
    registry=registry
)

REQUEST_DURATION = Histogram(
    "grpc_request_duration_seconds",
    "Duration of gRPC requests in seconds",
    labelnames=["method", "app"],
    registry=registry
)

ACTIVE_CONNECTIONS = Gauge(
    "sse_active_connections",
    "Number of currently active long-lived connections",
    ["operation", "app"],
    registry=registry
)

CONNECTION_DURATION = Histogram(
    "sse_connection_duration_seconds",
    "Duration of long-lived connections in seconds",
    ["operation", "status", "app"],
    registry=registry
)

CONNECTIONS_TOTAL = Counter(
    "sse_connections_total",
    "Total number of long-lived connections",
    ["operation", "status", "app"],
    registry=registry
)

app = FastAPI()

@app.get("/metrics")
async def metrics():
    # 每次请求都新建 registry 来聚合所有进程的 .db 文件
    agg_registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(agg_registry)
    data = generate_latest(agg_registry)
    return Response(content=data)

if __name__ == "__main__":
    import uvicorn

    log_config = get_uvicorn_log_config("metrics")
    print(f"Starting FastAPI Prometheus metrics server on http://0.0.0.0:{config.METRICS_PORT}/metrics")
    uvicorn.run(app, host="0.0.0.0", port=config.METRICS_PORT, log_level="info", log_config=log_config)