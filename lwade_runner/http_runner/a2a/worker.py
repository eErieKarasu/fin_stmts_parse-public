# A2A Worker
import asyncio
import json
import os
import uvicorn

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard

from lwade_config import config
from lwade_runner.http_runner.a2a.agent_executor import A2AAgentExecutor
from lwade_runner.http_runner.a2a.agent_runner.langgraph_runner import LangGraphRunner
from lwade_utils.bootload import load_entry_module
from lwade_utils.log_utils import get_custom_logger
from lwade_utils.path_utils import PROJECT_DIR

logger = get_custom_logger(__name__, "%(asctime)s - a2a - worker - %(levelname)s - %(message)s")

class Worker:
    def __init__(self, workspace_dir):
        self.workspace_dir = workspace_dir

    def get_agent_card(self):
        agent_card_path = os.path.join(self.workspace_dir, "agent_card.json")
        if os.path.exists(agent_card_path):
            with open(agent_card_path, "r", encoding="utf-8") as file:
                data = json.load(file)
            if config.ENV == "local":
                data['url'] = f"http://localhost:{config.HTTP_PORT}/a2a/"
            else:
                data['url'] = f"{config.APISIX_GATEWAY_URL.rstrip('/')}/a2a/{config.APPID}/"
            agent_card = AgentCard(**data)
            return agent_card
        else:
            raise FileNotFoundError(f"Agent card not found at {agent_card_path}")

    def read_manifest(self):
        manifest_path = os.path.join(self.workspace_dir, "manifest.json")
        if os.path.exists(manifest_path):
            with open(manifest_path, "r") as file:
                data = json.load(file)
                return data
        else:
            raise FileNotFoundError(f"Manifest not found at {manifest_path}")

    def create_app(self):
        agent_card = self.get_agent_card()
        manifest = self.read_manifest()

        runner_type = manifest["agent_runner"]
        if runner_type == "LangGraph":

            # 加载用户自定义的stream_wrapper（可选）
            stream_wrapper = None
            stream_wrapper_entry = manifest.get("langgraph_stream_wrapper")
            if stream_wrapper_entry:
                wrapper_file, wrapper_var = stream_wrapper_entry.split(":")
                wrapper_module = load_entry_module(self.workspace_dir, "a2a", wrapper_file)
                stream_wrapper = getattr(wrapper_module, wrapper_var)
                logger.info(f"Using custom stream_wrapper: {stream_wrapper_entry}")

            agent_runner = LangGraphRunner(stream_wrapper=stream_wrapper)
        else:
            raise ValueError(f"Unsupported agent runner type: {runner_type}")

        request_handler = DefaultRequestHandler(
            agent_executor=A2AAgentExecutor(agent_runner),
            task_store=InMemoryTaskStore(),
        )

        server = A2AStarletteApplication(
            agent_card=agent_card,
            http_handler=request_handler
        )
        agent_card_url = '/.well-known/agent-card.json'
        rpc_url = '/'
        if config.ENV != 'local':
            agent_card_url = f'/{config.APPID}{agent_card_url}'
            rpc_url = f'/{config.APPID}{rpc_url}'
        return server.build(agent_card_url=agent_card_url, rpc_url=rpc_url)


if __name__ == '__main__':
    workspace_dir = os.getenv("WORKSPACE_DIR", os.path.join(PROJECT_DIR, "apps/a2a-app"))
    worker = Worker(workspace_dir)
    app = worker.create_app()
    config = uvicorn.Config(app, host="0.0.0.0", port=10102)
    server = uvicorn.Server(config)
    asyncio.run(server.serve())
