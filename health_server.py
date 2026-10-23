# health_server.py
import json
import psutil
import threading
import time
import socket


from lwade_config import config
from lwade_utils.log_utils import get_custom_logger

logger = get_custom_logger(__name__, "%(asctime)s - health_server - %(levelname)s - %(message)s")


class ProcessManager:
    def __init__(self):
        self.processes = {}  # pid -> process_info
        self.lock = threading.Lock()

    def add_process(self, pid, process_type="unknown"):
        """添加进程到监控列表"""
        with self.lock:
            self.processes[pid] = {
                "pid": pid,
                "type": process_type,
                "added_at": time.time(),
                "status": "running"
            }
            logger.info(f"Added process {pid} ({process_type}) to monitoring list")

    def remove_process(self, pid):
        """从监控列表移除进程"""
        with self.lock:
            if pid in self.processes:
                del self.processes[pid]
                logger.info(f"Removed process {pid} from monitoring list")

    def get_process_list(self):
        """获取当前监控的进程列表"""
        with self.lock:
            return list(self.processes.values()).copy()

    def check_all_processes_healthy(self):
        """检查所有进程是否健康"""
        with self.lock:
            if not self.processes:
                return True

            healthy_count = 0
            for pid, proc_info in self.processes.items():
                try:
                    process = psutil.Process(pid)
                    if process.is_running() and process.status() != psutil.STATUS_ZOMBIE:
                        proc_info["status"] = "running"
                        healthy_count += 1
                    else:
                        proc_info["status"] = "stopped"
                except psutil.NoSuchProcess:
                    proc_info["status"] = "not_found"
                except Exception as e:
                    proc_info["status"] = f"error: {str(e)}"

            return healthy_count == len(self.processes)


class CommandHandler:
    def __init__(self, process_manager):
        self.process_manager = process_manager

    def handle_command(self, command_str):
        """处理来自socket的命令"""
        try:
            command = json.loads(command_str)
            cmd = command.get("command")

            if cmd == "register":
                pid = command.get("pid")
                process_type = command.get("type", "unknown")
                if pid:
                    self.process_manager.add_process(pid, process_type)
                    return {"status": "success", "message": "Process registered"}
                else:
                    return {"status": "error", "message": "Missing pid"}

            elif cmd == "unregister":
                pid = command.get("pid")
                if pid:
                    self.process_manager.remove_process(pid)
                    return {"status": "success", "message": "Process unregistered"}
                else:
                    return {"status": "error", "message": "Missing pid"}

            elif cmd == "list":
                processes = self.process_manager.get_process_list()
                return {"status": "success", "processes": processes}

            elif cmd == "health":
                all_healthy = self.process_manager.check_all_processes_healthy()
                processes = self.process_manager.get_process_list()
                return {
                    "status": "success",
                    "all_healthy": all_healthy,
                    "processes": processes
                }

            else:
                return {"status": "error", "message": "Unknown command"}

        except json.JSONDecodeError:
            return {"status": "error", "message": "Invalid JSON"}
        except Exception as e:
            return {"status": "error", "message": str(e)}


