import unittest
from unittest import mock

from apps.fin_stmts_parse.src.core.contracts import MappedStatementResult, StatementMarkdownDocument
from apps.fin_stmts_parse_grpc.financial_report_service import FinancialReportService


class FinancialReportWorkflowServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = FinancialReportService.__new__(FinancialReportService)
        self.service.logger = mock.Mock()
        self.service.parse_core = mock.Mock()
        self.service.map_core = mock.Mock()
        self.service.inspect_core = mock.Mock()
        self.service._check_financial_statements_completeness = mock.Mock()

    def test_process_single_file_uses_core_parse_and_map(self) -> None:
        self.service.parse_core.parse_local_file.return_value = [
            StatementMarkdownDocument(
                table_name="资产负债表",
                date="202412",
                unit="元",
                is_consolidated=False,
                content="# 资产负债表\n\n| 项目 | 期末余额 |\n| --- | --- |\n| 货币资金 | 100 |",
                source_file_name="demo.pdf",
                source_file_path="/tmp/demo.pdf",
            )
        ]
        self.service.map_core.map_markdown_document.return_value = MappedStatementResult(
            statement_type="balance",
            table_name="资产负债表",
            date="202412",
            unit="元",
            canonical_data_full={"Z01010100": ["90.25", "100.5"]},
            view_data_full={"Z01010100": ["90.25", "100.5"]},
        )

        mapped_results = self.service._process_single_file(
            file_path="/tmp/demo.pdf",
            output_dir="/tmp/out",
            is_consolidated=False,
        )

        self.service.parse_core.parse_local_file.assert_called_once_with(
            "/tmp/demo.pdf",
            output_dir="/tmp/out",
            is_consolidated=False,
            report_period=None,
        )
        self.service.map_core.map_markdown_document.assert_called_once()
        self.assertEqual(len(mapped_results), 1)
        self.assertEqual(mapped_results[0].statement_type, "balance")
        self.service._check_financial_statements_completeness.assert_called_once()

    def test_process_single_file_uses_request_end_date_only_as_fallback(self) -> None:
        self.service.parse_core.parse_local_file.return_value = [
            StatementMarkdownDocument(
                table_name="资产负债表",
                date="N/A",
                unit="元",
                is_consolidated=False,
                content="# 资产负债表\n\n| 项目 | 期末余额 |\n| --- | --- |\n| 货币资金 | 100 |",
                source_file_name="demo.pdf",
                source_file_path="/tmp/demo.pdf",
            )
        ]
        self.service.map_core.map_markdown_document.return_value = MappedStatementResult(
            statement_type="balance",
            table_name="资产负债表",
            date="202312",
            unit="元",
            canonical_data_full={"Z01010100": ["90.25", "100.5"]},
            view_data_full={"Z01010100": ["90.25", "100.5"]},
        )

        self.service._process_single_file(
            file_path="/tmp/demo.pdf",
            output_dir="/tmp/out",
            is_consolidated=False,
            end_date="202312",
        )

        mapped_document = self.service.map_core.map_markdown_document.call_args.args[0]
        self.assertEqual(mapped_document.date, "202312")

    def test_process_single_file_does_not_override_detected_date_with_request_end_date(self) -> None:
        self.service.parse_core.parse_local_file.return_value = [
            StatementMarkdownDocument(
                table_name="资产负债表",
                date="202412",
                unit="元",
                is_consolidated=False,
                content="# 资产负债表\n\n| 项目 | 期末余额 |\n| --- | --- |\n| 货币资金 | 100 |",
                source_file_name="demo.pdf",
                source_file_path="/tmp/demo.pdf",
            )
        ]
        self.service.map_core.map_markdown_document.return_value = MappedStatementResult(
            statement_type="balance",
            table_name="资产负债表",
            date="202412",
            unit="元",
            canonical_data_full={"Z01010100": ["90.25", "100.5"]},
            view_data_full={"Z01010100": ["90.25", "100.5"]},
        )

        self.service._process_single_file(
            file_path="/tmp/demo.pdf",
            output_dir="/tmp/out",
            is_consolidated=False,
            end_date="202312",
        )

        mapped_document = self.service.map_core.map_markdown_document.call_args.args[0]
        self.assertEqual(mapped_document.date, "202412")

    def test_statement_presence_flags_follow_mapped_statement_types(self) -> None:
        flags = self.service._build_statement_presence_flags(
            [
                mock.Mock(statement_type="balance"),
                mock.Mock(statement_type="cashflow"),
            ]
        )

        self.assertEqual(
            flags,
            {
                "fnsItemBsFlag": "1",
                "fnsItemIsFlag": "0",
                "fnsItemCsFlag": "1",
            },
        )

    def test_error_response_marks_all_statements_absent(self) -> None:
        response = self.service._build_error_response(
            request_id="request-id",
            fns_id="fns-id",
            fns_no="FN191",
            error_message="failed",
        )

        self.assertEqual(response["fnsItemBsFlag"], "0")
        self.assertEqual(response["fnsItemIsFlag"], "0")
        self.assertEqual(response["fnsItemCsFlag"], "0")


if __name__ == "__main__":
    unittest.main()
