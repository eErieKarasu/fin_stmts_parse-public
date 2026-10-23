from langfuse import Langfuse

from lwade_config import config
from langfuse import get_client

_langfuse_client = None
_client_initialized = False

def get_langfuse_client():
    global _langfuse_client, _client_initialized

    if not _client_initialized:
        try:
            # 检查配置是否存在
            if config.ENABLE_AUTO_TRACE_LANGFUSE:
                _langfuse_client = Langfuse(
                    public_key=config.LANGFUSE_PUBLIC_KEY,
                    secret_key=config.LANGFUSE_SECRET_KEY,
                    host=config.LANGFUSE_HOST
                )
            else:
                _langfuse_client = None
                print("Langfuse keys not configured, tracing disabled")
        except Exception as e:
            _langfuse_client = None
            print(f"Failed to initialize Langfuse client: {e}")

        _client_initialized = True

    return _langfuse_client


def __getattr__(name):
    if name == 'langfuse_client':
        return get_langfuse_client()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")