class HealthServer:
    def __init__(self, tcp_port=9003, http_port=9000):
        self.tcp_port = tcp_port
        self.http_port = http_port
        self.process_manager = ProcessManager()
        self.command_handler = CommandHandler(self.process_manager)
        self.tcp_server = None
        self.http_server = None
        self.running = False

    def start_tcp_server(self):
        """启动TCP Socket服务器"""
        self.tcp_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp_server.bind(("127.0.0.1", self.tcp_port))
        self.tcp_server.listen(5)
        self.running = True
        logger.info(f"TCP server listening on 127.0.0.1:{self.tcp_port}")

        def handle_connections():
            while self.running:
                try:
                    client_socket, addr = self.tcp_server.accept()
                    threading.Thread(
                        target=self.handle_client,
                        args=(client_socket,),
                        daemon=True
                    ).start()
                except Exception as e:
                    if self.running:
                        logger.error(f"TCP accept error: {e}")
                    break

        threading.Thread(target=handle_connections, daemon=True).start()

    def handle_client(self, client_socket):
        """处理客户端连接"""
        try:
            data = client_socket.recv(1024).decode()
            response = self.command_handler.handle_command(data)
            client_socket.send(json.dumps(response).encode())
        except Exception as e:
            error_response = {"status": "error", "message": str(e)}
            try:
                client_socket.send(json.dumps(error_response).encode())
            except:
                pass
        finally:
            client_socket.close()

    def start_http_server(self):
        """启动HTTP服务器（用于外部健康检查）"""
        from http.server import HTTPServer, BaseHTTPRequestHandler

        class HealthHandler(BaseHTTPRequestHandler):
            def __init__(_, process_manager, *args, **kwargs):
                _.process_manager = process_manager
                super().__init__(*args, **kwargs)

            def do_GET(_):
                if _.path == '/health':
                    all_healthy = _.process_manager.check_all_processes_healthy()
                    processes = _.process_manager.get_process_list()
                    code = 200 if all_healthy else 503

                    _.send_response(code)
                    _.send_header("Content-type", "application/json")
                    _.end_headers()
                    response = {
                        "status": "healthy" if all_healthy else "unhealthy",
                        "all_healthy": all_healthy,
                        "processes": processes,
                        "timestamp": time.time()
                    }
                    _.wfile.write(json.dumps(response, indent=2).encode())
                else:
                    _.send_response(404)
                    _.end_headers()

        def handler_factory(*args, **kwargs):
            return HealthHandler(self.process_manager, *args, **kwargs)

        self.http_server = HTTPServer(("0.0.0.0", self.http_port), handler_factory)
        threading.Thread(target=self.http_server.serve_forever, daemon=True).start()
        logger.info(f"HTTP server listening on 0.0.0.0:{self.http_port}")

    def start(self):
        """启动健康服务器"""
        self.start_tcp_server()
        self.start_http_server()
        logger.info("Health server started")

    def stop(self):
        """停止健康服务器"""
        self.running = False
        if self.tcp_server:
            self.tcp_server.close()
        if self.http_server:
            self.http_server.shutdown()


# 客户端工具函数
def register_process(pid, process_type="unknown", host="127.0.0.1", port=config.HEALTH_TCP_PORT):
    """向健康服务器注册进程"""
    try:
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect((host, port))

        command = {
            "command": "register",
            "pid": pid,
            "type": process_type
        }

        client.send(json.dumps(command).encode())
        response = client.recv(1024).decode()
        result = json.loads(response)

        client.close()
        logger.info(f"Registered process {pid}-{process_type} successfully.")
        return result
    except Exception as e:
        logger.error(f"Failed to register process: {e}")
        return {"status": "error", "message": str(e)}


def unregister_process(pid, host="127.0.0.1", port=config.HEALTH_TCP_PORT):
    """从健康服务器注销进程"""
    try:
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect((host, port))

        command = {
            "command": "unregister",
            "pid": pid
        }

        client.send(json.dumps(command).encode())
        response = client.recv(1024).decode()
        result = json.loads(response)

        client.close()
        return result
    except Exception as e:
        logger.error(f"Failed to unregister process: {e}")
        return {"status": "error", "message": str(e)}


# 测试和启动代码
if __name__ == "__main__":
    import signal
    import sys

    server = HealthServer(tcp_port=config.HEALTH_TCP_PORT, http_port=config.HEALTH_HTTP_PORT)
    server.start()

    def signal_handler(signum, frame):
        logger.info("Shutting down health server...")
        server.stop()
        sys.exit(0)


    signal.signal(signal.SIGINT, signal_handler)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, signal_handler)

    logger.info("Health server running. Press Ctrl+C to stop.")

    # 保持服务运行
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        signal_handler(signal.SIGINT, None)
