#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一日志管理模块（基于 Loguru）

特性：
- 全局单例 logger，无需每个类单独创建
- 自动注入请求上下文（request_id、company_name）
- 内置线程标识，解决多线程日志交叉问题
- 控制台仅显示 [LIFECYCLE] 标记的 INFO 和 WARNING+ 日志
- 文件日志自动轮转、压缩、保留策略
- InterceptHandler 拦截第三方库的标准 logging 输出
- context_aware_submit 自动传递请求上下文到子线程
"""

import logging
import os
import sys
from contextvars import ContextVar
from concurrent.futures import Executor

from loguru import logger

from fin_stmts_parse.utils.read_yaml import load_env_config


request_context: ContextVar[dict] = ContextVar('request_context', default={})

_logging_initialized = False

LIFECYCLE_MARKER = "[LIFECYCLE]"


def _context_patcher(record):
    """Loguru patcher：每条日志自动注入请求上下文字段"""
    ctx = request_context.get()
    if ctx and ctx.get('request_id'):
        record["extra"]["request_id"] = ctx["request_id"]
        record["extra"]["company_name"] = ctx.get("company_name", "")
    else:
        record["extra"]["request_id"] = "SYSTEM"
        record["extra"]["company_name"] = ""


def _lifecycle_filter(record):
    """控制台过滤：WARNING+ 全部通过，INFO 仅通过 [LIFECYCLE]"""
    if record["level"].no >= 30:
        return True
    if record["level"].no == 20:
        message = record["message"]
        return LIFECYCLE_MARKER in message
    return False


class InterceptHandler(logging.Handler):
    """
    拦截标准 logging 日志，转发到 Loguru。
    利用 LogRecord 已有的调用位置信息（pathname/funcName/lineno），
    通过 patch 直接注入 Loguru，避免帧深度猜测导致的来源误判。
    """

    def emit(self, record: logging.LogRecord):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        logger.opt(exception=record.exc_info).patch(
            lambda r: r.update(
                name=record.name,
                function=record.funcName,
                line=record.lineno,
            )
        ).log(level, record.getMessage())


def _setup_stdlib_intercept():
    """拦截标准 logging，统一转发到 Loguru。"""
    logging.basicConfig(handlers=[InterceptHandler()], level=logging.ERROR, force=True)
    for name in logging.root.manager.loggerDict:
        lib_logger = logging.getLogger(name)
        lib_logger.handlers = [InterceptHandler()]
        lib_logger.setLevel(logging.ERROR)
        lib_logger.propagate = False


def setup_logging(*, intercept_stdlib: bool = True):
    """
    全局日志初始化，应在应用启动时调用一次。

    - 移除 Loguru 默认 handler
    - 配置 Console（带 LIFECYCLE 过滤）和 File（完整 DEBUG）两个 sink
    - 注入 patcher 自动填充 request_id
    - 可选拦截标准 logging，统一转发到 Loguru
    """
    global _logging_initialized
    if _logging_initialized:
        return
    _logging_initialized = True

    logger.remove()

    env = os.getenv("RUNNING_ENV", "local")
    try:
        config = load_env_config(env)
        log_dir = config.get("log", {}).get("root_path", "/tmp/fin_stmts_parse/logs")
    except Exception:
        log_dir = "/tmp/fin_stmts_parse/logs"

    os.makedirs(log_dir, exist_ok=True)

    CONSOLE_FORMAT = (
        "<green>{time:HH:mm:ss}</green> | "
        "<level>{level}</level> | "
        "<cyan>[{extra[request_id]}]</cyan> | "
        "<level>{message}</level>"
    )

    FILE_FORMAT = (
        "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
        "{level: <8} | "
        "[{extra[request_id]}] | "
        "{thread.name} | "
        "{name}:{function}:{line} - "
        "{message}"
    )

    logger.configure(patcher=_context_patcher)

    logger.add(
        sys.stderr,
        format=CONSOLE_FORMAT,
        filter=_lifecycle_filter,
        level="INFO",
        colorize=True,
    )

    logger.add(
        os.path.join(log_dir, "system_{time:YYYY-MM-DD}.log"),
        format=FILE_FORMAT,
        level="DEBUG",
        rotation="100 MB",
        retention="30 days",
        compression="gz",
        encoding="utf-8",
        enqueue=True,
    )

    if intercept_stdlib:
        _setup_stdlib_intercept()


def setup_logger(cls_name: str):
    """
    兼容旧接口：返回全局 loguru logger。

    旧代码调用 setup_logger("ClassName") 后仍可正常工作，
    但底层已统一走 Loguru，不再创建独立的 logging.Logger 实例。
    """
    if not _logging_initialized:
        setup_logging()
    return logger


def context_aware_submit(executor: Executor, fn, *args, **kwargs):
    """
    自动将当前请求上下文传递到子线程。

    用法：
        future = context_aware_submit(executor, my_func, arg1, arg2)

    替代：
        current_context = request_context.get()
        def wrapper():
            request_context.set(current_context)
            return my_func(arg1, arg2)
        future = executor.submit(wrapper)
    """
    ctx = request_context.get()

    def wrapper(*a, **kw):
        request_context.set(ctx)
        return fn(*a, **kw)

    return executor.submit(wrapper, *args, **kwargs)
