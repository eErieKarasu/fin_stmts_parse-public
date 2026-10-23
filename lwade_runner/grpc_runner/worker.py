# GRPC Worker
import argparse
from concurrent.futures import ThreadPoolExecutor
import grpc
import importlib.util
import inspect
import os
import random
import socket
from typing import Optional

from grpc_reflection.v1alpha import reflection

from lwade_config import config
from lwade_utils.bootload import load_service_module
from lwade_utils.log_utils import get_custom_logger
from lwade_runner.grpc_runner.interceptors import ObservabilityInterceptor

logger = get_custom_logger(__name__, "%(asctime)s - grpc - worker - %(levelname)s - %(message)s")


class Worker:
    def __init__(self, port: int, max_requests: int, max_requests_jitter: int, graceful_kill_delay: int, worker_threads: int):
        self.port = port
        self.max_requests = max_requests + random.randint(0, max_requests_jitter)
        self.graceful_kill_delay = graceful_kill_delay
        self.worker_threads = worker_threads
        self.request_count = 0
        self.pid = os.getpid()
        self.draining = False
        self.server: Optional[grpc.Server] = None

        # 从环境变量获取 master 管理地址
        self.mgmt_addr = os.getenv("GRPC_MASTER_MGMT_ADDR")
        self.workspace_dir = os.getenv("WORKSPACE_DIR")
        if not self.mgmt_addr:
            logger.warning("GRPC_MASTER_MGMT_ADDR not set! Will not notify master on drain.")
        self.service_names = []

    def load_and_register_service(self, server):
        service_module = load_service_module(self.workspace_dir, "grpc")

        for name, cls in inspect.getmembers(service_module, inspect.isclass):
            for base in cls.__bases__:
                if 'pb2_grpc' in base.__module__:
                    generated_module = importlib.import_module(base.__module__)
                    add_func_name = f"add_{base.__name__}_to_server"
                    add_func = getattr(generated_module, add_func_name)

                    service_instance = cls()
                    add_func(service_instance, server)

                    pb2_module_name = base.__module__.replace("_grpc", "")

                    pb2_module = importlib.import_module(pb2_module_name)
                    for svc_name, svc_desc in pb2_module.DESCRIPTOR.services_by_name.items():
                        self.service_names.append(svc_desc.full_name)

    def _start_graceful_shutdown(self):
        if self.server and not self.draining:
            self.draining = True
            self._notify_master_drain()
            self.server.stop(grace=self.graceful_kill_delay)
            logger.info(f"[Worker {self.pid}] Graceful shutdown initiated.")

    def _notify_master_drain(self):
        """通知 master 自己要退出（跨平台 TCP）"""
        if not self.mgmt_addr:
            return

        try:
            host, port_str = self.mgmt_addr.split(":")
            with socket.create_connection((host, int(port_str)), timeout=2) as sock:
                sock.send(f"DRAIN:{self.port}:{self.pid}".encode())
                sock.recv(10)  # 等待 ACK
            logger.info(f"[Worker {os.getpid()}] Notified master to drain port {self.port}")
        except Exception as e:
            logger.error(f"[Worker {os.getpid()}] Failed to notify master: {e}")

    def serve(self):
        self.server = grpc.server(
            ThreadPoolExecutor(max_workers=self.worker_threads),
            interceptors=(ObservabilityInterceptor(self),),
            options=[
                ('grpc.max_receive_message_length', 100 * 1024 * 1024),  # 接收上限
                ('grpc.max_send_message_length', 100 * 1024 * 1024),  # 发送上限
            ]
        )

        self.load_and_register_service(self.server)

        reflection.enable_server_reflection(self.service_names, self.server)

        self.server.add_insecure_port(f'[::]:{self.port}')
        self.server.start()
        logger.info(f"[Worker PID={os.getpid()} Started gRPC server on 127.0.0.1:{self.port} with {self.max_requests} requests limit]")
        # 不阻塞，让服务器在后台运行
        try:
            # 保持服务器运行
            self.server.wait_for_termination()
            logger.info(f"[Worker {self.pid}] server terminated")
        except KeyboardInterrupt:
            logger.error("Shutting down grpc servers...")
            self.server.stop(0)


# ================== 启动入口 ==================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--port",
        type=int,
        help="Worker process server port"
    )
    args = parser.parse_args()

    worker = Worker(port=args.port,
                    max_requests=config.GRPC_MAX_REQUESTS,
                    max_requests_jitter=config.GRPC_MAX_REQUESTS_JITTER,
                    graceful_kill_delay=config.GRPC_GRACEFUL_KILL_DELAY,
                    worker_threads=config.GRPC_WORKER_THREADS)
    worker.serve()


if __name__ == '__main__':
    main()