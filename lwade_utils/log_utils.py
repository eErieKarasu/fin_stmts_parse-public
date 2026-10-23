import logging

from contextvars import ContextVar


request_id_ctx = ContextVar("request_id", default="N/A")


class RequestIDFilter(logging.Filter):
    """
    这是一个日志过滤器，它不过滤日志，而是将 context 中的 request_id
    注入到日志记录(record)中，供 Formatter 使用。
    """
    def filter(self, record):
        record.request_id = request_id_ctx.get()
        return True


def get_uvicorn_log_config(server: str):
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "request_id_filter": {
                "()": RequestIDFilter
            }
        },
        "formatters": {
            "default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": f"%(asctime)s - {server} - %(request_id)s - %(levelname)s - %(message)s"
            },
            "access": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": f"%(asctime)s - {server} - %(request_id)s - %(levelname)s - %(client_addr)s - %(request_line)s - %(status_code)s"
            }
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
                "filters": ["request_id_filter"],
            },
            "access": {
                "formatter": "access",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "filters": ["request_id_filter"],
            }
        },
        "loggers": {
            "": {  # ← root logger
                "handlers": ["default"],
                "level": "INFO",
            },
            "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"level": "INFO"},
            "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
            "gunicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "gunicorn.access": {"handlers": ["default"], "level": "INFO", "propagate": False},
        }
    }


def get_custom_logger(name: str,formatter: str):
    logger = logging.getLogger(name)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(formatter)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        root_logger = logging.getLogger()
        if not root_logger.handlers:
            root_handler = logging.StreamHandler()
            root_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            root_handler.setFormatter(root_formatter)
            root_logger.addHandler(root_handler)
        root_logger.setLevel(logging.INFO)

    return logger