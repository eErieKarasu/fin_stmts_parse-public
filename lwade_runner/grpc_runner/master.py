# GRPC Master
import argparse
import asyncio
from dataclasses import dataclass
import os
import psutil
import random
import signal
import subprocess
import sys
import threading
import types
from typing import Optional

import grpc

from lwade_config import config
from health_server import register_process
from lwade_utils.apisix_client import apisix_client
from lwade_utils.bootload import install_dependencies
from lwade_utils.log_utils import get_custom_logger
from lwade_utils.path_utils import GRPC_PACKAGE_INSTALL_PATH
from lwade_runner.grpc_runner.utils import read_proto_files

logger = get_custom_logger(__name__, '%(asctime)s - grpc - master - %(levelname)s - %(message)s')


@dataclass
class WorkerInfo:
    pid: int
    port: int
    channel: grpc.Channel


class WorkerRegistry:
    def __init__(self):
        self._lock = threading.RLock()
        self._workers: dict[int, WorkerInfo] = {}  # pid -> info

    def add_worker(self, pid: int, port: int):
        with self._lock:
            channel = grpc.insecure_channel(f"localhost:{port}")
            self._workers[pid] = WorkerInfo(pid, port, channel)

    def remove_worker(self, pid: int):
        with self._lock:
            if pid in self._workers:
                self._workers[pid].channel.close()
                del self._workers[pid]

    def get_active_channels(self):
        with self._lock:
            return [w.channel for w in self._workers.values() if w.channel]

    def get_workers(self):
        with self._lock:
            return [(w.pid, w.port) for w in self._workers.values()]

class GRPCProxy(grpc.GenericRpcHandler):
    def __init__(self, registry: WorkerRegistry):
        self._registry = registry
        self._index = 0
        self._lock = threading.Lock()

    def service(self, handler_call_details):
        method_name = handler_call_details.method

        def unary_unary_handler(request, context):
            return self._proxy_unary_unary(request, context, method_name)

        return types.SimpleNamespace(
            request_streaming=False,
            response_streaming=False,
            request_deserializer=lambda x: x,
            response_serializer=lambda x: x,
            unary_unary=unary_unary_handler,
        )

    def _proxy_unary_unary(self, request, context, method_name):
        channels = self._registry.get_active_channels()
        if not channels:
            context.abort(grpc.StatusCode.UNAVAILABLE, "No active workers")

        # round-robin
        with self._lock:
            channel = channels[self._index % len(channels)]
            self._index += 1

        try:
            worker_stub = channel.unary_unary(method_name)
            return worker_stub(
                request,
                metadata=context.invocation_metadata(),
                timeout=config.GRPC_MASTER_WAIT_TIMEOUT
            )
        except grpc.RpcError as e:
            context.abort(e.code(), e.details())

