import os
from lwade_config import config as cg # 避免与gunicorn内部的config变量冲突

os.environ['SERVER_TYPE'] = 'http'

bind = f"0.0.0.0:{cg.HTTP_PORT}"

workers = cg.HTTP_WORKERS

worker_class = "lwade_runner.http_runner.uvicorn_worker.CustomUvicornWorker"

max_requests = cg.HTTP_MAX_REQUESTS

max_requests_jitter = cg.HTTP_MAX_REQUESTS_JITTER

graceful_timeout = cg.HTTP_GRACEFUL_KILL_DELAY

accesslog = None

errorlog = "-"

loglevel = "info"