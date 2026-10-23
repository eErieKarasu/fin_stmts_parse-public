import unittest

from apps.fin_stmts_parse.src.core.contracts import MappedStatementResult
from apps.fin_stmts_parse.src.persistence.contracts import FinancialStatementFactSource
from apps.fin_stmts_parse.src.persistence.fact_builder import FinancialStatementFactBuilder


class FinancialStatementFactBuilderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = FinancialStatementFactBuilder()

    def test_build_rows_maps_balance_values_to_begin_and_end_amounts(self) -> None:
        rows = self.builder.build_rows(
            session_id="session-1",
            report_status="0",
            sources=[
                self._make_source(
                    statement_type="balance",
                    date="202503",
                    is_consolidated=False,
                    canonical_data_full={"Z01010100": ["90.25", "100.5"]},
                    canonical_labels={"Z01010100": "货币资金"},
                )
            ],
        )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.company_name, "测试公司")
        self.assertEqual(row.item_name, "货币资金")
        self.assertEqual(row.fns_year, "2025")
        self.assertEqual(row.fns_cycle, "3")
        self.assertEqual(row.report_cycle_type, "QUATER")
        self.assertEqual(row.report_type, "1")
        self.assertEqual(row.begin_amt, "90.25")
        self.assertEqual(row.end_amt, "100.5")
        self.assertEqual(row.statement_type, "balance")
        self.assertEqual(row.file_name, "demo.pdf")

    def test_build_rows_maps_date_to_month_and_cycle_type(self) -> None:
        test_cases = [
            ("202501", "2025", "1", "MONTH"),
            ("202503", "2025", "3", "QUATER"),
            ("202506", "2025", "6", "INTERIM"),
            ("202509", "2025", "9", "QUATER"),
            ("202512", "2025", "12", "YEAR"),
            ("2025", "2025", "12", "YEAR"),
        ]

        for date_value, expected_year, expected_month, expected_cycle_type in test_cases:
            with self.subTest(date_value=date_value):
                row = self.builder.build_rows(
                    session_id="session-1",
                    report_status="0",
                    sources=[
                        self._make_source(
                            statement_type="profit",
                            date=date_value,
                            is_consolidated=False,
                            canonical_data_full={"L00000000": "1000.0"},
                            canonical_labels={"L00000000": "营业总收入"},
                        )
                    ],
                )[0]
                self.assertEqual(row.fns_year, expected_year)
                self.assertEqual(row.fns_cycle, expected_month)
                self.assertEqual(row.report_cycle_type, expected_cycle_type)

    def test_build_rows_reuses_shared_period_resolution(self) -> None:
        rows = self.builder.build_rows(
            session_id="session-1",
            report_status="0",
            sources=[
                self._make_source(
                    statement_type="profit",
                    date="202506",
                    is_consolidated=False,
                    canonical_data_full={"L00000000": "1000.0"},
                    canonical_labels={"L00000000": "营业总收入"},
                )
            ],
        )

        self.assertEqual(rows[0].report_cycle_type, "INTERIM")

    def test_build_rows_maps_profit_values_to_previous_and_current_amounts(self) -> None:
        rows = self.builder.build_rows(
            session_id="session-1",
            report_status="1",
            sources=[
                self._make_source(
                    statement_type="profit",
                    date="202412",
                    is_consolidated=True,
                    canonical_data_full={"L00000000": ["900.0", "1000.0"]},
                    canonical_labels={"L00000000": "营业总收入"},
                )
            ],
        )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.begin_amt, "900.0")
        self.assertEqual(row.end_amt, "1000.0")
        self.assertEqual(row.report_type, "2")
        self.assertEqual(row.report_status, "1")
        self.assertEqual(row.statement_type, "profit")

    def test_build_rows_sets_cashflow_statement_type(self) -> None:
        rows = self.builder.build_rows(
            session_id="session-1",
            report_status="1",
            sources=[
                self._make_source(
                    statement_type="cashflow",
                    date="202412",
                    is_consolidated=False,
                    canonical_data_full={"X01010000": ["77.7", "88.8"]},
                    canonical_labels={"X01010000": "销售商品、提供劳务收到的现金"},
                )
            ],
        )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.begin_amt, "77.7")
        self.assertEqual(row.end_amt, "88.8")
        self.assertEqual(row.statement_type, "cashflow")

    def test_build_rows_preserves_none_empty_and_zero_amounts(self) -> None:
        rows = self.builder.build_rows(
            session_id="session-1",
            report_status="0",
            sources=[
                self._make_source(
                    statement_type="balance",
                    date="202412",
                    is_consolidated=False,
                    canonical_data_full={
                        "Z01010100": [None, ""],
                        "Z01010101": ["", "0.0"],
                    },
                    canonical_labels={
                        "Z01010100": "货币资金",
                        "Z01010101": "交易性金融资产",
                    },
                )
            ],
        )

        self.assertEqual(len(rows), 2)
        self.assertIsNone(rows[0].begin_amt)
        self.assertEqual(rows[0].end_amt, "")
        self.assertEqual(rows[1].begin_amt, "")
        self.assertEqual(rows[1].end_amt, "0.0")

    def test_build_rows_encodes_unmatched_balance_item_as_double_null(self) -> None:
        rows = self.builder.build_rows(
            session_id="session-1",
            report_status="0",
            sources=[
                self._make_source(
                    statement_type="balance",
                    date="202412",
                    is_consolidated=False,
                    canonical_data_full={"Z01010100": None},
                    canonical_labels={"Z01010100": "货币资金"},
                )
            ],
        )

        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0].begin_amt)
        self.assertIsNone(rows[0].end_amt)

    @staticmethod
    def _make_source(
        *,
        statement_type: str,
        date: str,
        is_consolidated: bool,
        canonical_data_full: dict,
        canonical_labels: dict,
    ) -> FinancialStatementFactSource:
        table_name_by_type = {
            "balance": "资产负债表",
            "profit": "利润表",
            "cashflow": "现金流量表",
        }
        return FinancialStatementFactSource(
            mapped_result=MappedStatementResult(
                statement_type=statement_type,
                table_name=table_name_by_type[statement_type],
                date=date,
                is_consolidated=is_consolidated,
                canonical_data_full=canonical_data_full,
                canonical_labels=canonical_labels,
                source_file_name="demo.pdf",
            ),
            company_name="测试公司",
            file_name="demo.pdf",
            source_group_key="file-1",
        )


if __name__ == "__main__":
    unittest.main()
