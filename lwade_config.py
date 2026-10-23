import os


def get_env_int(key: str, default: int) -> int:
    val = os.getenv(key)
    return int(val) if val is not None else default

class Config:
    APPID = os.getenv("APPID", "demo-app")
    METRICS_PORT = 8002
    HEALTH_TCP_PORT = 9003
    HEALTH_HTTP_PORT = 9000

    GRPC_PORT = 50051
    GRPC_WORKERS = get_env_int("GRPC_WORKERS", 5)
    GRPC_WORKER_THREADS = get_env_int("GRPC_WORKER_THREADS", 50)
    GRPC_MASTER_WAIT_TIMEOUT = get_env_int("GRPC_MASTER_WAIT_TIMEOUT", 900)
    GRPC_MAX_REQUESTS = get_env_int("GRPC_MAX_REQUESTS", 1000)
    GRPC_MAX_REQUESTS_JITTER = get_env_int("GRPC_MAX_REQUESTS_JITTER", 100)
    GRPC_GRACEFUL_KILL_DELAY = get_env_int("GRPC_GRACEFUL_KILL_DELAY", 300)

    HTTP_PORT = 8001
    HTTP_WORKERS = get_env_int("HTTP_WORKERS", 1)
    HTTP_MAX_REQUESTS = get_env_int("HTTP_MAX_REQUESTS", 1000)
    HTTP_MAX_REQUESTS_JITTER = get_env_int("HTTP_MAX_REQUESTS_JITTER", 100)
    HTTP_GRACEFUL_KILL_DELAY = get_env_int("HTTP_GRACEFUL_KILL_DELAY", 300)

    SW_OAP_ADDRESS = os.getenv("SW_OAP_ADDRESS", "")
    APISIX_ADMIN_URL = os.getenv("APISIX_ADMIN_URL", "")
    APISIX_ADMIN_KEY = os.getenv("APISIX_ADMIN_KEY", "")
    APISIX_GATEWAY_URL = os.getenv("APISIX_GATEWAY_URL", "")
    ENV = os.getenv("RUNNING_ENV", "local") # choices ['local', 'sit', 'prod']
    PLUGIN_CONFIG = os.getenv("PLUGIN_CONFIG", "")

    ENABLE_AUTO_TRACE_LANGFUSE = os.getenv("ENABLE_AUTO_TRACE_LANGFUSE", "false").lower() in ("true", "1", "yes", "on")
    LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
    LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "")
    LANGFUSE_SSE_TRACE_MAX_NUM = get_env_int("LANGFUSE_SSE_TRACE_MAX_NUM", 0) # sse模式下上报langfuse的数量限制，0表示不限制

    PIP_MIRROR_URL = os.getenv("PIP_MIRROR_URL", "https://pypi.org/simple/")
    PIP_MIRROR_HOSTNAME = os.getenv("PIP_MIRROR_HOSTNAME", "pypi.org")

    ENABLE_OPENAI_SSE_RESPONSE = os.getenv("ENABLE_OPENAI_SSE_RESPONSE", "true").lower() in ("true", "1", "yes", "on")
    SSE_MODEL_NAME = os.getenv("SSE_MODEL_NAME", APPID)
    SSE_COMPLETION_ID_PREFIX = os.getenv("SSE_COMPLETION_ID_PREFIX", "chatcmpl")

config = Config()