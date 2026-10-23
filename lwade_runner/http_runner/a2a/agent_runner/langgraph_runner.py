# LangGraphRunner
from typing import Any, AsyncIterable, List

from a2a.types import (
    DataPart,
    FilePart,
    FileWithBytes,
    FileWithUri,
    Message,
    TextPart,
)
from langgraph.graph.state import CompiledStateGraph
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from lwade_runner.http_runner.a2a.agent_runner.base_runner import BaseRunner


class LangGraphRunner(BaseRunner):
    def __init__(self, graph: CompiledStateGraph = None, stream_mode: List[str] = None, use_subgraph: bool = None, stream_wrapper=None):
        self.graph = graph
        self.stream_mode = stream_mode
        self.use_subgraph = use_subgraph
        self.stream_wrapper = stream_wrapper

    def convert_a2a_message(self, message: Message):
        """Convert A2A message to LangGraph input"""
        message_content_blocks = []

        for part in message.parts:
            part = part.root
            if isinstance(part, TextPart):
                message_content_blocks.append({"type": "text", "text": part.text})
            elif isinstance(part, FilePart):
                if isinstance(part.file, FileWithBytes):
                    data_uri = f"data:{part.file.mime_type};base64,{part.file.bytes}"
                    message_content_blocks.append({"type": "image_url", "image_url": {"url": data_uri}})
                elif isinstance(part.file, FileWithUri):
                    message_content_blocks.append({"type": "image_url", "image_url": {"url": part.file.uri}})
        return HumanMessage(content=message_content_blocks)

    def convert_runner_message(self, event):
        """Convert LangGraph agent response to A2A"""
        def _process_message(message):
            if isinstance(message, AIMessage):
                if message.tool_calls:
                    tool_names = ','.join([tc['name'] for tc in message.tool_calls])
                    return {
                        'is_task_complete': False,
                        'require_user_input': False,
                        'content': f'调用工具 {tool_names} ...',
                    }
                else:
                    return {
                        'is_task_complete': False,
                        'require_user_input': False,
                        'content': message.content,
                    }
            elif isinstance(message, ToolMessage):
                return {
                    'is_task_complete': False,
                    'require_user_input': False,
                    'content': f'调用工具 {message.name} 完成',
                }
            return None

        if self.use_subgraph:
            _, mode, data = event
        else:
            mode, data = event

        if mode == 'values':
            messages = data['messages']
            last_message = messages[-1]
            return _process_message(last_message)
        elif mode == 'updates':
            for node, output in data.items():
                messages = output['messages']
                last_message = messages[-1]
                result = _process_message(last_message)
                if result:
                    return result
        elif mode == 'custom':
            return {
                'is_task_complete': False,
                'require_user_input': False,
                'content': data,
            }

        return {
            'is_task_complete': False,
            'require_user_input': False,
            'content': '处理中...',
        }

    async def stream(self, message: Message, context_id, task_id) -> AsyncIterable[dict[str, Any]]:
        # 使用用户提供的stream_wrapper，如果没提供则使用默认的astream调用
        # stream_wrapper可以接收额外参数: message, context_id，返回AsyncGenerator[str]
        if self.stream_wrapper:
            async for chunk in self.stream_wrapper(message, context_id, task_id):
                yield {
                    'is_task_complete': False,
                    'require_user_input': False,
                    'content': chunk
                }
        else:
            inputs = {'messages': self.convert_a2a_message(message)}
            config = {'configurable': {'thread_id': context_id}}
            async for event in self.graph.astream(inputs, config, stream_mode=self.stream_mode, subgraphs=self.use_subgraph):
                yield self.convert_runner_message(event)

        yield {
            'is_task_complete': True,
            'require_user_input': False,
        }
