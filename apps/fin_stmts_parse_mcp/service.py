import json
import os
import sys
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Dict, List, Optional, cast
from urllib.parse import unquote, urlparse

MCP_PACKAGE_DIR = Path(__file__).resolve().parents[2] / "packages" / "mcp"

if str(MCP_PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_PACKAGE_DIR))

def _evict_conflicting_dependency(module_prefix: str) -> None:
    for module_name in list(sys.modules):
        if module_name != module_prefix and not module_name.startswith(f"{module_prefix}."):
            continue

        loaded_module = sys.modules.get(module_name)
        if loaded_module is None:
            continue

        loaded_path = getattr(loaded_module, "__file__", "") or ""
        if loaded_path and not loaded_path.startswith(str(MCP_PACKAGE_DIR)):
            sys.modules.pop(module_name, None)


for _module_name in ("typing_extensions", "attr", "attrs"):
    _evict_conflicting_dependency(_module_name)

import anyio

from fastmcp import Context, FastMCP

from fin_stmts_parse.src.core.contracts import (
    InspectionResult,
    MappedStatementResult,
    StatementMarkdownDocument,
    mapped_statement_result_from_item,
    normalize_is_consolidated,
    resolve_statement_period,
    resolve_statement_type,
    statement_markdown_document_from_item,
    statement_markdown_documents_from_items,
)
from fin_stmts_parse.src.company_name_resolver import (
    CompanyNameResolver,
    resolve_unique_company_name,
)
from fin_stmts_parse.src.core.export_excel import FinancialStatementExcelExportCore
from fin_stmts_parse.src.core.inspect import FinancialStatementInspectCore
from fin_stmts_parse.src.core.map import FinancialStatementMapCore
from fin_stmts_parse.src.core.audit import FinancialStatementAuditFirmCore
from fin_stmts_parse.src.financial_inspector import (
    BALANCE_BASIC_RULES,
    BALANCE_HIERARCHICAL_RULES,
    CASHFLOW_BASIC_RULES,
)
from fin_stmts_parse.src.core.parse import (
    FinancialStatementParseCore,
    SUPPORTED_EXCEL_EXTENSIONS,
    SUPPORTED_IMAGE_EXTENSIONS,
    SUPPORTED_PDF_EXTENSIONS,
)
from fin_stmts_parse.src.persistence import (
    FinancialStatementFactBuilder,
    FinancialStatementFactSource,
    MarkdownFinancialStatementFactBuilder,
    PostgresFinancialStatementRepository,
)
from fin_stmts_parse.clients.llm_client import LLMClient
from fin_stmts_parse.utils.file_transfer import batch_download
from fin_stmts_parse.utils.logger import (
    context_aware_submit,
    logger,
    request_context,
    setup_logging,
)
from fin_stmts_parse.utils.read_yaml import load_env_config
from fin_stmts_parse.utils.s3_client import S3Client

setup_logging(intercept_stdlib=False)

mcp_server = FastMCP("fin_stmts_parse MCP Server")
REPO_ROOT = Path(__file__).resolve().parents[2]


MCP_PROGRESS_TOTALS = MappingProxyType({
    "parse_fin_stmts_markdown": 5,
    "fin_stmts_parse_map": 5,
    "fin_stmts_parse_inspect": 5,
    "fin_stmts_parse_markdown_to_excel": 5,
    "fin_stmts_parse_audit_firm": 5,
})
SUPPORTED_FILE_KINDS = MappingProxyType({
    **{suffix: "image" for suffix in SUPPORTED_IMAGE_EXTENSIONS},
    **{suffix: "pdf" for suffix in SUPPORTED_PDF_EXTENSIONS},
    **{suffix: "excel" for suffix in SUPPORTED_EXCEL_EXTENSIONS},
})
PRIVATE_MAP_RESULTS_BY_SESSION: Dict[str, List[Dict[str, Any]]] = {}
MCP_TOOL_LOG_LOCK = threading.Lock()
MCP_PERSISTENT_BASE_DIR = Path("/tmp/fin_stmts_parse/mcp")
DEFAULT_MCP_PARSE_MAX_WORKERS = 4
DECIMAL_TOLERANCE = Decimal("0.01")
BALANCE_VALIDATED_COMPONENT_EXTRAS = MappingProxyType({
    "ZY2015061": (
        {"code": "Z02010710", "name": "优先股"},
        {"code": "Z02010711", "name": "永续债"},
    ),
})


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _resolve_mcp_persistent_dir(name: str) -> str:
    date_prefix = datetime.now().strftime("%Y%m%d")
    base_dir = Path(os.getenv("MCP_PERSISTENT_BASE_DIR", str(MCP_PERSISTENT_BASE_DIR)))
    directory = base_dir / date_prefix / name
    directory.mkdir(parents=True, exist_ok=True)
    return str(directory)


def _resolve_mcp_parse_max_workers() -> int:
    raw_value = os.getenv(
        "MCP_PARSE_MAX_WORKERS",
        str(DEFAULT_MCP_PARSE_MAX_WORKERS),
    )
    try:
        return max(1, int(raw_value))
    except (TypeError, ValueError):
        logger.warning(
            "[LIFECYCLE] MCP_PARSE_MAX_WORKERS 配置无效，"
            f"使用默认值 {DEFAULT_MCP_PARSE_MAX_WORKERS}: {raw_value}"
        )
        return DEFAULT_MCP_PARSE_MAX_WORKERS


def _parse_decimal(value: Any) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _resolve_mcp_tool_log_dir() -> Path:
    env = os.getenv("RUNNING_ENV", "local")
    try:
        config = load_env_config(env)
        return Path(config.get("log", {}).get("root_path", "/tmp/fin_stmts_parse/logs"))
    except Exception:
        return Path("/tmp/fin_stmts_parse/logs")


def _write_mcp_tool_log(record: Dict[str, Any]) -> None:
    log_dir = _resolve_mcp_tool_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"mcp_tools_{datetime.now().strftime('%Y-%m-%d')}.jsonl"
    line = json.dumps(record, ensure_ascii=False, default=str)
    with MCP_TOOL_LOG_LOCK:
        with log_path.open("a", encoding="utf-8") as file:
            file.write(f"{line}\n")


def _safe_write_mcp_tool_log(record: Dict[str, Any]) -> None:
    try:
        _write_mcp_tool_log(record)
    except Exception as exc:
        logger.warning(f"[LIFECYCLE] MCP tool audit log write failed: {exc}")


def _extract_session_id(input_payload: Dict[str, Any]) -> str:
    session_id = input_payload.get("session_id")
    return str(session_id).strip() if session_id is not None else ""


class MCPProgressReporter:
    def __init__(self, ctx: Optional[Context], total: int):
        self.ctx = ctx
        self.total = total
        self.current = 0.0

    def report(self, message: str, *, progress: Optional[float] = None) -> None:
        if progress is None:
            self.current = min(self.current + 1, float(self.total))
        else:
            self.current = max(0.0, min(float(progress), float(self.total)))

        if self.ctx is None:
            return

        try:
            anyio.from_thread.run(
                self.ctx.report_progress,
                self.current,
                float(self.total),
                message,
            )
        except Exception as exc:
            logger.debug(f"[LIFECYCLE] MCP progress notify skipped: {exc}")


def _progress_call_kwargs(progress: MCPProgressReporter) -> Dict[str, MCPProgressReporter]:
    return {"progress": progress} if progress.ctx is not None else {}


def _summarize_exception(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        message = type(exc).__name__
    return message[:160]


def _run_mcp_tool_call(
    tool_name: str,
    input_payload: Dict[str, Any],
    call: Callable[[], Any],
    *,
    progress: Optional[MCPProgressReporter] = None,
) -> Any:
    session_id = _extract_session_id(input_payload)
    started_at = _now_iso()
    started_perf = time.perf_counter()
    context_token = None

    if session_id:
        context_token = request_context.set(
            {
                "request_id": session_id,
                "session_id": session_id,
                "company_name": "",
            }
        )

    logger.info(f"[LIFECYCLE] MCP tool start: {tool_name} session_id={session_id or '-'}")
    if progress is not None:
        progress.report("已接收请求，开始处理", progress=1)

    try:
        output = call()
    except Exception as exc:
        finished_at = _now_iso()
        duration_ms = int((time.perf_counter() - started_perf) * 1000)
        if progress is not None:
            progress.report(
                f"处理失败：{_summarize_exception(exc)}",
                progress=progress.total,
            )
        _safe_write_mcp_tool_log(
            {
                "event": "mcp_tool_call",
                "tool": tool_name,
                "session_id": session_id,
                "status": "error",
                "started_at": started_at,
                "finished_at": finished_at,
                "duration_ms": duration_ms,
                "input": input_payload,
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                },
            }
        )
        logger.warning(
            f"[LIFECYCLE] MCP tool error: {tool_name} "
            f"session_id={session_id or '-'} duration_ms={duration_ms} "
            f"error={type(exc).__name__}: {exc}"
        )
        raise
    else:
        finished_at = _now_iso()
        duration_ms = int((time.perf_counter() - started_perf) * 1000)
        if progress is not None:
            progress.report("处理完成", progress=progress.total)
        _safe_write_mcp_tool_log(
            {
                "event": "mcp_tool_call",
                "tool": tool_name,
                "session_id": session_id,
                "status": "success",
                "started_at": started_at,
                "finished_at": finished_at,
                "duration_ms": duration_ms,
                "input": input_payload,
                "output": output,
            }
        )
        logger.info(
            f"[LIFECYCLE] MCP tool success: {tool_name} "
            f"session_id={session_id or '-'} duration_ms={duration_ms}"
        )
        return output
    finally:
        if context_token is not None:
            request_context.reset(context_token)


@dataclass(frozen=True)
class InputFile:
    fileName: str
    fileUrl: str


def _normalize_required_session_id(session_id: str) -> str:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise ValueError("session_id 不能为空")
    return normalized_session_id


def _normalize_optional_page(value: Any) -> Optional[int]:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        page = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return page if page > 0 else None


def _cache_private_map_results(
    session_id: str,
    map_results: List[Dict[str, Any]],
) -> None:
    PRIVATE_MAP_RESULTS_BY_SESSION[session_id] = deepcopy(map_results)


def _get_cached_private_map_results(
    session_id: str,
) -> Optional[List[Dict[str, Any]]]:
    cached_results = PRIVATE_MAP_RESULTS_BY_SESSION.get(session_id)
    if cached_results is None:
        return None
    return deepcopy(cached_results)


def _clear_private_map_results_cache() -> None:
    PRIVATE_MAP_RESULTS_BY_SESSION.clear()