class Master:
    def __init__(
        self,
        workspace_dir: str,
        service_port: int = 50051,
        initial_workers: int = 3,
        base_worker_port: int = 51000,
        health_check_interval: float = 2.0,
    ):
        install_dependencies(workspace_dir, GRPC_PACKAGE_INSTALL_PATH)
        self.workspace_dir = workspace_dir
        self.service_port = service_port
        self.initial_workers = initial_workers
        self.base_worker_port = base_worker_port
        self.health_check_interval = health_check_interval

        # 动态分配管理端口
        self.mgmt_host = "127.0.0.1"
        self.mgmt_port = random.randint(59000, 65000)

        # 内部状态
        self.next_worker_id = 0
        self._shutdown = False
        self.registry = WorkerRegistry()
        self.grpc_proxy = GRPCProxy(self.registry)
        self.mgmt_server: Optional[asyncio.AbstractServer] = None

        if config.ENV != 'local':
            self._register_with_apisix()

    def _register_with_apisix(self):
        result = read_proto_files(os.path.join(self.workspace_dir, "protos/ALL_IN_ONE.proto"))
        apisix_client.upsert_proto(result['ALL_IN_ONE.proto'])

    async def _start_proxy(self):
        """启动 gRPC Server 并绑定 GRPCProxy"""
        server = grpc.aio.server()
        server.add_generic_rpc_handlers((self.grpc_proxy,))
        server.add_insecure_port(f"[::]:{self.service_port}")
        await server.start()
        logger.info(f"gRPC Proxy listening on :{self.service_port}")
        await server.wait_for_termination()

    # ================== Worker 管理 ==================
    def _start_worker(self) -> Optional[int]:
        port = self.base_worker_port + self.next_worker_id
        self.next_worker_id += 1

        env = os.environ.copy()
        env["GRPC_MASTER_MGMT_ADDR"] = f"{self.mgmt_host}:{self.mgmt_port}"
        env["WORKSPACE_DIR"] = self.workspace_dir
        cmd = [
            sys.executable, "-m", "lwade_runner.grpc_runner.worker",
            "--port", str(port)
        ]
        try:
            proc = subprocess.Popen(cmd, stdout=sys.stdout, stderr=subprocess.STDOUT, env=env)
            logger.info(f"Started worker PID={proc.pid} on port {port}")
            self.registry.add_worker(proc.pid, port)
            return port
        except Exception as e:
            logger.error(f"Failed to start worker on port {port}: {e}")
            return None

    # ================== 管理通道 ==================
    async def _handle_management(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            data = await reader.read(100)
            msg = data.decode().strip()
            if msg.startswith("DRAIN:"):
                msgs = msg.split(":")
                port = int(msgs[1])
                pid = int(msgs[2])

                if (pid, port) in self.registry.get_workers():
                    logger.info(f"Remove worker {pid} on localhost:{port}")
                    self.registry.remove_worker(pid)
                    # Spawn a new worker
                    self._start_worker()
                    # asyncio.create_task(self._kill_worker_after_delay(port))
            writer.write(b"OK\n")
            await writer.drain()
        except Exception as e:
            logger.error(f"Management error: {e}")
        finally:
            writer.close()

    async def _start_mgmt_server(self):
        self.mgmt_server = await asyncio.start_server(
            self._handle_management,
            self.mgmt_host, self.mgmt_port
        )
        logger.info(f"Management server ready at {self.mgmt_host}:{self.mgmt_port}")

    # ================== Worker健康监控 ==================
    async def _health_monitor(self):
        while not self._shutdown:
            dead_ports = []
            for pid, port in self.registry.get_workers():
                try:
                    proc = psutil.Process(pid)
                    status = proc.status()
                    if status == psutil.STATUS_ZOMBIE:
                        logger.error(f"Worker {port} (pid={pid}) is a zombie!")
                        dead_ports.append(port)
                        self.registry.remove_worker(pid)
                        continue
                except psutil.NoSuchProcess:
                    # 进程已经彻底消失
                    logger.warning(f"Worker {port} (pid={pid}) disappeared (no such process)")
                    dead_ports.append(port)
                    self.registry.remove_worker(pid)
                    continue
            for _ in dead_ports:
                self._start_worker()

            await asyncio.sleep(self.health_check_interval)

    # ================== 生命周期控制 ==================
    def _setup_signal_handlers(self):
        def cleanup_handler(signum, frame):
            logger.info("\nReceived signal. Shutting down...")
            self._shutdown = True
            asyncio.create_task(self._graceful_shutdown())

        signal.signal(signal.SIGINT, cleanup_handler)
        if hasattr(signal, 'SIGTERM'):
            signal.signal(signal.SIGTERM, cleanup_handler)

    async def _graceful_shutdown(self):
        if self.mgmt_server:
            self.mgmt_server.close()
            await self.mgmt_server.wait_closed()

        # 终止所有 worker
        for pid, port in self.registry.get_workers():
            try:
                proc = psutil.Process(pid)
                # 先尝试优雅终止
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except psutil.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            except psutil.NoSuchProcess:
                continue
        logger.warning("All workers stopped. Exiting.")

    # ================== 启动入口 ==================
    async def run(self):
        logger.info("Starting Master...")
        self._setup_signal_handlers()

        # 启动初始 workers
        for _ in range(self.initial_workers):
            self._start_worker()

        register_process(os.getpid(), "grpc-server-manager")

        # 启动服务
        await asyncio.gather(
            self._start_proxy(),
            self._start_mgmt_server(),
            self._health_monitor(),
        )


# ================== 主函数 ==================
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workspace-dir",
        help="Path to gRPC app directory"
    )
    args = parser.parse_args()

    master = Master(
        workspace_dir=args.workspace_dir,
        service_port=50051,
        initial_workers=config.GRPC_WORKERS,
        base_worker_port=51000,
        health_check_interval=2.0,
    )

    try:
        asyncio.run(master.run())
    except KeyboardInterrupt:
        pass