#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import gc as _gc
import json
import os
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from loguru import logger as _loguru_logger

from fin_stmts_parse.exceptions.base_exception import ServiceError
from fin_stmts_parse.src.core.contracts import MappedStatementResult, StatementMarkdownDocument
from fin_stmts_parse.src.core.inspect import FinancialStatementInspectCore
from fin_stmts_parse.src.core.map import FinancialStatementMapCore
from fin_stmts_parse.src.core.parse import FinancialStatementParseCore
from fin_stmts_parse.utils.file_transfer import batch_download, get_all_files
from fin_stmts_parse.utils.logger import logger, request_context
from fin_stmts_parse.utils.s3_client import S3Client


class LogCapture:
    ALARM_MARKER = "[ALARM]"

    def __init__(self):
        self.messages: List[dict] = []
        self._sink_id = None

    def _sink(self, message):
        record = message.record
        if record["level"].no >= 30:
            self.messages.append({
                "text": record["message"],
                "level": record["level"].name,
            })

    def has_alarms(self) -> bool:
        return any(self.ALARM_MARKER in message["text"] for message in self.messages)

    def get_alarm_issues(self) -> List[str]:
        issues = []
        for message in self.messages:
            if self.ALARM_MARKER in message["text"]:
                issues.append(f"[{message['level']}] {message['text']}")
        return issues

    def __enter__(self):
        self._sink_id = _loguru_logger.add(self._sink, level="WARNING", format="{message}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._sink_id is not None:
            _loguru_logger.remove(self._sink_id)
        return False


class DealStatus(Enum):
    SUCCESS = "1"
    PROCESSING = "2"
    FAILED = "3"
    PARTIAL_SUCCESS = "4"


class FinancialReportService:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.output_base_dir = config["fin_files"]["local_path"]
        self.logger = logger
        self.parse_core = FinancialStatementParseCore(config)
        self.map_core = FinancialStatementMapCore(config)
        self.inspect_core = FinancialStatementInspectCore()

    def _build_pipeline_context(self, request: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "request_id": request.get("requestID", ""),
            "fns_id": request.get("fnsId", ""),
            "fns_no": request.get("fnsNo", ""),
            "company_name": request.get("companyName", ""),
            "report_type": request.get("reportType", ""),
            "end_date": request.get("endDate", ""),
            "fin_files": request.get("fileUrls", []),
        }

    def _log_pipeline_context(self, context: Dict[str, Any]) -> None:
        request_context.set({
            "request_id": context["request_id"],
            "company_name": context["company_name"],
        })

        self.logger.info("=== 开始处理财报解析请求 ===")
        self.logger.info(f"请求ID: {context['request_id']}")
        self.logger.info(f"财务报表主ID: {context['fns_id']}")
        self.logger.info(f"报表代号: {context['fns_no']}")
        self.logger.info(f"公司名称: {context['company_name']}")
        self.logger.info(f"报表类型: {context['report_type']}")
        self.logger.info(f"截至日期: {context['end_date']}")
        self.logger.info(f"文件数量: {len(context['fin_files'])}")
        self.logger.info(f"报表类型: {'合并' if context['fns_no'] == 'FN192' else '非合并'}报表")

    def _run_parse_pipeline(self, request: Dict[str, Any]) -> Dict[str, Any]:
        context = self._build_pipeline_context(request)
        request_id = context["request_id"]
        fns_id = context["fns_id"]
        fns_no = context["fns_no"]
        company_name = context["company_name"]
        report_type = context["report_type"]
        end_date = context["end_date"]
        fin_files = context["fin_files"]
        is_consolidated = fns_no == "FN192"

        self._log_pipeline_context(context)

        local_dir = None
        try:
            local_dir = self.config["fin_files"]["local_path"].format(
                **{
                    "company_name": company_name,
                    "end_date": end_date,
                    "request_id": request_id,
                }
            )
            self.logger.info(f"本次请求目录: {local_dir}")

            download_dir = os.path.join(local_dir, "download")
            batch_download(fin_files, download_dir)

            all_mapped_results: List[MappedStatementResult] = []
            local_file_urls = get_all_files(download_dir)
            task_output_dir = os.path.join(local_dir, "output")

            for idx, file_url in enumerate(local_file_urls, start=1):
                self.logger.info(f"处理第 {idx}/{len(local_file_urls)} 个文件: {file_url}")

                with LogCapture() as capture:
                    try:
                        mapped_results = self._process_single_file(
                            file_url,
                            task_output_dir,
                            is_consolidated,
                            report_type,
                            end_date,
                        )

                        if mapped_results:
                            if capture.has_alarms():
                                self.logger.warning(f"⚠️ 文件 {idx} 检测到需要警报的问题")
                                self._save_failed_file(
                                    file_path=file_url,
                                    company_name=company_name,
                                    end_date=end_date,
                                    reason="解析存在警报问题",
                                    issues=capture.get_alarm_issues(),
                                    extracted_data=self._summarize_mapped_results(mapped_results),
                                )

                            all_mapped_results.extend(mapped_results)
                            self.logger.info(f"✅ 文件 {idx} 处理完成")
                        else:
                            self.logger.warning(f"⚠️ 文件 {idx} 解析失败，返回结果为空")
                            alarm_issues = capture.get_alarm_issues() or ["未能提取任何有效数据"]
                            self._save_failed_file(
                                file_path=file_url,
                                company_name=company_name,
                                end_date=end_date,
                                reason="解析失败",
                                issues=alarm_issues,
                            )

                    except Exception as exc:
                        alarm_issues = capture.get_alarm_issues()
                        alarm_issues.append(f"[ERROR] [EXCEPTION] {str(exc)}")
                        self.logger.error(f"❌ 文件 {idx} 解析异常: {exc}", exc_info=True)
                        self._save_failed_file(
                            file_path=file_url,
                            company_name=company_name,
                            end_date=end_date,
                            reason="解析异常",
                            issues=alarm_issues,
                        )

            if not all_mapped_results:
                error_msg = "未能成功解析任何文件"
                self.logger.error(error_msg)
                return {
                    "requestId": request_id,
                    "fnsId": fns_id,
                    "fnsNo": fns_no,
                    "error": error_msg,
                }

            merged_data = self._merge_mapped_results(all_mapped_results)
            statement_flags = self._build_statement_presence_flags(all_mapped_results)
            inspection_result = self.inspect_core.inspect_mapped_results(all_mapped_results)
            inspection_remark = inspection_result.remark

            bs_count = len(merged_data.get("balance", {}))
            is_count = len(merged_data.get("profit", {}))
            cs_count = len(merged_data.get("cashflow", {}))
            self.logger.info(
                f"提取数据统计: 资产负债表 {bs_count} 项, 利润表 {is_count} 项, 现金流量表 {cs_count} 项"
            )
            if inspection_remark:
                self.logger.warning(f"[ALARM] {inspection_remark}")

            self.logger.info("=== 财报解析请求处理完成 ===")
            return {
                "requestId": request_id,
                "fnsId": fns_id,
                "fnsNo": fns_no,
                "mergedData": merged_data,
                "statementFlags": statement_flags,
                "inspectionRemark": inspection_remark,
            }
        finally:
            _gc.collect()
            try:
                import ctypes as _ctypes

                _libc = _ctypes.CDLL("libc.so.6")
                _libc.malloc_trim(0)
            except Exception:
                pass

    def parse_financial_report(self, request: Dict[str, Any]) -> Dict[str, Any]:
        pipeline_result = self._run_parse_pipeline(request)
        if pipeline_result.get("error"):
            return self._build_error_response(
                pipeline_result.get("requestId", ""),
                pipeline_result.get("fnsId", ""),
                pipeline_result.get("fnsNo", ""),
                pipeline_result.get("error", "未能成功解析任何文件"),
            )

        response = self._build_success_response(
            pipeline_result["requestId"],
            pipeline_result["fnsId"],
            pipeline_result["fnsNo"],
            pipeline_result["mergedData"],
            pipeline_result["statementFlags"],
        )
        inspection_remark = pipeline_result.get("inspectionRemark", "")
        if inspection_remark:
            response["dealRemark"] = f"处理成功; {inspection_remark}"
        return response

    def _process_single_file(
        self,
        file_path: str,
        output_dir: str,
        is_consolidated: bool,
        report_period: Optional[str] = None,
        end_date: str = "",
    ) -> List[MappedStatementResult]:
        documents = self.parse_core.parse_local_file(
            file_path,
            output_dir=output_dir,
            is_consolidated=is_consolidated,
            report_period=report_period,
        )
        if not documents:
            self.logger.warning(f"文件处理未返回任何结果: {file_path}")
            return []

        mapped_results: List[MappedStatementResult] = []
        for document in documents:
            document = self._apply_request_end_date_fallback(document, end_date)
            self.logger.info(
                f"处理报表: {document.table_name}, 合并={document.is_consolidated}, "
                f"日期={document.date}, 单位={document.unit}"
            )
            mapped_results.append(self.map_core.map_markdown_document(document))
            self.logger.info(f"✅ 完成 {document.table_name} 数据映射")

        if file_path.lower().endswith(".pdf"):
            self._check_financial_statements_completeness(mapped_results, file_path)
        return mapped_results

    @staticmethod
    def _normalize_request_end_date(end_date: str) -> str:
        digits = "".join(ch for ch in str(end_date or "") if ch.isdigit())
        if len(digits) >= 6:
            return digits[:6]
        return ""

    def _apply_request_end_date_fallback(
        self,
        document: StatementMarkdownDocument,
        end_date: str,
    ) -> StatementMarkdownDocument:
        if document.date and document.date != "N/A":
            return document

        normalized_end_date = self._normalize_request_end_date(end_date)
        if not normalized_end_date:
            return document

        self.logger.info(
            f"{document.table_name} 未识别到报表日期，使用请求 endDate 兜底: {normalized_end_date}"
        )
        return StatementMarkdownDocument(
            table_name=document.table_name,
            table_type=document.table_type,
            page=document.page,
            date=normalized_end_date,
            unit=document.unit,
            company_name=document.company_name,
            is_consolidated=document.is_consolidated,
            content=document.content,
            source_file_name=document.source_file_name,
            source_file_path=document.source_file_path,
        )

    def _check_financial_statements_completeness(
        self,
        mapped_results: List[MappedStatementResult],
        file_path: str,
    ) -> None:
        present_statement_types = {result.statement_type for result in mapped_results}
        required_tables = {
            "balance": "资产负债表",
            "profit": "利润表",
            "cashflow": "现金流量表",
        }
        missing_tables = [
            table_name
            for statement_type, table_name in required_tables.items()
            if statement_type not in present_statement_types
        ]
        if missing_tables:
            self.logger.warning(
                f"[ALARM] PDF解析三表不全：缺少 {'、'.join(missing_tables)}，文件: {os.path.basename(file_path)}"
            )

    def _merge_mapped_results(self, mapped_results: List[MappedStatementResult]) -> Dict[str, Any]:
        merged = {
            "balance": {},
            "profit": {},
            "cashflow": {},
        }
        for result in mapped_results:
            merged[result.statement_type].update(result.view_data_full)
        return merged

    @staticmethod
    def _build_statement_presence_flags(
        mapped_results: List[MappedStatementResult],
    ) -> Dict[str, str]:
        present_statement_types = {result.statement_type for result in mapped_results}
        return {
            "fnsItemBsFlag": "1" if "balance" in present_statement_types else "0",
            "fnsItemIsFlag": "1" if "profit" in present_statement_types else "0",
            "fnsItemCsFlag": "1" if "cashflow" in present_statement_types else "0",
        }

    def _summarize_mapped_results(self, mapped_results: List[MappedStatementResult]) -> Dict[str, Any]:
        summary = {
            "balance": {},
            "profit": {},
            "cashflow": {},
        }
        for result in mapped_results:
            summary[result.statement_type].update(
                result.to_serialized_view_data(include_empty=False)
            )
        return summary

    def _build_success_response(
        self,
        request_id: str,
        fns_id: str,
        fns_no: str,
        data: Dict[str, Any],
        statement_flags: Dict[str, str],
    ) -> Dict[str, Any]:
        return {
            "requestId": request_id,
            "fnsId": fns_id,
            "dealSts": DealStatus.SUCCESS.value,
            "fnsNo": fns_no,
            "dealRemark": "处理成功",
            "fnsItemBs": self._convert_to_json_compatible(data.get("balance", {})),
            "fnsItemIs": self._convert_to_json_compatible(data.get("profit", {})),
            "fnsItemCs": self._convert_to_json_compatible(data.get("cashflow", {})),
            "fnsItemBsFlag": statement_flags["fnsItemBsFlag"],
            "fnsItemIsFlag": statement_flags["fnsItemIsFlag"],
            "fnsItemCsFlag": statement_flags["fnsItemCsFlag"],
        }

    def _build_error_response(
        self,
        request_id: str,
        fns_id: str,
        fns_no: str,
        error_message: str,
    ) -> Dict[str, Any]:
        return {
            "requestId": request_id,
            "fnsId": fns_id,
            "dealSts": DealStatus.FAILED.value,
            "fnsNo": fns_no,
            "dealRemark": error_message,
            "fnsItemBs": {},
            "fnsItemIs": {},
            "fnsItemCs": {},
            "fnsItemBsFlag": "0",
            "fnsItemIsFlag": "0",
            "fnsItemCsFlag": "0",
        }

    def _convert_to_json_compatible(self, data: Dict[str, Any]) -> Dict[str, Any]:
        result = {}
        for key, value in data.items():
            result[key] = self._json_safe_value(value)
        return result

    def _json_safe_value(self, value: Any) -> Any:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, list):
            return [self._json_safe_value(item) for item in value]
        if value is None or value == "":
            return value
        return value

    def _save_failed_file(
        self,
        file_path: str,
        company_name: str,
        end_date: str,
        reason: str,
        issues: Optional[List[str]] = None,
        extracted_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        try:
            if not os.path.exists(file_path):
                self.logger.warning(f"要保存的失败文件不存在: {file_path}")
                return False

            file_name = os.path.basename(file_path)
            file_base_name = os.path.splitext(file_name)[0]
            s3_base_path = f"llm/fin_parse_failed/{datetime.now().strftime('%Y%m%d')}"
            s3_file_path = f"{s3_base_path}/{file_name}"

            file_success = S3Client.upload_file(
                local_file_path=file_path,
                s3_file_path=s3_file_path,
                days=30,
                config_key="llm_oss",
            )

            metadata_success = self._save_issue_metadata(
                s3_base_path=s3_base_path,
                file_name=file_base_name,
                company_name=company_name,
                end_date=end_date,
                reason=reason,
                issues=issues,
                extracted_data=extracted_data,
            )

            if file_success:
                self.logger.info(f"[LIFECYCLE] ✅ 失败文件已保存到 llm_oss: {s3_file_path}, 原因: {reason}")
                if metadata_success:
                    self.logger.info("✅ 问题详情元数据已保存")
            else:
                self.logger.error(f"❌ 保存失败文件到 llm_oss 失败: {file_path}")

            return file_success
        except Exception as exc:
            self.logger.error(f"保存失败文件异常: {exc}", exc_info=True)
            return False

    def _save_issue_metadata(
        self,
        s3_base_path: str,
        file_name: str,
        company_name: str,
        end_date: str,
        reason: str,
        issues: Optional[List[str]] = None,
        extracted_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        try:
            import tempfile

            metadata = {
                "file_name": file_name,
                "company_name": company_name,
                "end_date": end_date,
                "reason": reason,
                "issues": issues or [],
                "extracted_data": extracted_data or {},
                "timestamp": datetime.now().isoformat(),
            }

            fd, temp_path = tempfile.mkstemp(suffix=".json", prefix="issue_")
            os.close(fd)
            with open(temp_path, "w", encoding="utf-8") as file:
                json.dump(metadata, file, ensure_ascii=False, indent=2)

            s3_metadata_path = f"{s3_base_path}/{file_name}_issue.json"
            success = S3Client.upload_file(
                local_file_path=temp_path,
                s3_file_path=s3_metadata_path,
                days=30,
                config_key="llm_oss",
            )

            if os.path.exists(temp_path):
                os.remove(temp_path)
            return success
        except Exception as exc:
            self.logger.error(f"保存问题详情元数据异常: {exc}", exc_info=True)
            return False