class FinStmtsMapService:
    def __init__(self):
        env = os.getenv("RUNNING_ENV", "local")
        config = load_env_config(env)
        self.map_core = FinancialStatementMapCore(config, repo_root=REPO_ROOT)
        llm_config = config.get("llm", {})
        llm_client = LLMClient(llm_config) if llm_config.get("base_url") else None
        self.company_name_resolver = CompanyNameResolver(llm_client=llm_client)

    def fin_stmts_parse_map(
        self,
        parse_results: List[Any],
        *,
        session_id: str,
        progress: Optional[MCPProgressReporter] = None,
    ) -> List[Dict[str, Any]]:
        normalized_session_id = _normalize_required_session_id(session_id)
        if not parse_results:
            raise ValueError("parse_results 不能为空")

        if progress is not None:
            progress.report("正在校验参数并准备输入", progress=2)
        normalized_results = self._normalize_parse_results(parse_results)
        if progress is not None:
            progress.report("正在将 Markdown 映射为标准科目", progress=3)
        private_map_results = [
            self._map_single_parse_result(item)
            for item in normalized_results
        ]
        _cache_private_map_results(normalized_session_id, private_map_results)
        self._run_passive_inspect(
            map_results=_get_cached_private_map_results(normalized_session_id) or private_map_results,
            session_id=normalized_session_id,
            progress=progress,
        )
        return [
            self._to_public_file_result(item)
            for item in private_map_results
        ]

    def _run_passive_inspect(
        self,
        *,
        map_results: List[Dict[str, Any]],
        session_id: str,
        progress: Optional[MCPProgressReporter] = None,
    ) -> None:
        try:
            if progress is not None:
                progress.report("正在执行被动勾稽校验", progress=4)
            get_inspect_service().fin_stmts_parse_inspect(
                map_results=map_results,
                session_id=session_id,
                report_status="0",
            )
        except Exception as exc:
            logger.warning(f"[LIFECYCLE] map 后触发被动勾稽校验失败: {exc}")

    def _normalize_parse_results(self, parse_results: List[Any]) -> List[Dict[str, Any]]:
        normalized_results: List[Dict[str, Any]] = []
        for index, item in enumerate(parse_results, start=1):
            if not isinstance(item, dict) or "markdown_files" not in item:
                raise ValueError(
                    "parse_results 必须是 parse_fin_stmts_markdown 的完整输出"
                )
            normalized_results.append(
                {
                    "message": item.get("message", ""),
                    "file_name": self._pick_file_name(item, index),
                    "company_name": self._resolve_company_name(item),
                    "markdown_files": item.get("markdown_files"),
                }
            )
        return normalized_results

    def _map_single_parse_result(self, item: Dict[str, Any]) -> Dict[str, Any]:
        markdown_files = item.get("markdown_files")
        if not isinstance(markdown_files, list) or not markdown_files:
            return {
                "message": "没有可映射的 markdown_files",
                "file_name": item["file_name"],
                "company_name": item["company_name"],
                "mapped_results": [],
            }

        mapped_results: List[Dict[str, Any]] = []
        succeeded = 0
        failed = 0

        for markdown_file in markdown_files:
            item_result = self._map_single_item(markdown_file)
            item_status = item_result.pop("_status", "failed")
            if item_status == "success":
                succeeded += 1
            else:
                failed += 1
            mapped_results.append(item_result)

        total = len(mapped_results)
        if succeeded == total:
            message = f"全部 {total} 项 markdown 映射成功"
        elif succeeded == 0:
            message = f"{total} 项 markdown 映射全部失败"
        else:
            message = f"{succeeded} 项成功，{failed} 项失败"

        return {
            "message": message,
            "file_name": item["file_name"],
            "company_name": item["company_name"],
            "mapped_results": mapped_results,
        }

    @staticmethod
    def _pick_file_name(item: Dict[str, Any], index: int) -> str:
        for key in ("file_name", "source_file_name", "name"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return Path(value.strip()).name
        return f"input_{index}"

    def _resolve_company_name(self, item: Dict[str, Any]) -> str:
        company_name = item.get("company_name")
        if isinstance(company_name, str) and company_name.strip():
            return company_name.strip()
        markdown_files = item.get("markdown_files")
        if isinstance(markdown_files, list):
            return self.company_name_resolver.extract_from_items(
                markdown_file
                for markdown_file in markdown_files
                if isinstance(markdown_file, dict)
            )
        return ""

    def _map_single_item(self, item: Any) -> Dict[str, Any]:
        if not isinstance(item, dict):
            return self._build_base_result({}, status="failed")

        document = statement_markdown_document_from_item(item)
        if document is None or not document.content.strip():
            return self._build_base_result(item, status="failed")

        try:
            mapped_result = self.map_core.map_markdown_document(
                document,
                mapping_config_dir=item.get("mapping_config_dir"),
            )
        except (FileNotFoundError, ValueError):
            return self._build_base_result(item, status="failed")
        except Exception:
            return self._build_base_result(item, status="failed")

        return self._build_base_result(
            item,
            status="success",
            is_consolidated=mapped_result.is_consolidated,
            canonical_data=mapped_result.to_serialized_canonical_data(),
            view_data=mapped_result.to_serialized_view_data_tree(),
            document=document,
        )

    @staticmethod
    def _build_base_result(
        item: Dict[str, Any],
        *,
        status: str = "failed",
        is_consolidated: Any = None,
        canonical_data: Optional[Dict[str, List[Any]]] = None,
        view_data: Optional[List[Dict[str, Any]]] = None,
        document: Optional[StatementMarkdownDocument] = None,
    ) -> Dict[str, Any]:
        return {
            "_status": status,
            "table_name": item.get("table_name") if document is None else document.table_name,
            "table_type": item.get("table_type", "") if document is None else document.table_type,
            **(
                {"page": _normalize_optional_page(item.get("page"))}
                if document is None and _normalize_optional_page(item.get("page")) is not None
                else {}
            ),
            **({"page": document.page} if document is not None and document.page is not None else {}),
            "date": item.get("date") if document is None else document.date,
            "period": item.get("period", "") if document is None else document.period,
            "is_consolidated": normalize_is_consolidated(
                item.get("is_consolidated", False)
                if is_consolidated is None
                else is_consolidated
            ),
            "view_data": view_data or [],
            "canonical_data": canonical_data or {},
        }

    @staticmethod
    def _to_public_file_result(item: Dict[str, Any]) -> Dict[str, Any]:
        mapped_results = item.get("mapped_results")
        public_mapped_results = []
        if isinstance(mapped_results, list):
            public_mapped_results = [
                FinStmtsMapService._to_public_mapped_item(mapped_item)
                for mapped_item in mapped_results
            ]
        return {
            "message": item.get("message", ""),
            "file_name": item.get("file_name", ""),
            "company_name": item.get("company_name", ""),
            "mapped_results": public_mapped_results,
        }

    @staticmethod
    def _to_public_mapped_item(item: Any) -> Dict[str, Any]:
        if not isinstance(item, dict):
            return {}
        return {
            key: value
            for key, value in item.items()
            if key != "canonical_data"
        }

class FinStmtsInspectService:
    STATEMENT_TYPES = ("balance", "profit", "cashflow")

    def __init__(self):
        env = os.getenv("RUNNING_ENV", "local")
        config = load_env_config(env)
        self.inspect_core = FinancialStatementInspectCore()
        self.fact_builder = FinancialStatementFactBuilder()
        self.repository = PostgresFinancialStatementRepository(config, logger=logger)

    def fin_stmts_parse_inspect(
        self,
        map_results: List[Any],
        *,
        session_id: str,
        report_status: str = "1",
        progress: Optional[MCPProgressReporter] = None,
    ) -> Dict[str, Any]:
        normalized_session_id = _normalize_required_session_id(session_id)
        if not isinstance(map_results, list):
            raise ValueError("map_results 必须是数组")
        normalized_report_status = str(report_status or "").strip()
        if normalized_report_status not in {"0", "1"}:
            raise ValueError("report_status 仅支持 0 或 1")
        report_status = normalized_report_status

        if progress is not None:
            progress.report("正在校验参数并准备输入", progress=2)
        normalized_results = self._normalize_map_results(map_results)
        normalized_results = self._hydrate_map_results_with_canonical_data(
            normalized_results,
            session_id=normalized_session_id,
        )
        if not self._uses_passive_canonical_cache(report_status):
            normalized_results = self._materialize_canonical_data_from_view_data(
                normalized_results
            )

        fact_sources: List[FinancialStatementFactSource] = []
        file_results: List[Dict[str, Any]] = []
        total_inspectable_count = 0
        overall_passed = True

        if progress is not None:
            inspect_message = (
                "正在执行被动勾稽校验"
                if self._uses_passive_canonical_cache(report_status)
                else "正在执行勾稽校验"
            )
            progress.report(inspect_message, progress=3)
        for file_index, item in enumerate(normalized_results, start=1):
            inspected_results: List[Dict[str, Any]] = []
            file_total_checks = 0
            file_passed_checks = 0
            file_failed_checks = 0
            file_passed = True

            for mapped_item in item["mapped_results"]:
                collected = self._collect_item(
                    item=mapped_item,
                    default_file_name=item["file_name"],
                    default_company_name=item["company_name"],
                    source_group_key=str(file_index),
                )
                if collected is None:
                    continue

                mapped_result, fact_source = collected
                fact_sources.append(fact_source)

                inspection_result = self.inspect_core.inspect_mapped_results([mapped_result])
                inspected_result_item = self._build_inspected_result_item(
                    mapped_result,
                    inspection_result,
                )
                inspected_results.append(inspected_result_item)
                total_inspectable_count += 1
                formatted_passed_checks = self._count_formatted_details_by_status(
                    inspected_result_item["details"],
                    "pass",
                )
                formatted_failed_checks = self._count_formatted_details_by_status(
                    inspected_result_item["details"],
                    "fail",
                )
                file_passed_checks += formatted_passed_checks
                file_failed_checks += formatted_failed_checks
                file_total_checks += formatted_passed_checks + formatted_failed_checks
                file_passed = (
                    file_passed
                    and inspection_result.passed
                    and not self._has_formatted_failures(inspected_result_item["details"])
                )

            overall_passed = overall_passed and file_passed

            if inspected_results:
                message = (
                    f"勾稽校验完成，有{len(inspected_results)} 张表参与了校验；"
                    f"总计 {file_total_checks} 条，{file_passed_checks} 条通过，"
                    f"{file_failed_checks} 条失败"
                )
            else:
                file_passed = False
                overall_passed = False
                message = "没有可用于勾稽校验的映射结果"

            file_results.append(
                {
                    "message": message,
                    "file_name": item["file_name"],
                    "company_name": item["company_name"],
                    "inspection_passed": file_passed if inspected_results else False,
                    "inspected_results": inspected_results,
                }
            )

        if total_inspectable_count == 0:
            return file_results

        should_save = self._should_save(
            report_status=report_status,
            inspection_passed=overall_passed,
        )
        save_mode = self._resolve_save_mode(report_status)
        if should_save:
            if progress is not None:
                progress.report("正在保存校验结果", progress=4)
            logger.info(
                f"[LIFECYCLE] 开始{save_mode}校验入库: "
                f"session_id={normalized_session_id}, "
                f"inspection_passed={overall_passed}, "
                f"fact_sources={len(fact_sources)}"
            )
            rows: List[Any] = []
            try:
                rows = self.fact_builder.build_rows(
                    session_id=normalized_session_id,
                    report_status=report_status,
                    sources=fact_sources,
                )
                saved_stat_date = str(rows[0].stat_date) if rows else ""
                self.repository.replace_session_snapshot(
                    normalized_session_id,
                    rows,
                    report_status=report_status,
                    target_sources=fact_sources,
                )
                logger.info(
                    f"[LIFECYCLE] {save_mode}校验入库完成: "
                    f"session_id={normalized_session_id}, "
                    f"stat_date={saved_stat_date}, "
                    f"saved_rows={len(rows)}, "
                    f"inspection_passed={overall_passed}"
                )
            except Exception as exc:
                saved_stat_date = str(rows[0].stat_date) if rows else ""
                context = f"session_id={normalized_session_id}"
                if saved_stat_date:
                    context = f"{context}, stat_date={saved_stat_date}"
                logger.warning(
                    f"[LIFECYCLE] {save_mode}校验入库失败: "
                    f"{context}, "
                    f"error={exc}"
                )
        else:
            if progress is not None:
                progress.report("校验未通过，跳过入库保存", progress=4)
            logger.info(
                f"[LIFECYCLE] {save_mode}校验未通过，跳过入库: "
                f"session_id={normalized_session_id}, "
                f"inspection_passed={overall_passed}"
            )

        return file_results

    @staticmethod
    def _normalize_map_results(map_results: List[Any]) -> List[Dict[str, Any]]:
        normalized_results: List[Dict[str, Any]] = []
        for index, item in enumerate(map_results, start=1):
            if not isinstance(item, dict) or "mapped_results" not in item:
                raise ValueError(
                    "map_results 必须是 fin_stmts_parse_map 的完整输出"
                )
            mapped_results = item.get("mapped_results")
            if not isinstance(mapped_results, list):
                raise ValueError(
                    "map_results 必须是 fin_stmts_parse_map 的完整输出"
                )

            file_name = item.get("file_name")
            if not isinstance(file_name, str) or not file_name.strip():
                file_name = f"input_{index}"

            company_name = item.get("company_name")
            normalized_results.append(
                {
                    "file_name": Path(file_name).name,
                    "company_name": company_name.strip() if isinstance(company_name, str) else "",
                    "mapped_results": mapped_results,
                }
            )
        return normalized_results

    def _hydrate_map_results_with_canonical_data(
        self,
        normalized_results: List[Dict[str, Any]],
        *,
        session_id: str,
    ) -> List[Dict[str, Any]]:
        if not self._requires_canonical_hydration(normalized_results):
            return normalized_results

        cached_results = _get_cached_private_map_results(session_id)
        if not cached_results:
            return normalized_results

        hydrated_results: List[Dict[str, Any]] = []
        for file_index, result in enumerate(normalized_results):
            cached_file_result = self._find_cached_file_result(
                result,
                cached_results,
                file_index=file_index,
            )
            cached_mapped_results = []
            if isinstance(cached_file_result, dict):
                cached_items = cached_file_result.get("mapped_results")
                if isinstance(cached_items, list):
                    cached_mapped_results = cached_items

            hydrated_mapped_results = []
            for mapped_index, mapped_item in enumerate(result["mapped_results"]):
                hydrated_mapped_results.append(
                    self._hydrate_mapped_item_with_canonical_data(
                        mapped_item,
                        cached_mapped_results,
                        mapped_index=mapped_index,
                    )
                )

            hydrated_results.append({
                **result,
                "mapped_results": hydrated_mapped_results,
            })

        return hydrated_results

    @staticmethod
    def _uses_passive_canonical_cache(report_status: str) -> bool:
        return str(report_status or "").strip() == "0"

    @classmethod
    def _materialize_canonical_data_from_view_data(
        cls,
        normalized_results: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        materialized_results: List[Dict[str, Any]] = []
        for result in normalized_results:
            materialized_mapped_results = []
            mapped_results = result.get("mapped_results")
            if not isinstance(mapped_results, list):
                materialized_results.append(result)
                continue

            for mapped_item in mapped_results:
                if not isinstance(mapped_item, dict):
                    materialized_mapped_results.append(mapped_item)
                    continue

                flattened_view_data = cls._flatten_view_data_for_canonical(
                    mapped_item.get("view_data")
                )
                if not flattened_view_data:
                    materialized_mapped_results.append(mapped_item)
                    continue

                canonical_data = mapped_item.get("canonical_data")
                if not isinstance(canonical_data, dict):
                    canonical_data = {}

                materialized_mapped_results.append(
                    {
                        **mapped_item,
                        "canonical_data": {
                            **deepcopy(canonical_data),
                            **flattened_view_data,
                        },
                    }
                )

            materialized_results.append({
                **result,
                "mapped_results": materialized_mapped_results,
            })
        return materialized_results

    @staticmethod
    def _flatten_view_data_for_canonical(view_data: Any) -> Dict[str, Any]:
        if not view_data:
            return {}

        if isinstance(view_data, dict):
            rows = view_data.get("rows")
            if isinstance(rows, dict):
                return deepcopy(rows)
            if not (
                "groups" in view_data
                or "children" in view_data
                or "roots" in view_data
            ):
                return deepcopy(view_data)

        flattened: Dict[str, Any] = {}

        def visit(node: Any) -> None:
            if isinstance(node, list):
                for child in node:
                    visit(child)
                return
            if not isinstance(node, dict):
                return

            code = str(node.get("code") or "").strip()
            if code:
                values = node.get("values", [])
                if not isinstance(values, list):
                    values = [values]
                name = str(node.get("name") or code).strip()
                flattened[code] = [name, *deepcopy(values)] if name else deepcopy(values)

            visit(node.get("rows", []))
            visit(node.get("groups", []))
            visit(node.get("children", []))

        visit(view_data)
        return flattened

    @staticmethod
    def _requires_canonical_hydration(
        normalized_results: List[Dict[str, Any]],
    ) -> bool:
        for result in normalized_results:
            mapped_results = result.get("mapped_results")
            if not isinstance(mapped_results, list):
                continue
            for mapped_item in mapped_results:
                if isinstance(mapped_item, dict) and "canonical_data" not in mapped_item:
                    return True
        return False

    @classmethod
    def _find_cached_file_result(
        cls,
        result: Dict[str, Any],
        cached_results: List[Dict[str, Any]],
        *,
        file_index: int,
    ) -> Optional[Dict[str, Any]]:
        if 0 <= file_index < len(cached_results):
            candidate = cached_results[file_index]
            if cls._match_file_result(result, candidate):
                return candidate

        for candidate in cached_results:
            if cls._match_file_result(result, candidate):
                return candidate
        return None

    @staticmethod
    def _match_file_result(
        result: Dict[str, Any],
        candidate: Any,
    ) -> bool:
        if not isinstance(candidate, dict):
            return False

        file_name = str(result.get("file_name") or "").strip()
        candidate_file_name = Path(str(candidate.get("file_name") or "")).name
        if file_name and candidate_file_name and file_name != candidate_file_name:
            return False

        company_name = str(result.get("company_name") or "").strip()
        candidate_company_name = str(candidate.get("company_name") or "").strip()
        if company_name and candidate_company_name and company_name != candidate_company_name:
            return False

        return True

    @classmethod
    def _hydrate_mapped_item_with_canonical_data(
        cls,
        mapped_item: Any,
        cached_mapped_results: List[Dict[str, Any]],
        *,
        mapped_index: int,
    ) -> Any:
        if not isinstance(mapped_item, dict) or "canonical_data" in mapped_item:
            return mapped_item

        cached_item = cls._find_cached_mapped_item(
            mapped_item,
            cached_mapped_results,
            mapped_index=mapped_index,
        )
        if not isinstance(cached_item, dict):
            return mapped_item

        canonical_data = cached_item.get("canonical_data")
        if not isinstance(canonical_data, dict):
            return mapped_item

        hydrated_item = dict(mapped_item)
        hydrated_item["canonical_data"] = deepcopy(canonical_data)
        for key in (
            "statement_type",
            "unit",
            "semantic_config_path_used",
            "view_config_path_used",
            "source_file_name",
            "source_file_path",
        ):
            if key not in hydrated_item and key in cached_item:
                hydrated_item[key] = deepcopy(cached_item[key])
        return hydrated_item

    @classmethod
    def _find_cached_mapped_item(
        cls,
        mapped_item: Dict[str, Any],
        cached_mapped_results: List[Dict[str, Any]],
        *,
        mapped_index: int,
    ) -> Optional[Dict[str, Any]]:
        if 0 <= mapped_index < len(cached_mapped_results):
            candidate = cached_mapped_results[mapped_index]
            if cls._match_mapped_item(mapped_item, candidate):
                return candidate

        for candidate in cached_mapped_results:
            if cls._match_mapped_item(mapped_item, candidate):
                return candidate
        return None

    @staticmethod
    def _match_mapped_item(
        mapped_item: Dict[str, Any],
        candidate: Any,
    ) -> bool:
        if not isinstance(candidate, dict):
            return False

        for key in ("table_name", "date"):
            value = mapped_item.get(key)
            candidate_value = candidate.get(key)
            if value not in (None, "") and candidate_value not in (None, "") and value != candidate_value:
                return False

        page = _normalize_optional_page(mapped_item.get("page"))
        candidate_page = _normalize_optional_page(candidate.get("page"))
        if page is not None and candidate_page is not None and page != candidate_page:
            return False

        return normalize_is_consolidated(
            mapped_item.get("is_consolidated", False)
        ) == normalize_is_consolidated(candidate.get("is_consolidated", False))

    @staticmethod
    def _should_save(
        *,
        report_status: str,
        inspection_passed: bool,
    ) -> bool:
        if str(report_status or "").strip() == "0":
            return True
        return inspection_passed

    @staticmethod
    def _resolve_save_mode(report_status: str) -> str:
        return "被动" if str(report_status or "").strip() == "0" else "主动"

    def _collect_item(
        self,
        item: Any,
        *,
        default_file_name: str,
        default_company_name: str,
        source_group_key: str,
    ) -> Optional[tuple[MappedStatementResult, FinancialStatementFactSource]]:
        if not isinstance(item, dict):
            return None

        normalized_item = dict(item)
        normalized_item.setdefault("file_name", default_file_name)
        normalized_item.setdefault("source_file_name", default_file_name)

        item_status = normalized_item.get("status")
        if item_status is not None and item_status != "success":
            return None

        statement_type = self._resolve_statement_type(normalized_item)
        if not isinstance(statement_type, str) or not statement_type.strip():
            return None

        normalized_statement_type = statement_type.strip()
        if normalized_statement_type not in self.STATEMENT_TYPES:
            return None

        if "canonical_data" not in normalized_item:
            return None

        canonical_data = normalized_item.get("canonical_data")
        if not isinstance(canonical_data, dict):
            return None

        mapped_result = mapped_statement_result_from_item(normalized_item)
        if mapped_result is None:
            return None

        return mapped_result, FinancialStatementFactSource(
            mapped_result=mapped_result,
            company_name=default_company_name,
            file_name=default_file_name,
            source_group_key=source_group_key,
        )

    def _build_inspected_result_item(
        self,
        mapped_result: MappedStatementResult,
        inspection_result: InspectionResult,
    ) -> Dict[str, Any]:
        details = [
            detail
            for detail in inspection_result.details
            if str(detail.get("_table") or "").strip() == mapped_result.statement_type
        ]
        suppressed_checks = self._semantic_covered_hierarchical_checks(details)
        supported_inferred_keys = self._supported_missing_inferred_keys(details, suppressed_checks)
        confirmed_subtree_failure_keys = self._confirmed_recomputed_subtree_keys(details, suppressed_checks)
        confirmed_recomputed_component_attributions = (
            self._confirmed_recomputed_component_attributions(details, suppressed_checks)
        )
        profit_confirmed_component_parents = self._profit_confirmed_component_parents(
            details,
            suppressed_checks,
        )
        reported_total_supported_values = self._reported_total_supported_values(
            details,
            suppressed_checks,
            supported_inferred_keys,
        )
        return {
            "table_name": mapped_result.table_name,
            "table_type": mapped_result.statement_type,
            "date": mapped_result.date,
            "period": resolve_statement_period(mapped_result.date),
            "is_consolidated": mapped_result.is_consolidated,
            "details": [
                simplified_detail
                for detail in details
                if str(detail.get("check") or "").strip() not in suppressed_checks
                for simplified_detail in self._simplify_detail_items(
                    self._format_detail_items(
                        detail,
                        supported_inferred_keys,
                        confirmed_subtree_failure_keys,
                        confirmed_recomputed_component_attributions,
                        reported_total_supported_values,
                        profit_confirmed_component_parents,
                    )
                )
            ],
        }

    @staticmethod
    def _has_formatted_failures(details: List[Dict[str, Any]]) -> bool:
        return any(
            str(detail.get("status") or "").strip().lower() == "fail"
            for detail in details
        )

    @staticmethod
    def _count_formatted_details_by_status(
        details: List[Dict[str, Any]],
        status: str,
    ) -> int:
        expected_status = str(status or "").strip().lower()
        return sum(
            1
            for detail in details
            if str(detail.get("status") or "").strip().lower() == expected_status
        )

    @classmethod
    def _simplify_detail_items(
        cls,
        details: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        simplified_details: List[Dict[str, Any]] = []
        for detail in details:
            simplified_detail = cls._simplify_detail_item(detail)
            if simplified_detail is not None:
                simplified_details.append(simplified_detail)
        return simplified_details

    @classmethod
    def _simplify_detail_item(
        cls,
        detail: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        status = str(detail.get("status") or "").strip().lower()
        reason = str(detail.get("reason") or "").strip()

        if status in {"pass", "passed", "success", "ok"}:
            normalized_status = "pass"
            short_reason = cls._simplify_pass_reason(reason)
        elif status in {"fail", "failed", "error"}:
            normalized_status = "fail"
            inferred_value = str(
                detail.get("_validated_inferred_value")
                or detail.get("_display_inferred_value")
                or ""
            ).strip()
            suspected_value = str(detail.get("_validated_suspected_value") or "").strip()
            if inferred_value and cls._has_missing_field_signal(reason):
                short_reason = f"字段缺失，推测值是{inferred_value}"
            elif suspected_value and cls._has_suspected_field_signal(reason):
                short_reason = f"疑似字段错误，推测值是{suspected_value}"
            else:
                short_reason = cls._simplify_fail_reason(reason)
        elif status in {"skip", "skipped"}:
            short_reason = cls._simplify_skip_reason(reason)
            if not short_reason:
                return None
            normalized_status = "fail"
        else:
            return None

        simplified_detail = dict(detail)
        simplified_detail.pop("_validated_inferred_value", None)
        simplified_detail.pop("_display_inferred_value", None)
        simplified_detail.pop("_validated_suspected_value", None)
        simplified_detail["status"] = normalized_status
        simplified_detail["reason"] = short_reason
        return simplified_detail

    @staticmethod
    def _simplify_pass_reason(reason: str) -> str:
        if reason in {"", "校验通过", "层级校验通过"}:
            return "校验通过"
        if "子项校验通过" in reason:
            return "校验通过"
        return "复核通过"

    @classmethod
    def _simplify_fail_reason(cls, reason: str) -> str:
        if cls._has_parent_residual_component_mismatch_signal(reason):
            return "子项和不匹配"
        if cls._has_suspected_field_signal(reason):
            return "疑似字段错误"
        if cls._has_missing_field_signal(reason):
            return "字段缺失"
        if cls._has_unverifiable_signal(reason):
            return "无法校验"
        return "校验未通过"

    @classmethod
    def _simplify_skip_reason(cls, reason: str) -> str:
        if not reason:
            return ""
        if reason in {"未参与校验", "合计项未解析出，未参与校验"}:
            return ""
        if "替代公式覆盖" in reason or "替代轨" in reason:
            return ""
        if "组成项均未" in reason:
            return ""
        if cls._has_missing_field_signal(reason):
            return "字段缺失"
        if cls._has_unverifiable_signal(reason):
            return "无法校验"
        return ""

    @staticmethod
    def _has_missing_field_signal(reason: str) -> bool:
        return any(
            token in reason
            for token in (
                "未提取",
                "未解析",
                "缺失",
                "缺少合计",
                "合计项缺失",
                "值为空",
                "缺少资产总计",
            )
        )

    @staticmethod
    def _has_unverifiable_signal(reason: str) -> bool:
        return any(
            token in reason
            for token in (
                "无法校验",
                "无法进行",
                "无法直接校验",
                "缺少足够",
                "未参与校验",
                "不参与勾稽校验",
            )
        )

    @staticmethod
    def _has_parent_residual_component_mismatch_signal(reason: str) -> bool:
        return (
            "上层推测值" in reason
            and "子项和" in reason
            and "差额" in reason
        )

    @staticmethod
    def _has_suspected_field_signal(reason: str) -> bool:
        return any(
            token in reason
            for token in (
                "疑似",
                "识别错误",
                "字段有误",
                "可能有误",
                "已定位",
                "嫌疑",
                "需复核",
                "需核对",
                "异常范围",
                "差异范围",
            )
        )

    @staticmethod
    def _resolve_statement_type(item: Dict[str, Any]) -> Any:
        statement_type = item.get("statement_type")
        if isinstance(statement_type, str) and statement_type.strip():
            return statement_type.strip()

        table_name = item.get("table_name")
        if not isinstance(table_name, str) or not table_name.strip():
            return statement_type

        try:
            resolved, _ = resolve_statement_type(
                table_name,
                item.get("is_consolidated"),
            )
            return resolved
        except ValueError:
            return statement_type

    @staticmethod
    def _build_item_metadata(item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "file_name": item.get("file_name"),
            "source_file_name": item.get("source_file_name"),
            "table_name": item.get("table_name"),
            "date": item.get("date"),
            "unit": item.get("unit"),
            "is_consolidated": normalize_is_consolidated(item.get("is_consolidated", False)),
            "semantic_config_path_used": item.get("semantic_config_path_used"),
            "view_config_path_used": item.get("view_config_path_used"),
        }

    @staticmethod
    def _build_skipped_item(
        metadata: Dict[str, Any],
        statement_type: Any,
        reason_code: str,
        reason: str,
    ) -> Dict[str, Any]:
        return {
            **metadata,
            "status": "skipped",
            "statement_type": statement_type,
            "reason_code": reason_code,
            "reason": reason,
        }

    @staticmethod
    def _format_detail_period(detail: Dict[str, Any]) -> str:
        table = str(detail.get("_table") or "").strip()
        if table in {"profit", "cashflow"}:
            return "end"

        period = str(detail.get("period") or "").strip()
        if period == "年初":
            return "begin"
        return "end"

    @classmethod
    def _empty_grouped_details(cls) -> Dict[str, List[Dict[str, Any]]]:
        return {
            statement_type: []
            for statement_type in cls.STATEMENT_TYPES
        }

    def _group_formatted_details(
        self,
        details: List[Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        grouped_details = self._empty_grouped_details()
        suppressed_checks = self._semantic_covered_hierarchical_checks(details)
        supported_inferred_keys = self._supported_missing_inferred_keys(details, suppressed_checks)
        confirmed_subtree_failure_keys = self._confirmed_recomputed_subtree_keys(details, suppressed_checks)
        confirmed_recomputed_component_attributions = (
            self._confirmed_recomputed_component_attributions(details, suppressed_checks)
        )
        profit_confirmed_component_parents = self._profit_confirmed_component_parents(
            details,
            suppressed_checks,
        )
        reported_total_supported_values = self._reported_total_supported_values(
            details,
            suppressed_checks,
            supported_inferred_keys,
        )
        for detail in details:
            if str(detail.get("check") or "").strip() in suppressed_checks:
                continue
            statement_type = str(detail.get("_table") or "").strip()
            if statement_type not in grouped_details:
                raise ValueError(f"不支持的勾稽表类型: {statement_type}")
            grouped_details[statement_type].extend(
                self._simplify_detail_items(
                    self._format_detail_items(
                        detail,
                        supported_inferred_keys,
                        confirmed_subtree_failure_keys,
                        confirmed_recomputed_component_attributions,
                        reported_total_supported_values,
                        profit_confirmed_component_parents,
                    )
                )
            )
        return grouped_details

    @staticmethod
    def _semantic_covered_hierarchical_checks(details: List[Dict[str, Any]]) -> set[str]:
        covered_checks: set[str] = set()
        for detail in details:
            semantic_attribution = detail.get("semantic_attribution")
            if not isinstance(semantic_attribution, dict):
                continue
            validation_chain = semantic_attribution.get("validation_chain")
            if not isinstance(validation_chain, dict):
                continue
            grandparent_check = validation_chain.get("grandparent_check")
            if not isinstance(grandparent_check, dict):
                continue
            if validation_chain.get("supports_grandparent_check") is not True:
                continue

            rule = str(grandparent_check.get("rule") or "").strip()
            period = str(detail.get("period") or "").strip()
            if rule and period:
                covered_checks.add(f"{rule}({period})")
        return covered_checks

    @staticmethod
    def _supported_missing_inferred_keys(
        details: List[Dict[str, Any]],
        suppressed_checks: set[str],
    ) -> set[tuple[str, str]]:
        candidate_keys: set[tuple[str, str]] = set()
        candidate_values: Dict[tuple[str, str], Optional[Decimal]] = {}
        directly_supported_keys: set[tuple[str, str]] = set()
        for detail in details:
            if str(detail.get("check") or "").strip() in suppressed_checks:
                continue
            attribution = detail.get("attribution")
            if not isinstance(attribution, dict):
                continue
            period = str(detail.get("period") or "").strip()
            mode = str(attribution.get("mode") or "").strip()
            if mode in {
                "missing_component_zero_inferred_match",
                "missing_component_residual_inferred_match",
            }:
                for code in attribution.get("culprit_codes", []):
                    code = str(code or "").strip()
                    if code and period:
                        directly_supported_keys.add((code, period))
                continue
            if mode == "missing_component_and_recomputed_component_match":
                for code in attribution.get("validated_missing_component_codes", []):
                    code = str(code or "").strip()
                    if code and period:
                        directly_supported_keys.add((code, period))
                continue
            if mode == "cashflow_subtotal_inferred_by_net_amount":
                code = str(
                    attribution.get("culprit_code")
                    or detail.get("_rule_total_code")
                    or ""
                ).strip()
                if code:
                    directly_supported_keys.add((code, period))
                continue
            if str(attribution.get("mode") or "").strip() != "missing_total_inferred_from_components":
                continue
            code = str(attribution.get("culprit_code") or detail.get("_rule_total_code") or "").strip()
            if code:
                key = (code, period)
                candidate_keys.add(key)
                candidate_values[key] = _parse_decimal(
                    attribution.get("candidate_sum") or detail.get("expected")
                )

        supported_keys: set[tuple[str, str]] = set()
        for code, period in candidate_keys:
            for detail in details:
                if str(detail.get("check") or "").strip() in suppressed_checks:
                    continue
                if str(detail.get("period") or "").strip() != period:
                    continue
                components = detail.get("components")
                if not isinstance(components, dict) or code not in components:
                    continue
                component = components.get(code)
                if not isinstance(component, dict):
                    continue
                if str(detail.get("result") or "").strip() == "pass":
                    attribution = detail.get("attribution")
                    mode = ""
                    culprit_codes = []
                    if isinstance(attribution, dict):
                        mode = str(attribution.get("mode") or "").strip()
                        culprit_codes = [
                            str(item)
                            for item in attribution.get("culprit_codes", [])
                        ]
                    if (
                        isinstance(attribution, dict)
                        and mode in {
                            "missing_component_inferred_match",
                            "missing_component_residual_inferred_match",
                        }
                        and code in culprit_codes
                        and component.get("reported_value") is None
                        and component.get("recomputed_value") is not None
                    ):
                        recomputed_value = _parse_decimal(component.get("recomputed_value"))
                        candidate_value = candidate_values.get((code, period))
                        if (
                            recomputed_value is None
                            or candidate_value is None
                            or abs(recomputed_value - candidate_value) <= DECIMAL_TOLERANCE
                        ):
                            supported_keys.add((code, period))
                            break

                    inferred_components = [
                        (str(component_code or "").strip(), component_item)
                        for component_code, component_item in components.items()
                        if isinstance(component_item, dict)
                        and str(component_item.get("source") or "").strip() == "inferred"
                    ]
                    if inferred_components:
                        inferred_component_codes = {
                            inferred_code
                            for inferred_code, _component in inferred_components
                        }
                        if code not in inferred_component_codes:
                            continue

                        supported_inferred_keys = []
                        all_inferred_components_match = True
                        for inferred_code, inferred_component in inferred_components:
                            inferred_key = (inferred_code, period)
                            candidate_value = candidate_values.get(inferred_key)
                            inferred_value = _parse_decimal(inferred_component.get("value"))
                            if (
                                inferred_key not in candidate_keys
                                or inferred_value is None
                                or candidate_value is None
                                or abs(inferred_value - candidate_value) > DECIMAL_TOLERANCE
                            ):
                                all_inferred_components_match = False
                                break
                            supported_inferred_keys.append(inferred_key)

                        if all_inferred_components_match:
                            supported_keys.update(supported_inferred_keys)
                            break
                if component.get("reported_value") is not None:
                    continue
                if component.get("recomputed_value") is None:
                    continue

                attribution = detail.get("attribution")
                culprit_codes = []
                if isinstance(attribution, dict):
                    culprit_codes = [str(item) for item in attribution.get("culprit_codes", [])]
                if (
                    isinstance(attribution, dict)
                    and str(attribution.get("mode") or "").strip()
                    in {
                        "missing_component_inferred_match",
                        "missing_component_residual_inferred_match",
                    }
                    and code in culprit_codes
                ):
                    supported_keys.add((code, period))
                    break

        return supported_keys | directly_supported_keys

    @staticmethod
    def _confirmed_recomputed_subtree_keys(
        details: List[Dict[str, Any]],
        suppressed_checks: set[str],
    ) -> set[tuple[str, str]]:
        confirmed_keys: set[tuple[str, str]] = set()
        for detail in details:
            if str(detail.get("check") or "").strip() in suppressed_checks:
                continue
            attribution = detail.get("attribution")
            if not isinstance(attribution, dict):
                continue
            if str(attribution.get("mode") or "").strip() != "missing_component_and_recomputed_component_match":
                continue
            period = str(detail.get("period") or "").strip()
            for code in attribution.get("culprit_codes", []):
                code = str(code or "").strip()
                if code and period:
                    confirmed_keys.add((code, period))
        return confirmed_keys

    @staticmethod
    def _confirmed_recomputed_component_attributions(
        details: List[Dict[str, Any]],
        suppressed_checks: set[str],
    ) -> Dict[tuple[str, str], Dict[str, str]]:
        confirmed: Dict[tuple[str, str], Dict[str, str]] = {}
        for detail in details:
            if str(detail.get("check") or "").strip() in suppressed_checks:
                continue
            if str(detail.get("_table") or "").strip() != "balance":
                continue
            if str(detail.get("result") or "").strip() != "fail":
                continue
            attribution = detail.get("attribution")
            if not isinstance(attribution, dict):
                continue
            mode = str(attribution.get("mode") or "").strip()
            if mode not in {
                "component_recomputed_match",
                "multiple_component_recomputed_match",
                "missing_component_and_recomputed_component_match",
            }:
                continue
            if (
                mode == "missing_component_and_recomputed_component_match"
                and str(detail.get("_rule_total_code") or "").strip() != "Z01000001"
            ):
                continue

            period = str(detail.get("period") or "").strip()
            if not period:
                continue

            parent_name = ""
            total = detail.get("total")
            if isinstance(total, dict):
                parent_name = str(total.get("name") or "").strip()
            if not parent_name:
                parent_name = str(detail.get("check") or "").split("=", 1)[0].strip()
            if not parent_name:
                parent_name = "上层合计"

            culprit_codes: List[str]
            culprit_names: List[str]
            if mode == "component_recomputed_match":
                culprit_codes = [str(attribution.get("culprit_code") or "").strip()]
                culprit_names = [str(attribution.get("culprit_name") or "").strip()]
            else:
                culprit_codes = [
                    str(code or "").strip()
                    for code in attribution.get("culprit_codes", [])
                    if str(code or "").strip()
                ]
                culprit_names = [
                    str(name or "").strip()
                    for name in attribution.get("culprit_names", [])
                    if str(name or "").strip()
                ]

            for index, code in enumerate(culprit_codes):
                if not code:
                    continue
                confirmed[(code, period)] = {
                    "code": code,
                    "name": culprit_names[index] if index < len(culprit_names) else "",
                    "parent_name": parent_name,
                    "mode": mode,
                    "reason": str(detail.get("reason") or "").strip(),
                }
        return confirmed

    @staticmethod
    def _profit_confirmed_component_parents(
        details: List[Dict[str, Any]],
        suppressed_checks: set[str],
    ) -> Dict[tuple[str, str], str]:
        confirmed: Dict[tuple[str, str], str] = {}
        for detail in details:
            if str(detail.get("check") or "").strip() in suppressed_checks:
                continue
            if str(detail.get("_table") or "").strip() != "profit":
                continue
            if str(detail.get("result") or "").strip() != "pass":
                continue

            components = detail.get("components")
            if not isinstance(components, dict):
                continue
            period = str(detail.get("period") or "").strip()
            total = detail.get("total")
            parent_name = ""
            if isinstance(total, dict):
                parent_name = str(total.get("name") or "").strip()
            if not parent_name:
                parent_name = str(detail.get("check") or "").split("=", 1)[0].strip()
            if not parent_name:
                parent_name = "上层校验"

            for code in components:
                code = str(code or "").strip()
                if code:
                    confirmed[(code, period)] = parent_name
        return confirmed

    @staticmethod
    def _reported_total_supported_values(
        details: List[Dict[str, Any]],
        suppressed_checks: set[str],
        supported_inferred_keys: Optional[set[tuple[str, str]]] = None,
    ) -> Dict[tuple[str, str], Optional[Decimal]]:
        failed_total_keys: set[tuple[str, str]] = set()
        reported_total_values: Dict[tuple[str, str], Decimal] = {}
        effectively_supported_total_keys: set[tuple[str, str]] = set()
        supported_values: Dict[tuple[str, str], Optional[Decimal]] = {}
        for detail in details:
            if str(detail.get("check") or "").strip() in suppressed_checks:
                continue
            if str(detail.get("_table") or "").strip() != "balance":
                continue

            period = str(detail.get("period") or "").strip()
            total_code = str(detail.get("_rule_total_code") or "").strip()
            total = detail.get("total")
            if not period or not total_code or not isinstance(total, dict):
                continue

            total_value = _parse_decimal(total.get("value"))
            if total_value is None:
                continue
            reported_total_values[(total_code, period)] = total_value

            if str(detail.get("result") or "").strip() != "fail":
                continue
            failed_total_keys.add((total_code, period))

            attribution = detail.get("attribution")
            if not isinstance(attribution, dict):
                continue
            mode = str(attribution.get("mode") or "").strip()
            if mode == "missing_component_and_recomputed_component_match":
                effectively_supported_total_keys.add((total_code, period))
                continue
            if mode not in {
                "missing_component_inferred_match",
                "missing_component_residual_inferred_match",
                "missing_component_zero_inferred_match",
            }:
                continue
            culprit_codes = [
                str(code or "").strip()
                for code in attribution.get("culprit_codes", [])
                if str(code or "").strip()
            ]
            if culprit_codes and all(
                (code, period) in (supported_inferred_keys or set())
                for code in culprit_codes
            ):
                effectively_supported_total_keys.add((total_code, period))
                components = detail.get("components")
                if not isinstance(components, dict):
                    continue
                for code, component in components.items():
                    code = str(code or "").strip()
                    if (
                        not code
                        or code in culprit_codes
                        or not isinstance(component, dict)
                        or component.get("reported_value") is None
                        or str(component.get("basic_result") or "").strip()
                        not in {"fail", "skip"}
                    ):
                        continue
                    supported_values[(code, period)] = _parse_decimal(
                        component.get("reported_value")
                    )
                    effectively_supported_total_keys.add((code, period))

        for detail in details:
            if str(detail.get("check") or "").strip() in suppressed_checks:
                continue
            if str(detail.get("_table") or "").strip() != "balance":
                continue
            if str(detail.get("result") or "").strip() != "pass":
                continue

            period = str(detail.get("period") or "").strip()
            components = detail.get("components")
            if not period or not isinstance(components, dict):
                continue

            for code, component in components.items():
                code = str(code or "").strip()
                if not code or not isinstance(component, dict):
                    continue
                if component.get("reported_value") is not None:
                    if str(component.get("basic_result") or "").strip() in {"fail", "skip"}:
                        supported_values[(code, period)] = _parse_decimal(
                            component.get("reported_value")
                        )
                        effectively_supported_total_keys.add((code, period))
                    continue
                if component.get("value") is None:
                    continue
                if (code, period) in failed_total_keys:
                    supported_values[(code, period)] = _parse_decimal(component.get("value"))
                    effectively_supported_total_keys.add((code, period))

        for period in {period for _code, period in reported_total_values}:
            asset_key = ("Z01000001", period)
            liability_key = ("Z02000001", period)
            equity_key = ("Z04020110", period)
            asset_total = reported_total_values.get(asset_key)
            liability_total = reported_total_values.get(liability_key)
            equity_total = reported_total_values.get(equity_key)
            if (
                asset_total is None
                or liability_total is None
                or equity_total is None
                or abs(asset_total - liability_total - equity_total) > DECIMAL_TOLERANCE
                or asset_key in failed_total_keys
            ):
                continue
            liability_failed = (
                liability_key in failed_total_keys
                and liability_key not in effectively_supported_total_keys
            )
            equity_failed = (
                equity_key in failed_total_keys
                and equity_key not in effectively_supported_total_keys
            )
            if liability_failed and not equity_failed:
                supported_values[liability_key] = liability_total
            if equity_failed and not liability_failed:
                supported_values[equity_key] = equity_total
        return supported_values

    @staticmethod
    def _join_names(names: List[str]) -> str:
        return "、".join(name for name in names if name)

    @classmethod
    def _format_detail_reason(
        cls,
        detail: Dict[str, Any],
        suspect_names: List[str],
    ) -> str:
        result = str(detail.get("result") or "").strip()
        suspects = detail.get("suspects", [])
        source = ""
        if suspects and isinstance(suspects[0], dict):
            source = str(suspects[0].get("source") or "").strip()
        verified_prefix = cls._format_verified_components_prefix(detail)

        if result == "pass":
            raw_reason = str(detail.get("reason") or "").strip()
            if "并列科目口径" in raw_reason or "单项科目口径" in raw_reason:
                return raw_reason
            if "交叉校验确认" in raw_reason:
                return raw_reason
            if raw_reason in {
                "已按canonical语义复核通过",
                "已按旧准则口径复核通过",
                "未抽取子项，未进行子项校验",
            }:
                return raw_reason
            derived = detail.get("derived", [])
            if derived:
                derived_reasons = []
                for item in derived:
                    if not isinstance(item, dict):
                        continue
                    derived_name = str(item.get("name") or "").strip()
                    basis_names = cls._join_names(
                        [
                            str(name or "").strip()
                            for name in item.get("basis_names", [])
                            if str(name or "").strip()
                        ]
                    )
                    if derived_name and basis_names:
                        derived_reasons.append(f"{derived_name}未直接识别，已按{basis_names}复核通过")
                    elif derived_name:
                        derived_reasons.append(f"{derived_name}未直接识别，已按相关科目复核通过")
                if derived_reasons:
                    return "；".join(derived_reasons)
                return "存在未直接识别科目，已按相关科目复核通过"
            return "校验通过"

        if result == "skip":
            raw_reason = str(detail.get("reason") or "").strip()
            if raw_reason == "替代轨校验已通过":
                return "已由更匹配的替代公式覆盖"
            if raw_reason == "替代轨更贴近markdown命中":
                return "已由更贴近原表命中的替代公式覆盖"
            if "原始表未解析出" in raw_reason and "合计项" in raw_reason:
                return "合计项未解析出，未参与校验"
            if "值为空" in raw_reason and "合计项" in raw_reason:
                return "合计项已匹配但值为空，未参与校验"
            if raw_reason == "组成项均未在原始表中解析出，不参与勾稽校验":
                return "组成项均未解析出，未参与校验"
            return raw_reason or "未参与校验"

        if result == "fail":
            semantic_reason = cls._format_semantic_attribution_reason(detail)
            if semantic_reason:
                return semantic_reason

            joined_names = cls._join_names(suspect_names)
            recomputed_value = cls._format_recomputed_value(detail)
            if (
                str(detail.get("_table") or "").strip() in {"profit", "cashflow"}
                and source == "missing_total_inferred_from_components"
                and recomputed_value
            ):
                missing_name = joined_names or str(detail.get("check") or "").split("=", 1)[0].strip()
                return (
                    f"{missing_name}未提取；按子项和推测值为{recomputed_value}"
                    if missing_name else
                    f"合计项未提取；按子项和推测值为{recomputed_value}"
                )
            if source == "diagnosed":
                prefix = "已定位到疑似科目" if len(suspect_names) == 1 else "已缩小到疑似科目范围"
                return f"{prefix}：{joined_names}" if joined_names else "已定位到疑似科目"
            if source == "component_range":
                return (
                    f"未定位到单一科目，当前嫌疑范围：{joined_names}"
                    if joined_names else
                    "未定位到单一科目，当前嫌疑范围较大"
                )
            if source == "excluded_range":
                return (
                    f"存在未解析科目，当前嫌疑范围：{joined_names}"
                    if joined_names else
                    "存在未解析科目，当前嫌疑范围较大"
                )
            if source == "self_total":
                return (
                    f"组成项已排除，更可能是合计项本身异常：{joined_names}"
                    if joined_names else
                    "组成项已排除，更可能是合计项本身异常"
                )
            if source == "view_participant":
                if str(detail.get("_table") or "").strip() in {"profit", "cashflow"} and recomputed_value:
                    return (
                        f"{verified_prefix}校验未通过，复算值为{recomputed_value}，参与校验科目：{joined_names}"
                        if joined_names else
                        f"{verified_prefix}校验未通过，复算值为{recomputed_value}"
                    )
                return (
                    f"{verified_prefix}校验未通过，参与校验科目：{joined_names}"
                    if joined_names else
                    f"{verified_prefix}校验未通过"
                )
            return (
                f"{verified_prefix}校验未通过，疑似科目：{joined_names}"
                if joined_names else
                f"{verified_prefix}校验未通过"
            )

        return ""

    @classmethod
    def _format_verified_components_prefix(cls, detail: Dict[str, Any]) -> str:
        verified_names = [
            str(component.get("name") or "").strip()
            for component in detail.get("verified_components", [])
            if isinstance(component, dict) and str(component.get("name") or "").strip()
        ]
        joined_names = cls._join_names(verified_names)
        return f"已排除：{joined_names}；" if joined_names else ""

    @staticmethod
    def _format_recomputed_value(detail: Dict[str, Any]) -> str:
        value = detail.get("expected")
        if value in (None, ""):
            amounts = detail.get("amounts")
            if isinstance(amounts, dict):
                value = amounts.get("recomputed_total")
        return str(value).strip() if value not in (None, "") else ""

    @classmethod
    def _format_semantic_attribution_reason(cls, detail: Dict[str, Any]) -> str:
        semantic_attribution = detail.get("semantic_attribution")
        if not isinstance(semantic_attribution, dict):
            return ""

        mode = str(semantic_attribution.get("mode") or "").strip()
        if mode == "cashflow_subtotal_confirmed_by_net_amount":
            subtotal_name = str(semantic_attribution.get("subtotal_name") or "现金流小计").strip()
            confirmation_name = str(semantic_attribution.get("confirmation_name") or "上层净额").strip()
            component_diff = str(semantic_attribution.get("component_diff") or "").strip()
            parts = [f"已由{confirmation_name}交叉确认{subtotal_name}正确，差异范围缩小到{subtotal_name}子项"]
            if component_diff:
                parts.append(f"{subtotal_name}子项合计相差{component_diff}")
            return "；".join(parts)

        if mode == "supporting_subtotal_match":
            subtotal_name = str(semantic_attribution.get("subtotal_name") or "独立合计").strip()
            component_diff = str(semantic_attribution.get("component_diff") or "").strip()
            candidate_text = cls._format_repair_candidates(
                semantic_attribution.get("repair_candidates")
            )
            parts = [f"按{subtotal_name}独立合计复核通过，差异范围缩小到{subtotal_name}明细，无法单点定位"]
            if component_diff:
                parts.append(f"{subtotal_name}明细相差{component_diff}")
            if candidate_text:
                parts.append(f"若只改一个字段，可闭合候选：{candidate_text}")
            return "；".join(parts)

        if mode == "semantic_single_field_match":
            culprit_name = str(semantic_attribution.get("culprit_name") or "").strip()
            current_value = str(semantic_attribution.get("current_value") or "").strip()
            validated_value = str(semantic_attribution.get("validated_value") or "").strip()
            if not culprit_name:
                return ""
            if current_value and validated_value:
                return f"使用canonical值复核通过，疑似{culprit_name}字段识别错误：{current_value}→{validated_value}"
            return f"使用canonical值复核通过，疑似{culprit_name}字段识别错误"

        culprit_name = str(semantic_attribution.get("culprit_name") or "").strip()
        inferred_value = str(semantic_attribution.get("inferred_value") or "").strip()
        missing_total_name = str(semantic_attribution.get("missing_total_name") or "").strip()
        if not culprit_name:
            return ""

        check_item = str(detail.get("check") or "").strip()
        parent_name = check_item.split("(", 1)[0] if check_item else "当前合计项"
        parts = [f"进一步校验发现{culprit_name}内部公式可推得正确值"]
        if inferred_value:
            parts[0] = f"{parts[0]}为{inferred_value}"

        validation_chain = semantic_attribution.get("validation_chain")
        if isinstance(validation_chain, dict):
            parent_supported = validation_chain.get("supports_parent_check")
            if parent_supported is True:
                parts.append(f"用该值替换后，{parent_name}校验通过")
            elif parent_supported is False:
                parts.append(f"用该值替换后，{parent_name}仍未通过")
            elif missing_total_name:
                parts.append(f"{missing_total_name}未提取，无法直接校验该合计项")

            grandparent_supported = validation_chain.get("supports_grandparent_check")
            if grandparent_supported is True:
                grandparent_check = validation_chain.get("grandparent_check")
                grandparent_rule = ""
                if isinstance(grandparent_check, dict):
                    grandparent_rule = str(grandparent_check.get("rule") or "").strip()
                grandparent_name = grandparent_rule.split("=", 1)[0].strip() or "更上层关系"
                parts.append(f"{grandparent_name}校验也恢复正常")
            elif grandparent_supported is False:
                parts.append("更上层关系仍未恢复")
            elif grandparent_supported is None and "supports_grandparent_check" in validation_chain:
                parts.append("由于缺少上层必要科目，无法继续验证更上层关系")

        if missing_total_name:
            parts.append(f"疑似{culprit_name}字段识别错误，且{missing_total_name}未提取")
        else:
            parts.append(f"疑似{culprit_name}字段识别错误")
        return "；".join(parts)

    @classmethod
    def _format_repair_candidates(cls, candidates: Any) -> str:
        if not isinstance(candidates, list):
            return ""

        formatted = []
        for candidate in candidates[:6]:
            if not isinstance(candidate, dict):
                continue
            name = str(candidate.get("name") or candidate.get("code") or "").strip()
            current_value = str(candidate.get("current_value") or "").strip()
            corrected_value = str(candidate.get("corrected_value") or "").strip()
            if not name:
                continue
            if current_value and corrected_value:
                formatted.append(f"{name}{current_value}→{corrected_value}")
            else:
                formatted.append(name)
        if len(candidates) > 6 and formatted:
            formatted.append("等")
        return cls._join_names(formatted)

    def _format_detail_items(
        self,
        detail: Dict[str, Any],
        supported_inferred_keys: Optional[set[tuple[str, str]]] = None,
        confirmed_subtree_failure_keys: Optional[set[tuple[str, str]]] = None,
        confirmed_recomputed_component_attributions: Optional[Dict[tuple[str, str], Dict[str, str]]] = None,
        reported_total_supported_values: Optional[Dict[tuple[str, str], Optional[Decimal]]] = None,
        profit_confirmed_component_parents: Optional[Dict[tuple[str, str], str]] = None,
    ) -> List[Dict[str, Any]]:
        verified_items = [
            *self._format_verified_component_items(detail),
            *self._format_validated_component_items(detail),
        ]
        invalid_items = self._format_invalid_component_items(detail)

        reported_total_supported_items = self._format_reported_total_supported_items(
            detail,
            reported_total_supported_values,
            confirmed_recomputed_component_attributions,
        )
        if reported_total_supported_items:
            return [*verified_items, *invalid_items, *reported_total_supported_items]

        component_breakdown_items = self._format_component_breakdown_items(detail)
        if component_breakdown_items:
            return [*verified_items, *invalid_items, *component_breakdown_items]

        confirmed_component_items = self._format_confirmed_recomputed_component_items(
            detail,
            confirmed_recomputed_component_attributions,
        )
        if confirmed_component_items:
            return [*verified_items, *invalid_items, *confirmed_component_items]

        confirmed_subtree_items = self._format_confirmed_balance_subtree_mismatch_items(
            detail,
            confirmed_subtree_failure_keys,
        )
        if confirmed_subtree_items:
            return [*verified_items, *invalid_items, *confirmed_subtree_items]

        optional_absent_items = self._format_optional_absent_component_items(detail)
        if optional_absent_items:
            parent_detail = dict(detail)
            parent_detail["reason"] = "校验通过"
            return [*verified_items, *invalid_items, self._format_detail(parent_detail), *optional_absent_items]

        supported_missing_total_items = self._format_supported_missing_total_without_components_detail(
            detail,
            supported_inferred_keys,
        )
        if supported_missing_total_items:
            return [*verified_items, *invalid_items, *supported_missing_total_items]

        attribution = detail.get("attribution")
        if isinstance(attribution, dict):
            mode = str(attribution.get("mode") or "").strip()
            if mode == "missing_total_inferred_from_components":
                inferred_component_items = self._format_supported_inferred_component_items(
                    detail,
                    attribution,
                    supported_inferred_keys,
                )
                residual_component_mismatch_items = (
                    self._format_parent_residual_component_mismatch_items(detail, attribution)
                )
                if str(detail.get("_table") or "").strip() != "balance":
                    raw_period = str(detail.get("period") or "").strip()
                    culprit_code = str(
                        attribution.get("culprit_code") or detail.get("_rule_total_code") or ""
                    ).strip()
                    if culprit_code and (culprit_code, raw_period) in (supported_inferred_keys or set()):
                        return [
                            *verified_items,
                            *invalid_items,
                            *inferred_component_items,
                            *residual_component_mismatch_items,
                            self._format_supported_missing_total_inference_detail(detail, attribution),
                        ]
                    if self._should_display_unvalidated_missing_total_inference(detail, attribution):
                        return [
                            *verified_items,
                            *invalid_items,
                            *inferred_component_items,
                            *residual_component_mismatch_items,
                            self._format_missing_total_inference_detail(
                                detail,
                                attribution,
                                display_inferred_value=True,
                            ),
                        ]
                    return [
                        *verified_items,
                        *invalid_items,
                        *inferred_component_items,
                        *residual_component_mismatch_items,
                        self._format_detail(detail),
                    ]
                raw_period = str(detail.get("period") or "").strip()
                culprit_code = str(attribution.get("culprit_code") or detail.get("_rule_total_code") or "").strip()
                if culprit_code and (culprit_code, raw_period) in (supported_inferred_keys or set()):
                    return [
                        *verified_items,
                        *invalid_items,
                        *inferred_component_items,
                        *residual_component_mismatch_items,
                        self._format_supported_missing_total_inference_detail(detail, attribution),
                    ]
                return [
                    *verified_items,
                    *invalid_items,
                    *inferred_component_items,
                    *residual_component_mismatch_items,
                    self._format_missing_total_inference_detail(detail, attribution),
                ]
            if mode in {
                "missing_component_inferred_match",
                "missing_component_residual_inferred_match",
            }:
                period = str(detail.get("period") or "").strip()
                culprit_codes = [str(item) for item in attribution.get("culprit_codes", [])]
                if not all((code, period) in (supported_inferred_keys or set()) for code in culprit_codes):
                    return [*verified_items, *invalid_items, self._format_detail(detail)]
                return [*verified_items, *invalid_items, self._format_missing_component_parent_check_detail(detail, attribution)]
            if mode == "missing_component_zero_inferred_match":
                period = str(detail.get("period") or "").strip()
                culprit_codes = [str(item) for item in attribution.get("culprit_codes", [])]
                if not all((code, period) in (supported_inferred_keys or set()) for code in culprit_codes):
                    return [*verified_items, *invalid_items, self._format_detail(detail)]
                zero_component_items = (
                    self._format_zero_inferred_component_items(detail, attribution)
                    if str(detail.get("result") or "").strip() == "pass" else
                    []
                )
                return [
                    *verified_items,
                    *invalid_items,
                    *zero_component_items,
                    self._format_missing_component_parent_check_detail(detail, attribution),
                ]
            if mode == "missing_component_and_recomputed_component_match":
                return [
                    *verified_items,
                    *invalid_items,
                    self._format_mixed_hierarchical_parent_check_detail(detail, attribution),
                ]

        cashflow_parent_detail = self._format_cashflow_inferred_parent_check_detail(
            detail,
            supported_inferred_keys,
        )
        if cashflow_parent_detail:
            return [*verified_items, *invalid_items, cashflow_parent_detail]

        semantic_attribution = detail.get("semantic_attribution")
        if not isinstance(semantic_attribution, dict):
            profit_component_items = self._format_profit_confirmed_component_mismatch_items(
                detail,
                profit_confirmed_component_parents,
            )
            if profit_component_items:
                return [*verified_items, *invalid_items, *profit_component_items]
            return [*verified_items, *invalid_items, self._format_detail(detail)]

        mode = str(semantic_attribution.get("mode") or "").strip()
        if mode == "cashflow_subtotal_confirmed_by_net_amount":
            return [
                *verified_items,
                *invalid_items,
                *self._format_cashflow_confirmed_subtotal_items(
                    detail,
                    semantic_attribution,
                ),
            ]

        if mode == "cashflow_subtotal_inferred_by_net_amount":
            return [
                *verified_items,
                *invalid_items,
                self._format_cashflow_inferred_subtotal_item(
                    detail,
                    semantic_attribution,
                ),
            ]

        if mode == "supporting_subtotal_match":
            return [
                *verified_items,
                *invalid_items,
                *self._format_supporting_subtotal_attribution_items(
                    detail,
                    semantic_attribution,
                ),
            ]

        if mode not in {
            "semantic_component_inference_match",
            "semantic_component_inference_with_missing_parent",
        }:
            return [*verified_items, *invalid_items, self._format_detail(detail)]

        period = self._format_detail_period(detail)
        culprit_code = str(semantic_attribution.get("culprit_code") or "").strip()
        culprit_name = str(semantic_attribution.get("culprit_name") or "").strip()
        inferred_value = str(semantic_attribution.get("inferred_value") or "").strip()
        candidate_sum = str(semantic_attribution.get("candidate_sum") or "").strip()
        missing_total_code = str(semantic_attribution.get("missing_total_code") or "").strip()
        missing_total_name = str(semantic_attribution.get("missing_total_name") or "").strip()
        validation_chain = semantic_attribution.get("validation_chain")
        candidate_sum_is_validated = (
            candidate_sum
            and missing_total_name
            and isinstance(validation_chain, dict)
            and validation_chain.get("supports_grandparent_check") is True
        )

        items: List[Dict[str, Any]] = []
        if culprit_code or culprit_name:
            reason = (
                f"{culprit_name}内部公式推得正确值为{inferred_value}，当前识别值可能有误"
                if inferred_value else
                f"{culprit_name}内部公式校验异常，当前识别值可能有误"
            )
            items.append(
                {
                    "check_item": self._format_check_item_for_row(culprit_name, period),
                    "status": detail.get("result"),
                    "period": period,
                    "suspects": [{"code": culprit_code, "name": culprit_name}],
                    "reason": reason,
                }
            )

        parent_check = str(detail.get("check") or "").strip()
        parent_name = parent_check.split("(", 1)[0] if parent_check else missing_total_name
        parent_code = missing_total_code or str(detail.get("_rule_total_code") or "").strip()
        if parent_name or parent_code:
            if missing_total_name:
                reason = (
                    f"{missing_total_name}未提取；按子项和推测值为{candidate_sum}"
                    if candidate_sum else
                    f"{missing_total_name}未提取"
                )
            else:
                reason = (
                    f"用{culprit_name}推测值替换后，{parent_name}校验通过；"
                    f"{parent_name}推测值为{candidate_sum}"
                    if candidate_sum else
                    f"用{culprit_name}推测值替换后，{parent_name}校验通过"
                )
            items.append(
                {
                    "check_item": self._format_check_item_for_row(parent_name, period),
                    "status": detail.get("result"),
                    "period": period,
                    "suspects": [{"code": parent_code, "name": parent_name}],
                    "reason": reason,
                    **(
                        {"_validated_inferred_value": candidate_sum}
                        if candidate_sum_is_validated else
                        {}
                    ),
                }
            )

        grandparent_check = validation_chain.get("grandparent_check") if isinstance(validation_chain, dict) else None
        if isinstance(grandparent_check, dict):
            grandparent_rule = str(grandparent_check.get("rule") or "").strip()
            grandparent_name = grandparent_rule.split("=", 1)[0].strip()
            grandparent_supported = validation_chain.get("supports_grandparent_check")
            grandparent_value = str(grandparent_check.get("recomputed_total_after_repair") or "").strip()
            if grandparent_name and grandparent_supported is not None:
                status = "pass" if grandparent_supported else "fail"
                reason = (
                    f"使用推测的{parent_name}值{candidate_sum}后，{grandparent_name}校验通过"
                    if grandparent_supported else
                    f"使用推测的{parent_name}值{candidate_sum}后，{grandparent_name}仍未通过"
                )
                if grandparent_value:
                    reason = f"{reason}，复算值为{grandparent_value}"
                items.append(
                    {
                        "check_item": self._format_check_item_for_row(grandparent_name, period),
                        "status": status,
                        "period": period,
                        "suspects": [{"code": "Z01000001", "name": grandparent_name}],
                        "reason": reason,
                    }
                )

        return [*verified_items, *invalid_items, *(items or [self._format_detail(detail)])]

    def _format_cashflow_inferred_subtotal_item(
        self,
        detail: Dict[str, Any],
        semantic_attribution: Dict[str, Any],
    ) -> Dict[str, Any]:
        period = self._format_detail_period(detail)
        subtotal_code = str(
            semantic_attribution.get("culprit_code")
            or semantic_attribution.get("subtotal_code")
            or ""
        ).strip()
        subtotal_name = str(
            semantic_attribution.get("culprit_name")
            or semantic_attribution.get("subtotal_name")
            or detail.get("check")
            or ""
        ).strip()
        inferred_value = str(semantic_attribution.get("inferred_value") or "").strip()
        confirmation_name = str(
            semantic_attribution.get("confirmation_name") or "上层净额"
        ).strip()
        reason = (
            f"{confirmation_name}交叉校验支持按子项和推测的{subtotal_name}值，"
            f"当前识别值可能有误"
        )
        if inferred_value:
            reason = f"{reason}，推测值为{inferred_value}"
        return {
            "check_item": self._format_check_item_for_row(subtotal_name, period),
            "status": detail.get("result"),
            "period": period,
            "suspects": [{"code": subtotal_code, "name": subtotal_name}],
            "reason": reason,
            **(
                {"_validated_suspected_value": inferred_value}
                if inferred_value else
                {}
            ),
        }

    def _format_cashflow_confirmed_subtotal_items(
        self,
        detail: Dict[str, Any],
        semantic_attribution: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        period = self._format_detail_period(detail)
        subtotal_code = str(semantic_attribution.get("subtotal_code") or "").strip()
        subtotal_name = str(semantic_attribution.get("subtotal_name") or detail.get("check") or "").strip()
        confirmation_name = str(semantic_attribution.get("confirmation_name") or "上层净额").strip()
        component_diff = str(semantic_attribution.get("component_diff") or "").strip()

        items: List[Dict[str, Any]] = []
        if subtotal_code or subtotal_name:
            items.append(
                {
                    "check_item": self._format_check_item_for_row(subtotal_name, period),
                    "status": "pass",
                    "period": period,
                    "suspects": [],
                    "reason": f"已由{confirmation_name}交叉校验确认正确",
                }
            )

        component_suspects = semantic_attribution.get("component_suspects")
        if not isinstance(component_suspects, list):
            component_suspects = detail.get("suspects", [])

        for component in component_suspects:
            if not isinstance(component, dict):
                continue
            code = str(component.get("code") or "").strip()
            name = str(component.get("name") or code).strip()
            if not code and not name:
                continue
            reason = f"{subtotal_name}子项合计与小计不一致，需复核"
            if component_diff:
                reason = f"{reason}，差异{component_diff}"
            items.append(
                {
                    "check_item": self._format_check_item_for_row(name, period),
                    "status": detail.get("result"),
                    "period": period,
                    "suspects": [{"code": code, "name": name}],
                    "reason": reason,
                }
            )

        return items or [self._format_detail(detail)]

    def _format_profit_confirmed_component_mismatch_items(
        self,
        detail: Dict[str, Any],
        profit_confirmed_component_parents: Optional[Dict[tuple[str, str], str]],
    ) -> List[Dict[str, Any]]:
        if str(detail.get("_table") or "").strip() != "profit":
            return []
        if str(detail.get("result") or "").strip() != "fail":
            return []

        total = detail.get("total")
        if not isinstance(total, dict):
            return []
        total_code = str(total.get("code") or "").strip()
        total_name = str(total.get("name") or detail.get("check") or "").strip()
        raw_period = str(detail.get("period") or "").strip()
        confirming_name = (profit_confirmed_component_parents or {}).get((total_code, raw_period), "")
        if not total_code or not confirming_name:
            return []

        components = detail.get("components")
        if not isinstance(components, dict):
            return []

        period = self._format_detail_period(detail)
        recomputed_value = self._format_recomputed_value(detail)
        reason_prefix = (
            f"{confirming_name}校验已确认{total_name}提取值本身未发现异常；"
            f"{total_name}按参与项复算不通过"
        )
        if recomputed_value:
            reason_prefix = f"{reason_prefix}，复算值为{recomputed_value}"

        items: List[Dict[str, Any]] = [
            {
                "check_item": self._format_check_item_for_row(total_name, period),
                "status": "pass",
                "period": period,
                "suspects": [{"code": total_code, "name": total_name}],
                "reason": f"已由{confirming_name}校验确认{total_name}提取值本身未发现异常",
            }
        ]
        for code, component in components.items():
            if not isinstance(component, dict):
                continue
            code = str(code or "").strip()
            name = str(component.get("name") or code).strip()
            if not code and not name:
                continue
            items.append(
                {
                    "check_item": self._format_check_item_for_row(name, period),
                    "status": "fail",
                    "period": period,
                    "suspects": [{"code": code, "name": name}],
                    "reason": f"{reason_prefix}，需核对该参与项",
                }
            )
        return items

    def _format_cashflow_inferred_parent_check_detail(
        self,
        detail: Dict[str, Any],
        supported_inferred_keys: Optional[set[tuple[str, str]]],
    ) -> Optional[Dict[str, Any]]:
        if str(detail.get("_table") or "").strip() != "cashflow":
            return None
        if str(detail.get("result") or "").strip() != "pass":
            return None

        components = detail.get("components")
        if not isinstance(components, dict):
            return None

        raw_period = str(detail.get("period") or "").strip()
        inferred_components = [
            (str(code or "").strip(), component)
            for code, component in components.items()
            if isinstance(component, dict)
            and str(component.get("source") or "").strip() == "inferred"
            and (str(code or "").strip(), raw_period) in (supported_inferred_keys or set())
        ]
        if not inferred_components:
            return None

        inferred_names = [
            str(component.get("name") or code).strip()
            for code, component in inferred_components
        ]
        inferred_name = self._join_names(inferred_names)
        if not inferred_name:
            return None

        period = self._format_detail_period(detail)
        total = detail.get("total")
        parent_code = str(detail.get("_rule_total_code") or "").strip()
        parent_name = str(detail.get("check") or "").split("=", 1)[0].strip()
        if isinstance(total, dict):
            parent_code = str(total.get("code") or parent_code).strip()
            parent_name = str(total.get("name") or parent_name).strip()
        if not parent_name:
            parent_name = "上层净额"

        recomputed_value = ""
        amounts = detail.get("amounts")
        if isinstance(amounts, dict):
            recomputed_value = str(amounts.get("recomputed_total") or "").strip()
        if not recomputed_value:
            recomputed_value = str(detail.get("expected") or "").strip()

        reason = f"使用推测的{inferred_name}值后，{parent_name}校验通过"
        if recomputed_value:
            reason = f"{reason}，复算值为{recomputed_value}"

        formatted: Dict[str, Any] = {
            "check_item": self._format_check_item_for_row(parent_name, period),
            "status": "pass",
            "period": period,
            "suspects": [{"code": parent_code, "name": parent_name}],
            "reason": reason,
        }
        validated_components: List[Dict[str, str]] = []
        validated_component_codes: set[str] = set()
        for inferred_code, _inferred_component in inferred_components:
            for item in self._cashflow_basic_rule_component_items(inferred_code):
                code = str(item.get("code") or "").strip()
                if code and code in validated_component_codes:
                    continue
                if code:
                    validated_component_codes.add(code)
                validated_components.append(item)
        if validated_components:
            formatted["validated_components"] = validated_components
        return formatted

    @staticmethod
    def _cashflow_basic_rule_component_items(total_code: str) -> List[Dict[str, str]]:
        for rule in CASHFLOW_BASIC_RULES:
            if str(rule.get("total_code") or "").strip() != total_code:
                continue
            items: List[Dict[str, str]] = []
            for component in rule.get("components", []):
                if not isinstance(component, tuple):
                    continue
                if len(component) == 3 and component[0] in {"+", "-"}:
                    _sign, code, name = component
                elif len(component) == 2:
                    code, name = component
                else:
                    continue
                code = str(code or "").strip()
                name = str(name or code).strip()
                if code or name:
                    items.append({"code": code, "name": name})
            return items
        return []

    def _format_supporting_subtotal_attribution_items(
        self,
        detail: Dict[str, Any],
        semantic_attribution: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        period = self._format_detail_period(detail)
        subtotal_name = str(semantic_attribution.get("subtotal_name") or "独立合计").strip()
        component_diff = str(semantic_attribution.get("component_diff") or "").strip()

        suspect_codes = {
            str(suspect.get("code") or "").strip()
            for suspect in detail.get("suspects", [])
            if isinstance(suspect, dict) and str(suspect.get("code") or "").strip()
        }
        suspect_codes.update(
            str(candidate.get("code") or "").strip()
            for candidate in semantic_attribution.get("repair_candidates", [])
            if isinstance(candidate, dict) and str(candidate.get("code") or "").strip()
        )

        items: List[Dict[str, Any]] = []
        total = detail.get("total")
        if isinstance(total, dict):
            total_code = str(total.get("code") or "").strip()
            total_name = str(total.get("name") or detail.get("check") or "").strip()
            if total_code or total_name:
                items.append(
                    {
                        "check_item": self._format_check_item_for_row(total_name, period),
                        "status": "pass",
                        "period": period,
                        "suspects": [],
                        "reason": f"按{subtotal_name}独立合计复核通过",
                    }
                )

        components = detail.get("components")
        if not isinstance(components, dict):
            return items or [self._format_detail(detail)]

        for code, component in components.items():
            if not isinstance(component, dict):
                continue
            code = str(code or "").strip()
            name = str(component.get("name") or code).strip()
            if not code and not name:
                continue

            if code in suspect_codes:
                reason = f"{subtotal_name}明细差异范围内，需复核"
                if component_diff:
                    reason = f"{reason}，{subtotal_name}明细相差{component_diff}"
                items.append(
                    {
                        "check_item": self._format_check_item_for_row(name, period),
                        "status": detail.get("result"),
                        "period": period,
                        "suspects": [{"code": code, "name": name}],
                        "reason": reason,
                    }
                )
                continue

            items.append(
                {
                    "check_item": self._format_check_item_for_row(name, period),
                    "status": "pass",
                    "period": period,
                    "suspects": [],
                    "reason": f"已通过{subtotal_name}交叉校验排除",
                }
            )

        return items or [self._format_detail(detail)]

    def _format_component_breakdown_items(
        self,
        detail: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        display_on_components = bool(detail.get("_display_on_components"))
        display_fail_on_components = bool(detail.get("_display_fail_on_components"))
        if not display_on_components and not display_fail_on_components:
            return []
        status = str(detail.get("result") or "").strip()
        if display_fail_on_components and status != "fail":
            return []
        if status == "fail" and not isinstance(detail.get("total"), dict):
            return []

        parallel_validation = detail.get("parallel_validation")
        if isinstance(parallel_validation, dict):
            mode = str(parallel_validation.get("mode") or "").strip()
            if mode == "single_component_match":
                return self._format_single_track_breakdown_items(
                    detail,
                    parallel_validation,
                )
            if mode == "parallel_components_match":
                return self._format_parallel_breakdown_component_items(
                    detail,
                    parallel_validation,
                )

        components = detail.get("components")
        if not isinstance(components, dict):
            return []

        parent_check = str(detail.get("check") or "").strip()
        parent_name = parent_check.split("(", 1)[0] if parent_check else "父项"
        period = self._format_detail_period(detail)

        items: List[Dict[str, Any]] = []
        for code, component in components.items():
            if not isinstance(component, dict):
                continue
            name = str(component.get("name") or code or "").strip()
            if not name:
                continue
            raw_reason = str(detail.get("reason") or "").strip()
            reason = (
                raw_reason
                if status == "pass" and "并列科目口径" in raw_reason
                else f"{parent_name}子项校验通过"
                if status == "pass"
                else f"参与{parent_name}勾稽出错，当前识别值可能有误"
            )
            items.append(
                {
                    "check_item": self._format_check_item_for_row(name, period),
                    "status": detail.get("result"),
                    "period": period,
                    "suspects": [{"code": str(code), "name": name}],
                    "reason": reason,
                }
            )
        return items

    def _format_parent_residual_component_mismatch_items(
        self,
        detail: Dict[str, Any],
        attribution: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        if str(detail.get("_table") or "").strip() != "balance":
            return []
        if str(detail.get("result") or "").strip() != "fail":
            return []
        if str(attribution.get("mode") or "").strip() != "missing_total_inferred_from_components":
            return []
        if str(attribution.get("inference_source") or "").strip() != "parent_residual":
            return []

        candidate_sum_text = str(
            attribution.get("candidate_sum")
            or detail.get("_inferred_total")
            or detail.get("expected")
            or ""
        ).strip()
        component_sum_text = str(attribution.get("component_sum") or "").strip()
        candidate_sum = _parse_decimal(candidate_sum_text)
        component_sum = _parse_decimal(component_sum_text)
        if (
            candidate_sum is None
            or component_sum is None
            or abs(candidate_sum - component_sum) <= DECIMAL_TOLERANCE
        ):
            return []

        components = detail.get("components")
        if not isinstance(components, dict):
            return []

        period = self._format_detail_period(detail)
        total_name = str(attribution.get("culprit_name") or "").strip()
        if not total_name:
            total_name = str(detail.get("check") or "").split("(", 1)[0].strip() or "当前合计项"
        diff_text = str(attribution.get("diff") or abs(candidate_sum - component_sum)).strip()
        reason = (
            f"{total_name}上层推测值为{candidate_sum_text or candidate_sum}，"
            f"子项和为{component_sum_text or component_sum}，差额{diff_text}，"
            "子项和不匹配"
        )

        items: List[Dict[str, Any]] = []
        for code, component in components.items():
            if not isinstance(component, dict):
                continue
            code = str(code or "").strip()
            name = str(component.get("name") or code).strip()
            if not code and not name:
                continue
            items.append(
                {
                    "check_item": self._format_check_item_for_row(name, period),
                    "status": "fail",
                    "period": period,
                    "suspects": [{"code": code, "name": name}],
                    "reason": reason,
                }
            )

        return items

    def _format_single_track_breakdown_items(
        self,
        detail: Dict[str, Any],
        parallel_validation: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        period = self._format_detail_period(detail)
        parent_name = str(parallel_validation.get("parent_total_name") or "").strip()
        reason = (
            f"已按{parent_name}单项科目口径复核通过，未发现异常"
            if parent_name else
            "已按单项科目口径复核通过，未发现异常"
        )
        return self._format_track_member_items(
            period=period,
            reason=reason,
            aggregate_code=str(parallel_validation.get("aggregate_code") or "").strip(),
            aggregate_name=str(parallel_validation.get("aggregate_name") or "").strip(),
            component_codes=parallel_validation.get("component_codes", []),
            component_names=parallel_validation.get("component_names", []),
        )

    def _format_parallel_breakdown_component_items(
        self,
        detail: Dict[str, Any],
        parallel_validation: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        period = self._format_detail_period(detail)
        parent_name = str(parallel_validation.get("parent_total_name") or "").strip()
        reason = (
            f"已按{parent_name}并列科目口径复核通过"
            if parent_name else
            "已按并列科目口径复核通过"
        )
        return self._format_track_member_items(
            period=period,
            reason=reason,
            aggregate_code=str(parallel_validation.get("aggregate_code") or "").strip(),
            aggregate_name=str(parallel_validation.get("aggregate_name") or "").strip(),
            component_codes=parallel_validation.get("component_codes", []),
            component_names=parallel_validation.get("component_names", []),
        )

    def _format_track_member_items(
        self,
        *,
        period: str,
        reason: str,
        aggregate_code: str,
        aggregate_name: str,
        component_codes: Any,
        component_names: Any,
    ) -> List[Dict[str, Any]]:
        members: List[tuple[str, str]] = []
        if aggregate_code or aggregate_name:
            members.append((aggregate_code, aggregate_name))
        normalized_component_codes = [
            str(code or "").strip()
            for code in component_codes
        ]
        normalized_component_names = [
            str(name or "").strip()
            for name in component_names
        ]
        members.extend(
            (
                code,
                normalized_component_names[index]
                if index < len(normalized_component_names)
                else code,
            )
            for index, code in enumerate(normalized_component_codes)
        )

        items: List[Dict[str, Any]] = []
        for code, name in members:
            if not code and not name:
                continue
            items.append(
                {
                    "check_item": self._format_check_item_for_row(name, period),
                    "status": "pass",
                    "period": period,
                    "suspects": [{"code": code, "name": name}],
                    "reason": reason,
                }
            )
        return items

    def _format_reported_total_supported_items(
        self,
        detail: Dict[str, Any],
        reported_total_supported_values: Optional[Dict[tuple[str, str], Optional[Decimal]]],
        confirmed_recomputed_component_attributions: Optional[Dict[tuple[str, str], Dict[str, str]]] = None,
    ) -> List[Dict[str, Any]]:
        if str(detail.get("_table") or "").strip() != "balance":
            return []
        status = str(detail.get("result") or "").strip()
        if status not in {"fail", "skip"}:
            return []
        attribution = detail.get("attribution")
        if isinstance(attribution, dict) and str(attribution.get("mode") or "").strip() in {
            "missing_component_inferred_match",
            "missing_component_residual_inferred_match",
            "missing_component_zero_inferred_match",
            "missing_component_and_recomputed_component_match",
        }:
            return []

        raw_period = str(detail.get("period") or "").strip()
        total_code = str(detail.get("_rule_total_code") or "").strip()
        supported_value_map = reported_total_supported_values or {}
        supported_key = (total_code, raw_period)
        if not total_code or supported_key not in supported_value_map:
            return []
        supported_total_value = supported_value_map.get(supported_key)

        total = detail.get("total")
        total_name = ""
        if isinstance(total, dict):
            total_name = str(total.get("name") or "").strip()
        if not total_name:
            total_name = str(detail.get("check") or "").split("(", 1)[0].strip()

        period = self._format_detail_period(detail)
        items: List[Dict[str, Any]] = []
        if total_name or total_code:
            total_item = {
                "check_item": self._format_check_item_for_row(total_name, period),
                "status": "pass",
                "period": period,
                "suspects": [{"code": total_code, "name": total_name}],
                "reason": f"{total_name}通过上层勾稽验证，合计值本身未发现异常",
            }
            if (
                status == "skip"
                and supported_total_value is not None
                and abs(supported_total_value) <= DECIMAL_TOLERANCE
            ):
                validated_components = self._balance_validated_component_items_for_total(total_code)
                if validated_components:
                    total_item["validated_components"] = validated_components
                return [total_item]
            items.append(total_item)

        attribution = detail.get("attribution")
        if isinstance(attribution, dict) and str(attribution.get("mode") or "").strip() in {
            "component_recomputed_match",
            "multiple_component_recomputed_match",
        }:
            culprit_codes = [
                str(code or "").strip()
                for code in (
                    [attribution.get("culprit_code")]
                    if str(attribution.get("mode") or "").strip() == "component_recomputed_match"
                    else attribution.get("culprit_codes", [])
                )
                if str(code or "").strip()
            ]
            culprit_keys = {(code, raw_period) for code in culprit_codes}
            if culprit_keys and all(
                key in (confirmed_recomputed_component_attributions or {})
                for key in culprit_keys
            ):
                return items

        components = detail.get("components")
        if not isinstance(components, dict):
            return items
        component_items = [
            {
                "code": str(code or "").strip(),
                "name": str(component.get("name") or code).strip(),
            }
            for code, component in components.items()
            if isinstance(component, dict)
        ]
        if not component_items and status == "skip":
            component_items = self._balance_basic_rule_component_items(total_code)

        if status == "skip":
            reason = (
                f"{total_name or '当前合计项'}缺少足够明细参与校验；"
                "上层校验已确认合计值本身未发现异常"
            )
        else:
            reason = f"参与{total_name or '当前合计项'}勾稽出错，当前识别值可能有误"
        for component_item in component_items:
            code = component_item["code"]
            name = component_item["name"]
            if not code and not name:
                continue
            items.append(
                {
                    "check_item": self._format_check_item_for_row(name, period),
                    "status": "fail",
                    "period": period,
                    "suspects": [{"code": code, "name": name}],
                    "reason": reason,
                }
            )

        return items

    def _format_confirmed_recomputed_component_items(
        self,
        detail: Dict[str, Any],
        confirmed_recomputed_component_attributions: Optional[Dict[tuple[str, str], Dict[str, str]]],
    ) -> List[Dict[str, Any]]:
        if str(detail.get("_table") or "").strip() != "balance":
            return []
        if str(detail.get("result") or "").strip() != "fail":
            return []

        raw_period = str(detail.get("period") or "").strip()
        total_code = str(detail.get("_rule_total_code") or "").strip()
        attribution = (confirmed_recomputed_component_attributions or {}).get(
            (total_code, raw_period)
        )
        if not attribution:
            return []

        total = detail.get("total")
        total_name = ""
        if isinstance(total, dict):
            total_name = str(total.get("name") or "").strip()
        if not total_name:
            total_name = (
                str(attribution.get("name") or "").strip()
                or str(detail.get("check") or "").split("(", 1)[0].strip()
            )

        period = self._format_detail_period(detail)
        component_diff = self._format_component_diff(detail)
        diff_suffix = f"，差异{component_diff}" if component_diff else ""
        parent_name = str(attribution.get("parent_name") or "上层合计").strip()
        reason = (
            f"{total_name}与子项合计不一致；使用子项重算值后{parent_name}勾稽成立，"
            f"疑似{total_name}字段有误{diff_suffix}"
        )
        items = [
            {
                "check_item": self._format_check_item_for_row(total_name, period),
                "status": "fail",
                "period": period,
                "suspects": [{"code": total_code, "name": total_name}],
                "reason": reason,
            }
        ]
        for component in self._balance_validated_component_items_for_total(total_code):
            code = str(component.get("code") or "").strip()
            name = str(component.get("name") or code).strip()
            if not code and not name:
                continue
            items.append(
                {
                    "check_item": self._format_check_item_for_row(name, period),
                    "status": "pass",
                    "period": period,
                    "suspects": [{"code": code, "name": name}],
                    "reason": f"{name}参与{total_name}子项重算，且重算值通过{parent_name}校验",
                }
            )
        return items

    @staticmethod
    def _balance_basic_rule_component_items(total_code: str) -> List[Dict[str, str]]:
        for rule in BALANCE_BASIC_RULES:
            if str(rule.get("total_code") or "").strip() != total_code:
                continue
            items: List[Dict[str, str]] = []
            for component in rule.get("components", []):
                if not isinstance(component, tuple):
                    continue
                if len(component) == 3 and component[0] in {"+", "-"}:
                    _sign, code, name = component
                elif len(component) == 2:
                    code, name = component
                else:
                    continue
                code = str(code or "").strip()
                name = str(name or code).strip()
                if code or name:
                    items.append({"code": code, "name": name})
            return items
        return []

    def _format_confirmed_balance_subtree_mismatch_items(
        self,
        detail: Dict[str, Any],
        confirmed_subtree_failure_keys: Optional[set[tuple[str, str]]],
    ) -> List[Dict[str, Any]]:
        if str(detail.get("_table") or "").strip() != "balance":
            return []
        if str(detail.get("result") or "").strip() != "fail":
            return []

        raw_period = str(detail.get("period") or "").strip()
        total_code = str(detail.get("_rule_total_code") or "").strip()
        if not total_code or (total_code, raw_period) not in (confirmed_subtree_failure_keys or set()):
            return []

        total = detail.get("total")
        total_name = ""
        if isinstance(total, dict):
            total_name = str(total.get("name") or "").strip()
        if not total_name:
            total_name = str(detail.get("check") or "").split("(", 1)[0].strip()

        period = self._format_detail_period(detail)
        component_diff = self._format_component_diff(detail)
        diff_suffix = f"，差异{component_diff}" if component_diff else ""
        parent_reason = f"{total_name}与子项合计不一致；上层校验已将异常收敛到该层级{diff_suffix}"
        child_reason = f"属于{total_name}异常范围，需与合计一并复核{diff_suffix}"

        items: List[Dict[str, Any]] = []
        if total_code or total_name:
            items.append(
                {
                    "check_item": self._format_check_item_for_row(total_name, period),
                    "status": "fail",
                    "period": period,
                    "suspects": [{"code": total_code, "name": total_name}],
                    "reason": parent_reason,
                }
            )

        components = detail.get("components")
        if not isinstance(components, dict):
            return items

        for code, component in components.items():
            if not isinstance(component, dict):
                continue
            code = str(code or "").strip()
            name = str(component.get("name") or code).strip()
            if not code and not name:
                continue
            items.append(
                {
                    "check_item": self._format_check_item_for_row(name, period),
                    "status": "fail",
                    "period": period,
                    "suspects": [{"code": code, "name": name}],
                    "reason": child_reason,
                }
            )

        return items

    @staticmethod
    def _format_component_diff(detail: Dict[str, Any]) -> str:
        amounts = detail.get("amounts")
        if not isinstance(amounts, dict):
            return ""
        reported = _parse_decimal(amounts.get("reported_total"))
        recomputed = _parse_decimal(amounts.get("recomputed_total"))
        if reported is None or recomputed is None:
            return ""
        return str(abs(recomputed - reported))

    def _format_optional_absent_component_items(
        self,
        detail: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        if str(detail.get("result") or "").strip() != "pass":
            return []
        if str(detail.get("reason") or "").strip() != "未抽取子项，未进行子项校验":
            return []

        components = detail.get("optional_absent_components")
        if not isinstance(components, list):
            return []

        period = self._format_detail_period(detail)
        items: List[Dict[str, Any]] = []
        for component in components:
            if not isinstance(component, dict):
                continue
            code = str(component.get("code") or "").strip()
            name = str(component.get("name") or "").strip()
            if not code and not name:
                continue
            reason_name = name or code
            items.append(
                {
                    "check_item": self._format_check_item_for_row(reason_name, period),
                    "status": "pass",
                    "period": period,
                    "suspects": [{"code": code, "name": name}],
                    "reason": f"{reason_name}未抽取，未进行子项校验",
                }
            )
        return items

    def _format_supported_missing_total_without_components_detail(
        self,
        detail: Dict[str, Any],
        supported_inferred_keys: Optional[set[tuple[str, str]]],
    ) -> List[Dict[str, Any]]:
        if str(detail.get("_table") or "").strip() != "balance":
            return []
        if str(detail.get("result") or "").strip() != "fail":
            return []

        raw_period = str(detail.get("period") or "").strip()
        total_code = str(detail.get("_rule_total_code") or "").strip()
        if not total_code or (total_code, raw_period) not in (supported_inferred_keys or set()):
            return []

        suspects = detail.get("suspects")
        suspect_source = ""
        suspect_name = ""
        if isinstance(suspects, list) and suspects and isinstance(suspects[0], dict):
            suspect_source = str(suspects[0].get("source") or "").strip()
            suspect_name = str(suspects[0].get("name") or "").strip()
        if suspect_source != "missing_total":
            return []

        total_name = suspect_name or str(detail.get("check") or "").split("(", 1)[0].strip()
        period = self._format_detail_period(detail)
        parent_name = self._first_balance_parent_total_name(total_code)
        reason = (
            f"{total_name}未提取，按推测值为0；{parent_name}校验按照推测值计算已通过"
            if parent_name else
            f"{total_name}未提取，按推测值为0；上层校验按照推测值计算已通过"
        )
        return [
            {
                "check_item": self._format_check_item_for_row(total_name, period),
                "status": "fail",
                "period": period,
                "suspects": [{"code": total_code, "name": total_name}],
                "reason": reason,
                "_validated_inferred_value": "0",
            }
        ]

    def _format_supported_inferred_component_items(
        self,
        detail: Dict[str, Any],
        attribution: Dict[str, Any],
        supported_inferred_keys: Optional[set[tuple[str, str]]],
    ) -> List[Dict[str, Any]]:
        if str(detail.get("_table") or "").strip() != "balance":
            return []

        raw_period = str(detail.get("period") or "").strip()
        culprit_code = str(
            attribution.get("culprit_code") or detail.get("_rule_total_code") or ""
        ).strip()
        culprit_name = str(attribution.get("culprit_name") or "").strip()
        if (
            not culprit_code
            or (culprit_code, raw_period) not in (supported_inferred_keys or set())
        ):
            return []
        if culprit_code in {"ZY2015058", "ZY2015061"}:
            return []

        components = detail.get("components")
        if not isinstance(components, dict):
            return []

        period = self._format_detail_period(detail)
        items: List[Dict[str, Any]] = []
        for code, component in components.items():
            if not isinstance(component, dict):
                continue
            code = str(code)
            name = str(component.get("name") or code or "").strip()
            if not name:
                continue
            items.append(
                {
                    "check_item": self._format_check_item_for_row(name, period),
                    "status": "pass",
                    "period": period,
                    "suspects": [{"code": str(code), "name": name}],
                    "reason": f"{name}参与{culprit_name or culprit_code}推导，且推导值通过上层校验",
                }
            )
        return items

    def _format_validated_component_items(
        self,
        detail: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        validated_components = detail.get("validated_components")
        if not isinstance(validated_components, list):
            return []

        period = self._format_detail_period(detail)
        items: List[Dict[str, Any]] = []
        for component in validated_components:
            if not isinstance(component, dict):
                continue
            code = str(component.get("code") or "").strip()
            name = str(component.get("name") or "").strip()
            if not code and not name:
                continue
            reason_name = name or code
            items.append(
                {
                    "check_item": self._format_check_item_for_row(reason_name, period),
                    "status": "pass",
                    "period": period,
                    "suspects": [{"code": code, "name": name}],
                    "reason": f"{reason_name}已按内部语义复核通过",
                }
            )
        return items

    def _format_invalid_component_items(
        self,
        detail: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        invalid_components = detail.get("invalid_components")
        if not isinstance(invalid_components, list):
            return []

        period = self._format_detail_period(detail)
        items: List[Dict[str, Any]] = []
        for component in invalid_components:
            if not isinstance(component, dict):
                continue
            code = str(component.get("code") or "").strip()
            name = str(component.get("name") or "").strip()
            if not code and not name:
                continue
            aggregate_name = str(component.get("aggregate_name") or "内部语义合计").strip()
            aggregate_value = str(component.get("aggregate_value") or "").strip()
            component_sum = str(component.get("component_sum") or "").strip()
            reason = f"{aggregate_name}与相关明细加总不一致"
            if aggregate_value and component_sum:
                reason = f"{aggregate_name}为{aggregate_value}，相关明细加总为{component_sum}，不一致"
            items.append(
                {
                    "check_item": self._format_check_item_for_row(name or code, period),
                    "status": "fail",
                    "period": period,
                    "suspects": [{"code": code, "name": name}],
                    "reason": reason,
                }
            )
        return items

    def _format_verified_component_items(
        self,
        detail: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        verified_components = detail.get("verified_components")
        if not isinstance(verified_components, list):
            return []

        period = self._format_detail_period(detail)
        parent_check = str(detail.get("check") or "").strip()
        parent_name = parent_check.split("(", 1)[0] if parent_check else "当前合计项"
        items: List[Dict[str, Any]] = []
        for component in verified_components:
            if not isinstance(component, dict):
                continue
            code = str(component.get("code") or "").strip()
            name = str(component.get("name") or "").strip()
            if not code and not name:
                continue
            reason_name = name or code
            items.append(
                {
                    "check_item": self._format_check_item_for_row(reason_name, period),
                    "status": "pass",
                    "period": period,
                    "suspects": [{"code": code, "name": name}],
                    "reason": f"{reason_name}内部公式复核通过，已从{parent_name}嫌疑范围排除",
                }
            )
        return items

    def _format_missing_total_inference_detail(
        self,
        detail: Dict[str, Any],
        attribution: Dict[str, Any],
        *,
        display_inferred_value: bool = False,
    ) -> Dict[str, Any]:
        period = self._format_detail_period(detail)
        culprit_code = str(attribution.get("culprit_code") or detail.get("_rule_total_code") or "").strip()
        culprit_name = str(attribution.get("culprit_name") or "").strip()
        candidate_sum = str(attribution.get("candidate_sum") or detail.get("expected") or "").strip()
        return {
            "check_item": self._format_check_item_for_row(culprit_name, period),
            "status": detail.get("result"),
            "period": period,
            "suspects": [{"code": culprit_code, "name": culprit_name}],
            "reason": (
                f"{culprit_name}未提取；按子项和推测值为{candidate_sum}"
                if candidate_sum else
                f"{culprit_name}未提取"
            ),
            **(
                {"_display_inferred_value": candidate_sum}
                if display_inferred_value and candidate_sum else
                {}
            ),
        }

    @staticmethod
    def _should_display_unvalidated_missing_total_inference(
        detail: Dict[str, Any],
        attribution: Dict[str, Any],
    ) -> bool:
        table = str(detail.get("_table") or "").strip()
        culprit_code = str(
            attribution.get("culprit_code") or detail.get("_rule_total_code") or ""
        ).strip()
        culprit_name = str(attribution.get("culprit_name") or "").strip()
        return table == "profit" and (
            culprit_code == "L07000000" or culprit_name == "综合收益总额"
        )

    def _format_supported_missing_total_inference_detail(
        self,
        detail: Dict[str, Any],
        attribution: Dict[str, Any],
    ) -> Dict[str, Any]:
        period = self._format_detail_period(detail)
        culprit_code = str(attribution.get("culprit_code") or detail.get("_rule_total_code") or "").strip()
        culprit_name = str(attribution.get("culprit_name") or "").strip()
        candidate_sum = str(attribution.get("candidate_sum") or detail.get("expected") or "").strip()
        candidate_value = _parse_decimal(candidate_sum)
        table = str(detail.get("_table") or "").strip()
        parent_name = (
            self._first_cashflow_parent_total_name(culprit_code)
            if table == "cashflow" else
            self._first_balance_parent_total_name(culprit_code)
        )
        if (
            table == "balance"
            and candidate_value is not None
        ):
            reason = (
                f"{culprit_name}未提取，按子项推测值为{candidate_sum}；"
                f"{parent_name}校验按照推测值计算已通过"
                if parent_name else
                f"{culprit_name}未提取，按子项推测值为{candidate_sum}；上层校验按照推测值计算已通过"
            )
            status = "fail"
        elif (
            table == "cashflow"
            and candidate_value is not None
            and abs(candidate_value) > DECIMAL_TOLERANCE
        ):
            reason = (
                f"{culprit_name}未提取，按子项推测值为{candidate_sum}；"
                f"{parent_name}校验按照推测值计算已通过"
                if parent_name else
                f"{culprit_name}未提取，按子项推测值为{candidate_sum}；上层校验按照推测值计算已通过"
            )
            status = "fail"
        else:
            reason = (
                f"{culprit_name}未提取；按子项推测值为{candidate_sum}，且已通过上层校验"
                if candidate_sum else
                f"{culprit_name}未提取，但已通过上层校验"
            )
            status = "pass"
        return {
            "check_item": self._format_check_item_for_row(culprit_name, period),
            "status": status,
            "period": period,
            "suspects": [{"code": culprit_code, "name": culprit_name}],
            "reason": reason,
            **(
                {"_validated_inferred_value": candidate_sum}
                if status == "fail" and candidate_sum else
                {}
            ),
        }

    @staticmethod
    def _first_balance_parent_total_name(component_code: str) -> str:
        for rule in BALANCE_HIERARCHICAL_RULES:
            for code, _name in rule.get("components", []):
                if str(code or "").strip() == component_code:
                    return str(rule.get("total_name") or rule.get("name") or "").split("=", 1)[0].strip()
        return ""

    @staticmethod
    def _first_cashflow_parent_total_name(component_code: str) -> str:
        for rule in CASHFLOW_BASIC_RULES:
            for component in rule.get("components", []):
                if not isinstance(component, tuple):
                    continue
                if len(component) == 3:
                    _sign, code, _name = component
                elif len(component) == 2:
                    code, _name = component
                else:
                    continue
                if str(code or "").strip() == component_code:
                    return str(rule.get("total_name") or rule.get("name") or "").split("=", 1)[0].strip()
        return ""

    def _format_missing_component_parent_check_detail(
        self,
        detail: Dict[str, Any],
        attribution: Dict[str, Any],
    ) -> Dict[str, Any]:
        period = self._format_detail_period(detail)
        check_item = str(detail.get("check") or "").strip()
        parent_name = check_item.split("=", 1)[0].strip() or check_item.split("(", 1)[0].strip()
        parent_code = str(detail.get("_rule_total_code") or "").strip()
        candidate_sum = str(attribution.get("candidate_sum") or detail.get("expected") or "").strip()
        culprit_names = [
            str(name or "").strip()
            for name in attribution.get("culprit_names", [])
            if str(name or "").strip()
        ]
        inferred_name = self._join_names(culprit_names) or "缺失下级合计"
        if (
            str(attribution.get("mode") or "").strip() == "missing_component_zero_inferred_match"
            and str(detail.get("result") or "").strip() == "pass"
        ):
            reason = (
                f"{inferred_name}未抽取，按0参与{parent_name}校验通过，复算值为{candidate_sum}"
                if candidate_sum else
                f"{inferred_name}未抽取，按0参与{parent_name}校验通过"
            )
        else:
            reason = (
                f"使用推测的{inferred_name}值后，{parent_name}校验通过，复算值为{candidate_sum}"
                if candidate_sum else
                f"使用推测的{inferred_name}值后，{parent_name}校验通过"
            )
        formatted = {
            "check_item": self._format_check_item_for_row(parent_name, period),
            "status": "pass",
            "period": period,
            "suspects": [{"code": parent_code, "name": parent_name}],
            "reason": reason,
        }
        validated_components = self._validated_balance_component_items_for_culprits(
            attribution.get("culprit_codes")
        )
        if validated_components:
            formatted["validated_components"] = validated_components
        return formatted

    def _format_zero_inferred_component_items(
        self,
        detail: Dict[str, Any],
        attribution: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        period = self._format_detail_period(detail)
        check_item = str(detail.get("check") or "").strip()
        parent_name = check_item.split("=", 1)[0].strip() or check_item.split("(", 1)[0].strip()
        culprit_codes = [
            str(code or "").strip()
            for code in attribution.get("culprit_codes", [])
            if str(code or "").strip()
        ]
        culprit_names = [
            str(name or "").strip()
            for name in attribution.get("culprit_names", [])
            if str(name or "").strip()
        ]
        items: List[Dict[str, Any]] = []
        for index, code in enumerate(culprit_codes):
            name = culprit_names[index] if index < len(culprit_names) else code
            reason = (
                f"{name}未抽取，按0参与{parent_name}校验通过"
                if parent_name else
                f"{name}未抽取，按0参与校验通过"
            )
            items.append(
                {
                    "check_item": self._format_check_item_for_row(name, period),
                    "status": "pass",
                    "period": period,
                    "suspects": [{"code": code, "name": name}],
                    "reason": reason,
                }
            )
        return items

    def _validated_balance_component_items_for_culprits(
        self,
        culprit_codes: Any,
    ) -> List[Dict[str, str]]:
        if not isinstance(culprit_codes, list):
            return []

        components: List[Dict[str, str]] = []
        seen_codes: set[str] = set()
        for culprit_code in culprit_codes:
            for component in self._balance_validated_component_items_for_total(
                str(culprit_code or "").strip()
            ):
                code = component.get("code", "")
                if not code or code in seen_codes:
                    continue
                seen_codes.add(code)
                components.append(component)
        return components

    def _balance_validated_component_items_for_total(self, total_code: str) -> List[Dict[str, str]]:
        items = [dict(component) for component in self._balance_basic_rule_component_items(total_code)]
        for component in BALANCE_VALIDATED_COMPONENT_EXTRAS.get(total_code, ()):
            items.append(dict(component))
        return items

    def _format_mixed_hierarchical_parent_check_detail(
        self,
        detail: Dict[str, Any],
        attribution: Dict[str, Any],
    ) -> Dict[str, Any]:
        period = self._format_detail_period(detail)
        check_item = str(detail.get("check") or "").strip()
        parent_name = check_item.split("=", 1)[0].strip() or check_item.split("(", 1)[0].strip()
        parent_code = str(detail.get("_rule_total_code") or "").strip()
        candidate_sum = str(attribution.get("candidate_sum") or detail.get("expected") or "").strip()
        culprit_names = self._join_names(
            [
                str(name or "").strip()
                for name in attribution.get("culprit_names", [])
                if str(name or "").strip()
            ]
        )
        inferred_names = self._join_names(
            [
                str(name or "").strip()
                for name in attribution.get("validated_missing_component_names", [])
                if str(name or "").strip()
            ]
        )

        repair_parts = []
        if culprit_names:
            repair_parts.append(f"{culprit_names}子项重算值")
        if inferred_names:
            repair_parts.append(f"{inferred_names}推测值")
        repair_text = "和".join(repair_parts) or "推导值"
        reason = f"使用{repair_text}后，{parent_name}校验通过"
        if candidate_sum:
            reason = f"{reason}，复算值为{candidate_sum}"

        formatted = {
            "check_item": self._format_check_item_for_row(parent_name, period),
            "status": "pass",
            "period": period,
            "suspects": [{"code": parent_code, "name": parent_name}],
            "reason": reason,
        }
        validated_components = self._validated_balance_component_items_for_culprits(
            attribution.get("validated_missing_component_codes")
        )
        if validated_components:
            formatted["validated_components"] = validated_components
        return formatted

    @staticmethod
    def _format_check_item_for_row(name: str, period: str) -> str:
        if not name:
            return ""
        suffix = "期初" if period == "begin" else "期末" if period == "end" else ""
        return f"{name}({suffix})" if suffix else name

    def _format_detail(
        self,
        detail: Dict[str, Any],
    ) -> Dict[str, Any]:
        suspects = detail.get("suspects", [])
        formatted_suspects = []
        suspect_names = []
        if suspects:
            for suspect in suspects:
                if not isinstance(suspect, dict):
                    continue
                code = str(suspect.get("code") or "").strip()
                name = str(suspect.get("name") or "").strip()
                if code or name:
                    formatted_suspects.append(
                        {
                            "code": code,
                            "name": name,
                        }
                    )
                if name and name not in suspect_names:
                    suspect_names.append(name)

        formatted_detail = {
            "check_item": detail.get("check"),
            "status": detail.get("result"),
            "period": self._format_detail_period(detail),
            "suspects": formatted_suspects,
            "reason": self._format_detail_reason(detail, suspect_names),
        }
        validated_components = self._format_validated_components(detail)
        if validated_components:
            formatted_detail["validated_components"] = validated_components
        return formatted_detail

    @staticmethod
    def _format_validated_components(detail: Dict[str, Any]) -> List[Dict[str, str]]:
        components = detail.get("validated_components")
        if not isinstance(components, list):
            return []
        formatted_components = []
        for component in components:
            if not isinstance(component, dict):
                continue
            code = str(component.get("code") or "").strip()
            name = str(component.get("name") or "").strip()
            if code or name:
                formatted_components.append({"code": code, "name": name})
        return formatted_components


class FinStmtsMarkdownService:
    def __init__(self):
        env = os.getenv("RUNNING_ENV", "local")
        config = load_env_config(env)
        self.parse_core = FinancialStatementParseCore(config)
        self.markdown_fact_builder = MarkdownFinancialStatementFactBuilder(
            logger=logger
        )
        self.repository = PostgresFinancialStatementRepository(
            config,
            logger=logger,
        )

    def parse_fin_stmts_markdown(
        self,
        files: List[Dict[str, Any]],
        *,
        session_id: str,
        progress: Optional[MCPProgressReporter] = None,
    ) -> List[Dict[str, Any]]:
        normalized_session_id = _normalize_required_session_id(session_id)
        if not files:
            raise ValueError("files 不能为空")

        token = request_context.set(
            {
                "request_id": normalized_session_id,
                "session_id": normalized_session_id,
                "company_name": "",
            }
        )

        try:
            if progress is not None:
                progress.report("正在校验参数并准备输入文件", progress=2)
            normalized_files = self._normalize_files(files)
            download_dir = _resolve_mcp_persistent_dir("download")
            max_workers = min(
                _resolve_mcp_parse_max_workers(),
                len(normalized_files),
            )

            if max_workers == 1:
                return [
                    self._build_file_result(
                        input_file=input_file,
                        download_dir=download_dir,
                        session_id=normalized_session_id,
                        progress=progress,
                    )
                    for input_file in normalized_files
                ]

            return self._parse_files_concurrently(
                normalized_files=normalized_files,
                download_dir=download_dir,
                session_id=normalized_session_id,
                max_workers=max_workers,
                progress=progress,
            )
        finally:
            request_context.reset(token)

    def _parse_files_concurrently(
        self,
        *,
        normalized_files: List[InputFile],
        download_dir: str,
        session_id: str,
        max_workers: int,
        progress: Optional[MCPProgressReporter] = None,
    ) -> List[Dict[str, Any]]:
        results: List[Optional[Dict[str, Any]]] = [None] * len(normalized_files)

        with ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="mcp-fin-stmts-parse",
        ) as executor:
            future_to_input = {
                context_aware_submit(
                    executor,
                    self._build_file_result,
                    input_file=input_file,
                    download_dir=download_dir,
                    session_id=session_id,
                    progress=None,
                ): (index, input_file)
                for index, input_file in enumerate(normalized_files)
            }

            for completed_count, future in enumerate(
                as_completed(future_to_input),
                start=1,
            ):
                index, input_file = future_to_input[future]
                try:
                    results[index] = future.result()
                except Exception as exc:
                    logger.exception(
                        "[LIFECYCLE] 财报文件并发处理异常: "
                        f"session_id={session_id}, "
                        f"file_name={input_file.fileName}, error={exc}"
                    )
                    results[index] = self._build_unexpected_failure_result(
                        input_file,
                        exc,
                    )

                if progress is not None:
                    progress.report(
                        f"已完成 {completed_count}/{len(normalized_files)} 个文件",
                        progress=(
                            2
                            + (2 * completed_count / len(normalized_files))
                        ),
                    )

        return [cast(Dict[str, Any], result) for result in results]

    @staticmethod
    def _build_unexpected_failure_result(
        input_file: InputFile,
        exc: Exception,
    ) -> Dict[str, Any]:
        return {
            "message": f"解析失败: {exc}",
            "file_name": input_file.fileName,
            "company_name": "",
            "markdown_files": [],
        }

    def _normalize_files(self, files: List[Dict[str, Any]]) -> List[InputFile]:
        normalized_files = []
        used_names = set()

        for index, file_item in enumerate(files, start=1):
            if not isinstance(file_item, dict):
                raise ValueError("files 中的每一项都必须是对象")

            source = self._pick_first_value(file_item, "fileUrl", "file_url", "url", "path")
            if not source:
                raise ValueError(f"第 {index} 个文件缺少 fileUrl/file_url/url/path")

            provided_name = self._pick_first_value(file_item, "fileName", "file_name", "name")
            file_name = self._build_unique_file_name(
                provided_name or self._derive_file_name(source, index),
                used_names,
            )

            normalized_files.append(InputFile(fileName=file_name, fileUrl=source))

        return normalized_files

    @staticmethod
    def _pick_first_value(file_item: Dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = file_item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _derive_file_name(source: str, index: int) -> str:
        parsed = urlparse(source)
        candidate = os.path.basename(unquote(parsed.path)) if parsed.scheme else os.path.basename(source)
        candidate = candidate.strip()
        if candidate:
            return candidate
        return f"input_{index}"

    @staticmethod
    def _build_unique_file_name(file_name: str, used_names: set[str]) -> str:
        candidate = os.path.basename(file_name) or "input"
        stem = Path(candidate).stem or "input"
        suffix = Path(candidate).suffix

        if candidate not in used_names:
            used_names.add(candidate)
            return candidate

        counter = 1
        while True:
            deduped = f"{stem}_{counter}{suffix}"
            if deduped not in used_names:
                used_names.add(deduped)
                return deduped
            counter += 1

    def _build_file_result(
        self,
        input_file: InputFile,
        download_dir: str,
        session_id: str,
        progress: Optional[MCPProgressReporter] = None,
    ) -> Dict[str, Any]:
        documents: List[StatementMarkdownDocument] = []
        markdown_files: List[Dict[str, Any]] = []
        company_name = ""
        message = "解析成功"

        try:
            os.makedirs(download_dir, exist_ok=True)
            if progress is not None:
                progress.report("正在下载/读取财报文件", progress=3)
            batch_download([input_file], download_dir, clean_dir=False)
            local_path = os.path.join(download_dir, input_file.fileName)
            file_kind = self._detect_file_kind(local_path)
            if file_kind is None:
                message = "不支持的文件类型"
            else:
                if progress is not None:
                    progress.report("正在识别财报表格并生成 Markdown", progress=4)
                documents = self._extract_markdown_documents(
                    local_path=local_path,
                    is_consolidated=None,
                    report_type=None,
                )
                markdown_files = self._build_markdown_files(documents)
                if not markdown_files:
                    message = "未识别到财报表格内容"
                else:
                    company_name = self._resolve_company_name(
                        markdown_files,
                        documents,
                    )
                    try:
                        self._persist_markdown_documents(
                            session_id=session_id,
                            file_name=input_file.fileName,
                            company_name=company_name,
                            documents=documents,
                        )
                    except Exception as exc:
                        message = f"解析成功但 Markdown 入库失败: {exc}"
                        logger.warning(
                            "[LIFECYCLE] Markdown 入库失败: "
                            f"session_id={session_id}, "
                            f"file_name={input_file.fileName}, error={exc}"
                        )
        except Exception as exc:
            message = f"解析失败: {exc}"

        return {
            "message": message,
            "file_name": input_file.fileName,
            "company_name": company_name,
            "markdown_files": markdown_files,
        }

    def _persist_markdown_documents(
        self,
        *,
        session_id: str,
        file_name: str,
        company_name: str,
        documents: List[StatementMarkdownDocument],
    ) -> None:
        rows = self.markdown_fact_builder.build_rows(
            session_id=session_id,
            company_name=company_name,
            file_name=file_name,
            documents=documents,
        )
        if not rows:
            return
        self.repository.replace_file_markdown(
            session_id=session_id,
            file_name=file_name,
            rows=rows,
        )
        logger.info(
            "[LIFECYCLE] Markdown 入库完成: "
            f"session_id={session_id}, file_name={file_name}, "
            f"saved_rows={len(rows)}"
        )

    @staticmethod
    def _detect_file_kind(local_path: str) -> Optional[str]:
        suffix = Path(local_path).suffix.lower()
        return SUPPORTED_FILE_KINDS.get(suffix)

    def _extract_markdown_documents(
        self,
        local_path: str,
        is_consolidated: Optional[bool],
        report_type: Optional[str],
    ) -> List[StatementMarkdownDocument]:
        return self.parse_core.parse_local_file(
            local_path,
            output_dir=_resolve_mcp_persistent_dir("output"),
            is_consolidated=is_consolidated,
            report_period=report_type,
        )

    @staticmethod
    def _build_markdown_files(
        documents: List[StatementMarkdownDocument],
    ) -> List[Dict[str, Any]]:
        markdown_files = []
        for document in documents:
            if document.content.strip():
                markdown_files.append(
                    FinStmtsMarkdownService._serialize_markdown_document(document)
                )
        return markdown_files

    @staticmethod
    def _serialize_markdown_document(
        document: StatementMarkdownDocument,
    ) -> Dict[str, Any]:
        item = {
            "table_name": document.table_name,
            "table_type": document.table_type,
            "date": document.date,
            "period": document.period,
            "is_consolidated": document.is_consolidated,
            "content": document.content,
        }
        if document.page is not None:
            item["page"] = document.page
        if document.unit and document.unit != "N/A":
            item["unit"] = document.unit
        return item

    @staticmethod
    def _resolve_company_name(
        markdown_files: List[Dict[str, Any]],
        documents: List[StatementMarkdownDocument],
    ) -> str:
        return resolve_unique_company_name(
            [document.company_name for document in documents]
        )


class FinStmtsAuditFirmService:
    def __init__(self):
        env = os.getenv("RUNNING_ENV", "local")
        config = load_env_config(env)
        llm_config = config.get("llm", {})
        llm_client = LLMClient(llm_config) if llm_config.get("base_url") else None
        self.audit_core = FinancialStatementAuditFirmCore(
            config,
            llm_client=llm_client,
            logger=logger,
        )

    def fin_stmts_parse_audit_firm(
        self,
        files: List[Dict[str, Any]],
        *,
        session_id: str,
        progress: Optional[MCPProgressReporter] = None,
    ) -> List[Dict[str, Any]]:
        normalized_session_id = _normalize_required_session_id(session_id)
        if not files:
            raise ValueError("files 不能为空")

        token = request_context.set(
            {
                "request_id": normalized_session_id,
                "session_id": normalized_session_id,
                "company_name": "",
            }
        )
        try:
            if progress is not None:
                progress.report("正在校验参数并准备输入文件", progress=2)
            normalized_files = self._normalize_files(files)
            results = []
            download_dir = _resolve_mcp_persistent_dir("download")
            for input_file in normalized_files:
                results.append(
                    self._build_file_result(
                        input_file=input_file,
                        download_dir=download_dir,
                        progress=progress,
                    )
                )
            return results
        finally:
            request_context.reset(token)

    @staticmethod
    def _normalize_files(files: List[Dict[str, Any]]) -> List[InputFile]:
        normalized_files = []
        used_names = set()

        for index, file_item in enumerate(files, start=1):
            if not isinstance(file_item, dict):
                raise ValueError("files 中的每一项都必须是对象")

            source = FinStmtsMarkdownService._pick_first_value(
                file_item,
                "fileUrl",
                "file_url",
                "url",
                "path",
            )
            if not source:
                raise ValueError(f"第 {index} 个文件缺少 fileUrl/file_url/url/path")

            provided_name = FinStmtsMarkdownService._pick_first_value(
                file_item,
                "fileName",
                "file_name",
                "name",
            )
            file_name = FinStmtsMarkdownService._build_unique_file_name(
                provided_name or FinStmtsMarkdownService._derive_file_name(source, index),
                used_names,
            )
            normalized_files.append(InputFile(fileName=file_name, fileUrl=source))

        return normalized_files

    def _build_file_result(
        self,
        input_file: InputFile,
        download_dir: str,
        progress: Optional[MCPProgressReporter] = None,
    ) -> Dict[str, Any]:
        try:
            os.makedirs(download_dir, exist_ok=True)
            if progress is not None:
                progress.report("正在下载/读取财报文件", progress=3)
            batch_download([input_file], download_dir, clean_dir=False)
            local_path = os.path.join(download_dir, input_file.fileName)
            if self._detect_file_kind(local_path) is None:
                return self._build_empty_result(
                    message="不支持的文件类型",
                    file_name=input_file.fileName,
                )

            if progress is not None:
                progress.report("正在识别审计状态和会计师事务所", progress=4)
            audit_result = self.audit_core.extract_local_file(local_path)
            message = (
                "识别成功"
                if audit_result.audit_status in {"audited", "unaudited"}
                else "未识别到审计信息"
            )
            return {
                "message": message,
                "file_name": input_file.fileName,
                **audit_result.to_dict(),
            }
        except Exception as exc:
            return self._build_empty_result(
                message=f"识别失败: {exc}",
                file_name=input_file.fileName,
            )

    @staticmethod
    def _detect_file_kind(local_path: str) -> Optional[str]:
        suffix = Path(local_path).suffix.lower()
        return SUPPORTED_FILE_KINDS.get(suffix)

    @staticmethod
    def _build_empty_result(
        *,
        message: str,
        file_name: str,
    ) -> Dict[str, Any]:
        return {
            "message": message,
            "file_name": file_name,
            "audit_status": "unknown",
            "audit_firm_name": "",
            "confidence": "low",
            "evidence": [],
        }


class FinStmtsExcelExportService:
    def __init__(self):
        self.export_core = FinancialStatementExcelExportCore()
        env = os.getenv("RUNNING_ENV", "local")
        config = load_env_config(env)
        llm_config = config.get("llm", {})
        llm_client = LLMClient(llm_config) if llm_config.get("base_url") else None
        self.company_name_resolver = CompanyNameResolver(llm_client=llm_client)

    def fin_stmts_parse_markdown_to_excel(
        self,
        parse_results: List[Any],
        *,
        session_id: str,
        output_dir: Optional[str] = None,
        progress: Optional[MCPProgressReporter] = None,
    ) -> List[Dict[str, Any]]:
        _normalize_required_session_id(session_id)
        if not parse_results:
            raise ValueError("parse_results 不能为空")

        if progress is not None:
            progress.report("正在校验参数并准备导出内容", progress=2)
        resolved_output_dir = output_dir or _resolve_mcp_persistent_dir("output")
        results = []
        for index, item in enumerate(parse_results, start=1):
            results.append(
                self._export_single_item(
                    item=item,
                    index=index,
                    output_dir=resolved_output_dir,
                    progress=progress,
                )
            )
        return results

    def _export_single_item(
        self,
        *,
        item: Any,
        index: int,
        output_dir: Optional[str],
        progress: Optional[MCPProgressReporter] = None,
    ) -> Dict[str, Any]:
        if not isinstance(item, dict):
            raise ValueError("parse_results 中的每一项都必须是对象")

        file_name = self._pick_file_name(item, index)
        markdown_files = item.get("markdown_files")
        company_name = self._resolve_company_name(item, markdown_files)
        if not isinstance(markdown_files, list) or not markdown_files:
            return self._build_empty_result(
                message="没有可导出的 markdown_files",
                file_name=file_name,
                company_name=company_name,
            )

        documents = statement_markdown_documents_from_items(
            markdown_files,
            default_source_file_name=file_name,
            default_source_file_path=self._pick_first_string(item, "source_file_path", "file_path"),
        )
        if not documents:
            return self._build_empty_result(
                message="没有可导出的财报表格",
                file_name=file_name,
                company_name=company_name,
            )

        try:
            if progress is not None:
                progress.report("正在生成 Excel 文件", progress=3)
            artifact = self.export_core.export_markdown_documents_to_excel(
                documents,
                file_name=file_name,
                output_dir=output_dir,
            )
        except Exception as exc:
            return self._build_empty_result(
                message=f"Excel 导出失败: {exc}",
                file_name=file_name,
                company_name=company_name,
            )

        sheets = self._build_public_sheets(artifact.exported_sheets)
        if not artifact.excel_file_path or not artifact.excel_file_name or not sheets:
            return self._build_empty_result(
                message="没有可导出的财报表格",
                file_name=file_name,
                company_name=company_name,
            )

        if progress is not None:
            progress.report("正在上传 Excel 文件", progress=4)
        excel_file_id, excel_file_url = self._upload_excel_file(
            artifact.excel_file_path,
            artifact.excel_file_name,
        )
        if not excel_file_url:
            return {
                "message": "Excel 导出成功但上传失败",
                "file_name": file_name,
                "company_name": company_name,
                "excel_file_name": artifact.excel_file_name,
                "excel_file_id": "",
                "excel_file_url": "",
                "sheets": sheets,
            }

        return {
            "message": "",
            "file_name": file_name,
            "company_name": company_name,
            "excel_file_name": artifact.excel_file_name,
            "excel_file_id": excel_file_id,
            "excel_file_url": excel_file_url,
            "sheets": sheets,
        }

    @staticmethod
    def _pick_file_name(item: Dict[str, Any], index: int) -> str:
        for key in ("file_name", "source_file_name", "name"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return Path(value.strip()).name
        return f"input_{index}"

    @staticmethod
    def _pick_first_string(item: Dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _resolve_company_name(
        self,
        item: Dict[str, Any],
        markdown_files: Any,
    ) -> str:
        explicit_company_name = self._pick_first_string(item, "company_name", "companyName")
        if explicit_company_name:
            return explicit_company_name
        if isinstance(markdown_files, list):
            return self.company_name_resolver.extract_from_items(
                markdown_files_item
                for markdown_files_item in markdown_files
                if isinstance(markdown_files_item, dict)
            )
        return ""

    @staticmethod
    def _build_public_sheets(exported_sheets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        sheets: List[Dict[str, Any]] = []
        for sheet in exported_sheets:
            table_name = sheet.get("table_name")
            if not isinstance(table_name, str) or not table_name.strip():
                continue
            date = sheet.get("date")
            public_sheet: Dict[str, Any] = {
                "table_name": table_name.strip(),
                "date": str(date).strip() if date not in (None, "") else "N/A",
                "is_consolidated": str(
                    normalize_is_consolidated(sheet.get("is_consolidated", False))
                ).lower(),
            }
            page = _normalize_optional_page(sheet.get("page"))
            if page is not None:
                public_sheet["page"] = page
            sheets.append(public_sheet)
        return sheets

    @staticmethod
    def _build_upload_object_key(excel_file_name: str) -> str:
        date_prefix = datetime.now().strftime("%Y%m%d")
        return f"agent-financial_report_agent/fin_parse_excel/{date_prefix}/{uuid.uuid4()}_{excel_file_name}"

    def _upload_excel_file(self, local_file_path: str, excel_file_name: str) -> tuple[str, str]:
        object_key = self._build_upload_object_key(excel_file_name)
        try:
            file_url = S3Client.upload_file(
                local_file_path=local_file_path,
                s3_file_path=object_key,
                config_key="agent_oss",
            )
        except Exception:
            return "", ""
        return (object_key, file_url or "") if file_url else ("", "")

    @staticmethod
    def _build_empty_result(
        *,
        message: str,
        file_name: str,
        company_name: str,
    ) -> Dict[str, Any]:
        return {
            "message": message,
            "file_name": file_name,
            "company_name": company_name,
            "excel_file_name": "",
            "excel_file_id": "",
            "excel_file_url": "",
            "sheets": [],
        }


markdown_service: Optional[FinStmtsMarkdownService] = None
map_service: Optional[FinStmtsMapService] = None
inspect_service: Optional[FinStmtsInspectService] = None
export_service: Optional[FinStmtsExcelExportService] = None
audit_firm_service: Optional[FinStmtsAuditFirmService] = None


def get_markdown_service() -> FinStmtsMarkdownService:
    global markdown_service
    if markdown_service is None:
        markdown_service = FinStmtsMarkdownService()
    return markdown_service


def get_map_service() -> FinStmtsMapService:
    global map_service
    if map_service is None:
        map_service = FinStmtsMapService()
    return map_service


def get_inspect_service() -> FinStmtsInspectService:
    global inspect_service
    if inspect_service is None:
        inspect_service = FinStmtsInspectService()
    return inspect_service


def get_export_service() -> FinStmtsExcelExportService:
    global export_service
    if export_service is None:
        export_service = FinStmtsExcelExportService()
    return export_service


def get_audit_firm_service() -> FinStmtsAuditFirmService:
    global audit_firm_service
    if audit_firm_service is None:
        audit_firm_service = FinStmtsAuditFirmService()
    return audit_firm_service


@mcp_server.tool()
def parse_fin_stmts_markdown(
    files: List[Dict[str, Any]],
    session_id: str,
    ctx: Optional[Context] = None,
) -> List[Dict[str, Any]]:
    """
    解析本地/下载后的财报文件，按输入文件返回标准 markdown 文档。

    files 中每个元素支持以下任一字段组合：
    - {"fileUrl": "...", "fileName": "..."}
    - {"file_url": "...", "file_name": "..."}
    - {"url": "...", "name": "..."}
    - {"path": "/local/path/to/file.pdf"}

    session_id 为必填会话 ID。

    顶层每项返回：
    - message/file_name/company_name/markdown_files

    返回的 markdown_files 每项包含：
    - table_name/table_type/date/period/is_consolidated/content
    - unit: 可选元数据
    """
    progress = MCPProgressReporter(ctx, MCP_PROGRESS_TOTALS["parse_fin_stmts_markdown"])
    return _run_mcp_tool_call(
        "parse_fin_stmts_markdown",
        {
            "files": files,
            "session_id": session_id,
        },
        lambda: get_markdown_service().parse_fin_stmts_markdown(
            files=files,
            session_id=session_id,
            **_progress_call_kwargs(progress),
        ),
        progress=progress,
    )


@mcp_server.tool()
def fin_stmts_parse_map(
    parse_results: List[Any],
    session_id: str,
    ctx: Optional[Context] = None,
) -> List[Dict[str, Any]]:
    """
    将 parse_fin_stmts_markdown 的完整输出按文件映射为 yaml 科目编码结果。

    入参必须是 parse_fin_stmts_markdown 的顶层返回数组。
    session_id 为必填会话 ID。
    每个文件级结果返回：
    - message/file_name/company_name/mapped_results

    mapped_results 每项仅包含：
    - table_name/table_type/page/date/period/is_consolidated/view_data
    - view_data 为对外展示树，按 view.yaml 的 view_data 分层组织字段，并保留 null/"" 状态差异

    tool 返回前会自动触发一次被动勾稽校验与入库：
    - report_status 固定为 "0"
    - 勾稽失败不影响 map 主返回
    """
    progress = MCPProgressReporter(ctx, MCP_PROGRESS_TOTALS["fin_stmts_parse_map"])
    return _run_mcp_tool_call(
        "fin_stmts_parse_map",
        {
            "parse_results": parse_results,
            "session_id": session_id,
        },
        lambda: get_map_service().fin_stmts_parse_map(
            parse_results=parse_results,
            session_id=session_id,
            **_progress_call_kwargs(progress),
        ),
        progress=progress,
    )


@mcp_server.tool()
def fin_stmts_parse_inspect(
    map_results: List[Any],
    session_id: str,
    report_status: str = "1",
    ctx: Optional[Context] = None,
) -> List[Dict[str, Any]]:
    """
    将 fin_stmts_parse_map 的完整输出聚合后执行勾稽校验。

    map_results 必须是 fin_stmts_parse_map 的顶层返回数组。
    勾稽校验先基于 view_data 展示字段执行首层简单校验。
    被动触发保存时，如果 map_results 中未显式携带 canonical_data，会按 session_id 读取同会话
    map 阶段缓存的规范语义结果，用于内部持久化和后续下钻能力。
    主动触发保存时，以当前 view_data 为人工确认结果，并由 view_data 现场生成 canonical_data。

    保存参数：
    - session_id: 会话 ID；必填
    - report_status: "0" 表示被动触发保存，"1" 表示主动触发保存

    返回文件级数组，每项包含：
    - message/file_name/company_name/inspection_passed/inspected_results

    inspected_results 每项包含：
    - table_name/table_type/date/period/is_consolidated/details

    details 为当前表的校验明细数组，每项仅包含：
    - check_item/status/period/suspects/reason
    """
    progress = MCPProgressReporter(ctx, MCP_PROGRESS_TOTALS["fin_stmts_parse_inspect"])
    return _run_mcp_tool_call(
        "fin_stmts_parse_inspect",
        {
            "map_results": map_results,
            "session_id": session_id,
            "report_status": report_status,
        },
        lambda: get_inspect_service().fin_stmts_parse_inspect(
            map_results=map_results,
            session_id=session_id,
            report_status=report_status,
            **_progress_call_kwargs(progress),
        ),
        progress=progress,
    )


@mcp_server.tool()
def fin_stmts_parse_markdown_to_excel(
    parse_results: List[Any],
    session_id: str,
    output_dir: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> List[Dict[str, Any]]:
    """
    将 parse_fin_stmts_markdown 返回的结果按输入文件导出为 Excel，并上传到 sdoss。

    parse_results 每项默认支持以下字段：
    - file_name: 输入文件名
    - company_name: 公司名称，可选
    - markdown_files: parse_fin_stmts_markdown 返回的 markdown_files 数组
    - markdown_files[].table_name/content: 必填
    - markdown_files[].page/date/unit/is_consolidated/source_file_name/source_file_path: 可选

    返回每项包含：
    - message/file_name/company_name/excel_file_name/excel_file_id/excel_file_url/sheets
    - sheets[].table_name/page/date/is_consolidated

    session_id 为必填会话 ID。
    output_dir 可选；未传时保存到 MCP 当天持久 output 目录。
    """
    progress = MCPProgressReporter(ctx, MCP_PROGRESS_TOTALS["fin_stmts_parse_markdown_to_excel"])
    return _run_mcp_tool_call(
        "fin_stmts_parse_markdown_to_excel",
        {
            "parse_results": parse_results,
            "session_id": session_id,
            "output_dir": output_dir,
        },
        lambda: get_export_service().fin_stmts_parse_markdown_to_excel(
            parse_results=parse_results,
            session_id=session_id,
            output_dir=output_dir,
            **_progress_call_kwargs(progress),
        ),
        progress=progress,
    )


@mcp_server.tool()
def fin_stmts_parse_audit_firm(
    files: List[Dict[str, Any]],
    session_id: str,
    ctx: Optional[Context] = None,
) -> List[Dict[str, Any]]:
    """
    识别财报文件是否经审计，并返回会计师事务所名称。

    files 中每个元素支持以下任一字段组合：
    - {"fileUrl": "...", "fileName": "..."}
    - {"file_url": "...", "file_name": "..."}
    - {"url": "...", "name": "..."}
    - {"path": "/local/path/to/file.pdf"}

    session_id 为必填会话 ID。

    顶层每项返回：
    - message/file_name/audit_status/audit_firm_name/confidence/evidence

    audit_status 固定取值：
    - audited: 明确识别到会计师事务所
    - unaudited: 明确识别到未经审计
    - unknown: 没有足够证据
    """
    progress = MCPProgressReporter(ctx, MCP_PROGRESS_TOTALS["fin_stmts_parse_audit_firm"])
    return _run_mcp_tool_call(
        "fin_stmts_parse_audit_firm",
        {
            "files": files,
            "session_id": session_id,
        },
        lambda: get_audit_firm_service().fin_stmts_parse_audit_firm(
            files=files,
            session_id=session_id,
            **_progress_call_kwargs(progress),
        ),
        progress=progress,
    )
