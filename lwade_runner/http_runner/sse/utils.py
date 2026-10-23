from datetime import datetime
from functools import wraps
import secrets
from typing import (
    AsyncGenerator,
    Callable,
)

from openai.types.chat.chat_completion_chunk import ChatCompletionChunk, Choice, ChoiceDelta


def openai_streaming_wrapper(model: str, completion_id_prefix: str = "chatcmpl"):
    def decorator(func: Callable[..., AsyncGenerator[str, None]]):
        @wraps(func)
        async def wrapper(*args, **kwargs) -> AsyncGenerator[str, None]:
            created = int(datetime.now().timestamp())
            completion_id = f"{completion_id_prefix}-{secrets.token_hex(16)}"

            # First chunk
            first_chunk = ChatCompletionChunk(
                id=completion_id,
                object="chat.completion.chunk",
                created=created,
                model=model,
                choices=[
                    Choice(
                        index=0,
                        delta=ChoiceDelta(role="assistant", content=""),
                        finish_reason=None,
                        logprobs=None
                    )
                ]
            )
            yield f"data: {first_chunk.model_dump_json()}\n\n"

            # Middle chunks
            async for token in func(*args, **kwargs):
                middle_chunk = ChatCompletionChunk(
                    id=completion_id,
                    object="chat.completion.chunk",
                    created=created,
                    model=model,
                    choices=[
                        Choice(
                            index=0,
                            delta=ChoiceDelta(content=str(token)),
                            finish_reason=None,
                            logprobs=None
                        )
                    ]
                )
                yield f"data: {middle_chunk.model_dump_json()}\n\n"

            # Last chunk
            last_chunk = ChatCompletionChunk(
                id=completion_id,
                object="chat.completion.chunk",
                created=created,
                model=model,
                choices=[
                    Choice(
                        index=0,
                        delta=ChoiceDelta(content=""),
                        finish_reason="stop",
                        logprobs=None
                    )
                ]
            )
            yield f"data: {last_chunk.model_dump_json()}\n\n"
            yield "data: [DONE]\n\n"
        return wrapper
    return decorator