from __future__ import annotations

from typing import Any, Dict, Iterable, List

from fin_stmts_parse.src.core.contracts import (
    InspectionResult,
    MappedStatementResult,
    STATEMENT_TYPES,
)
from fin_stmts_parse.src.financial_inspector import FinancialInspector


class FinancialStatementInspectCore:
    def __init__(self):
        self.inspector = FinancialInspector()

    def inspect_mapped_results(
        self,
        mapped_results: Iterable[MappedStatementResult],
    ) -> InspectionResult:
        mapped_result_list = list(mapped_results)
        merged_view_data = merge_mapped_results_by_statement_type(
            mapped_result_list,
            prefer="view",
        )
        merged_canonical_data = merge_mapped_results_by_statement_type(
            mapped_result_list,
            prefer="canonical",
        )
        input_statement_types = [
            statement_type
            for statement_type in STATEMENT_TYPES
            if merged_view_data[statement_type] or merged_canonical_data[statement_type]
        ]
        missing_statement_types = [
            statement_type
            for statement_type in STATEMENT_TYPES
            if statement_type not in input_statement_types
        ]

        if not mapped_result_list:
            return InspectionResult(
                passed=False,
                remark="",
                merged_data=merged_view_data,
                details=[],
                summary={
                    "input_statement_types": input_statement_types,
                    "missing_statement_types": missing_statement_types,
                    "total_checks": 0,
                    "passed_checks": 0,
                    "failed_checks": 0,
                    "skipped_checks": 0,
                },
            )

        inspection_result = self.inspector.inspect_view(
            merged_view_data,
            semantic_merged_data=merged_canonical_data,
        )
        return InspectionResult(
            passed=inspection_result.get("passed", False),
            remark=_build_inspection_remark(inspection_result),
            merged_data=merged_view_data,
            details=list(inspection_result.get("details", [])),
            summary={
                "input_statement_types": input_statement_types,
                "missing_statement_types": missing_statement_types,
                "total_checks": inspection_result.get("total_checks", 0),
                "passed_checks": inspection_result.get("passed_checks", 0),
                "failed_checks": inspection_result.get("failed_checks", 0),
                "skipped_checks": inspection_result.get("skipped_checks", 0),
            },
        )


def merge_mapped_results_by_statement_type(
    mapped_results: Iterable[MappedStatementResult],
    *,
    prefer: str = "view",
) -> Dict[str, Dict[str, Any]]:
    merged = {
        statement_type: {}
        for statement_type in STATEMENT_TYPES
    }
    for result in mapped_results:
        if prefer == "canonical":
            payload = result.canonical_data_full or result.view_data_full
        else:
            payload = result.view_data_full or result.canonical_data_full
        merged[result.statement_type].update(
            payload
        )
    return merged


def inspect_mapped_results(
    mapped_results: Iterable[MappedStatementResult],
) -> InspectionResult:
    return FinancialStatementInspectCore().inspect_mapped_results(mapped_results)


def _build_inspection_remark(inspection_result: Dict[str, Any]) -> str:
    if inspection_result.get("passed", True):
        return ""

    failed_items = [
        detail.get("check")
        for detail in inspection_result.get("details", [])
        if detail.get("result") == "fail" and detail.get("check")
    ]
    if not failed_items:
        return "勾稽校验未通过"
    return (
        f"勾稽校验: {inspection_result.get('failed_checks', 0)}项失败"
        f"({', '.join(failed_items)})"
    )
