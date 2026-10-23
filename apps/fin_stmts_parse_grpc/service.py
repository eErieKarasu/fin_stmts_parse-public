import os
import uuid
from datetime import datetime
from typing import Dict, List, Tuple

from google.protobuf.json_format import MessageToDict

from protos import fin_stmts_parse_pb2, fin_stmts_parse_pb2_grpc
from financial_report_service import DealStatus, FinancialReportService

from fin_stmts_parse.exceptions.base_exception import ServiceError
from fin_stmts_parse.utils.logger import logger, setup_logging
from fin_stmts_parse.utils.read_yaml import load_env_config


setup_logging()


class FinStmtsParse(fin_stmts_parse_pb2_grpc.FinStmtsParseServicer):
    _financial_service = None
    _financial_service_config_env = None

    def _build_fixed_fields(self, request, seri_no: str) -> Dict[str, str]:
        return {
            "tranCode": "aihelper@aiFnsCallback",
            "chanId": "llm",
            "sysId": "llm",
            "pubGloblJnno": request.pubGloblJnno,
            "seriNo": seri_no,
            "reqBizDate": datetime.now().strftime("%Y-%m-%d"),
            "tranCounter": "system",
            "orgNo": "00001",
            "protocol": "http",
            "preReverseFlag": "0",
            "legalCode": "9999",
            "headVerNo": "1.0.0",
            "preSysId": "llm",
            "preSerialNo": seri_no,
            "preReqVerNo": "1.0.0",
            "preSubFlag": "0",
            "requestId": request.requestId,
            "fnsId": request.fnsId,
            "fnsNo": request.fnsNo,
        }

    def _build_service_request(self, request, seri_no: str) -> Dict:
        return {
            "pubGloblJnno": request.pubGloblJnno,
            "seriNo": seri_no,
            "requestID": request.requestId,
            "fnsId": request.fnsId,
            "fnsNo": request.fnsNo,
            "companyName": getattr(request, "companyName", ""),
            "reportType": getattr(request, "reportType", ""),
            "endDate": getattr(request, "endDate", ""),
            "fileUrls": getattr(request, "finFiles", []),
        }

    def _get_financial_service(self) -> FinancialReportService:
        env = os.getenv("RUNNING_ENV", "local")
        if (
            FinStmtsParse._financial_service is None
            or FinStmtsParse._financial_service_config_env != env
        ):
            config = load_env_config(env)
            FinStmtsParse._financial_service = FinancialReportService(config)
            FinStmtsParse._financial_service_config_env = env
        return FinStmtsParse._financial_service

    def _check_params(self, request) -> List[str]:
        check_results = []

        if not all([request.requestId, request.fnsId, request.fnsNo]):
            check_results.append("缺少必填参数！")

        if not hasattr(request, "finFiles") or len(request.finFiles) == 0:
            check_results.append("请上传财报资料！")

        if request.fnsNo not in ["FN191", "FN192"]:
            check_results.append(f"无效的财务报表代号: {request.fnsNo}，应为FN191或FN192！")

        return check_results

    def _build_error_response(self, seri_no, request, message):
        fixed_fields = self._build_fixed_fields(request, seri_no)
        return fin_stmts_parse_pb2.ParseReply(
            **fixed_fields,
            dealSts=DealStatus.FAILED.value,
            dealRemark=message,
            fnsItemBsBegin={},
            fnsItemBsEnd={},
            fnsItemIs={},
            fnsItemCs={},
            fnsItemBsFlag="0",
            fnsItemIsFlag="0",
            fnsItemCsFlag="0",
        )

    def _build_parse_response(
        self,
        seri_no,
        request,
        deal_status,
        deal_remark,
        item_bs_begin,
        item_bs_end,
        item_is,
        item_cs,
        item_bs_flag,
        item_is_flag,
        item_cs_flag,
    ):
        fixed_fields = self._build_fixed_fields(request, seri_no)
        return fin_stmts_parse_pb2.ParseReply(
            **fixed_fields,
            dealSts=deal_status,
            dealRemark=deal_remark,
            fnsItemBsBegin=item_bs_begin,
            fnsItemBsEnd=item_bs_end,
            fnsItemIs=item_is,
            fnsItemCs=item_cs,
            fnsItemBsFlag=item_bs_flag,
            fnsItemIsFlag=item_is_flag,
            fnsItemCsFlag=item_cs_flag,
        )

    @staticmethod
    def _normalize_statement_flag(value) -> str:
        return "1" if str(value or "").strip() == "1" else "0"

    @staticmethod
    def _normalize_legacy_scalar(value, missing_placeholder: str = "0.0") -> str:
        if value is None:
            return missing_placeholder

        text = str(value).strip()
        if text == "":
            return missing_placeholder
        return text

    def _split_legacy_result(self, result: Dict) -> Dict[str, Dict[str, str]]:
        fns_item_bs_begin = {}
        fns_item_bs_end = {}

        for code, value in result.get("fnsItemBs", {}).items():
            if isinstance(value, list):
                begin_value = value[0] if len(value) > 0 else None
                end_value = value[1] if len(value) > 1 else None
                fns_item_bs_begin[code] = self._normalize_legacy_scalar(begin_value)
                fns_item_bs_end[code] = self._normalize_legacy_scalar(end_value)
            else:
                fns_item_bs_begin[code] = "0.0"
                fns_item_bs_end[code] = "0.0"

        fns_item_is = {
            code: self._normalize_legacy_scalar(
                value[-1] if isinstance(value, list) and value else value
            )
            for code, value in result.get("fnsItemIs", {}).items()
        }
        fns_item_cs = {
            code: self._normalize_legacy_scalar(
                value[-1] if isinstance(value, list) and value else value
            )
            for code, value in result.get("fnsItemCs", {}).items()
        }

        return {
            "fnsItemBsBegin": fns_item_bs_begin,
            "fnsItemBsEnd": fns_item_bs_end,
            "fnsItemIs": fns_item_is,
            "fnsItemCs": fns_item_cs,
        }

    def _has_valid_data(self, data_dict):
        if not data_dict:
            return False

        for value in data_dict.values():
            if value and value != "0.0" and value.strip() != "":
                try:
                    if float(value) != 0.0:
                        return True
                except (ValueError, AttributeError):
                    return True

        return False

    def _generate_parse_status_and_remark(
        self,
        item_bs_begin,
        item_bs_end,
        item_is,
        item_cs,
    ) -> Tuple[str, str]:
        parse_parts = [
            ("资产负债表期初值", self._has_valid_data(item_bs_begin)),
            ("资产负债表期末值", self._has_valid_data(item_bs_end)),
            ("利润表", self._has_valid_data(item_is)),
            ("现金流量表", self._has_valid_data(item_cs)),
        ]
        failed_parts = [
            f"{part_name}解析失败"
            for part_name, succeeded in parse_parts
            if not succeeded
        ]

        if not failed_parts:
            return DealStatus.SUCCESS.value, "解析成功。"

        failure_detail = "、".join(failed_parts) + "。"
        if len(failed_parts) == len(parse_parts):
            return DealStatus.FAILED.value, f"解析失败。{failure_detail}"

        return DealStatus.PARTIAL_SUCCESS.value, f"部分解析成功。{failure_detail}"

    def _build_processing_error_remark(self, message: str) -> str:
        _, parse_failure_remark = self._generate_parse_status_and_remark(
            {},
            {},
            {},
            {},
        )
        if not message:
            return parse_failure_remark
        return f"{parse_failure_remark}原因：{message}"

    def parseFinStmts(self, request, context):
        logger.info("请求参数：{}", MessageToDict(request, preserving_proto_field_name=True))
        seri_no = str(uuid.uuid4())

        check_results = self._check_params(request)
        if check_results:
            return self._build_error_response(seri_no, request, ";".join(check_results))

        try:
            financial_service = self._get_financial_service()
            result = financial_service.parse_financial_report(
                self._build_service_request(request, seri_no)
            ) or {}

            split_result = self._split_legacy_result(result)
            deal_status, deal_remark = self._generate_parse_status_and_remark(
                split_result["fnsItemBsBegin"],
                split_result["fnsItemBsEnd"],
                split_result["fnsItemIs"],
                split_result["fnsItemCs"],
            )

            response = self._build_parse_response(
                seri_no,
                request,
                deal_status=deal_status,
                deal_remark=deal_remark,
                item_bs_begin=split_result["fnsItemBsBegin"],
                item_bs_end=split_result["fnsItemBsEnd"],
                item_is=split_result["fnsItemIs"],
                item_cs=split_result["fnsItemCs"],
                item_bs_flag=self._normalize_statement_flag(result.get("fnsItemBsFlag")),
                item_is_flag=self._normalize_statement_flag(result.get("fnsItemIsFlag")),
                item_cs_flag=self._normalize_statement_flag(result.get("fnsItemCsFlag")),
            )
        except ServiceError as exc:
            response = self._build_error_response(
                seri_no,
                request,
                self._build_processing_error_remark(exc.message),
            )
        except Exception as exc:
            response = self._build_error_response(
                seri_no,
                request,
                self._build_processing_error_remark(str(exc)),
            )

        logger.info("返回结果：{}", response)
        return response
