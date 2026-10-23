import unittest

from apps.fin_stmts_parse.src.core.contracts import MappedStatementResult
from apps.fin_stmts_parse.src.core.inspect import FinancialStatementInspectCore


class FinancialStatementInspectCoreTest(unittest.TestCase):
    def test_inspect_mapped_results_returns_balance_summary(self) -> None:
        result = FinancialStatementInspectCore().inspect_mapped_results(
            [
                MappedStatementResult(
                    statement_type="balance",
                    table_name="资产负债表",
                    canonical_data_full={
                        "Z01010001": [100, 120],
                        "Z01010100": [60, 70],
                        "Z01010610": [40, 50],
                    },
                    view_data_full={
                        "Z01010001": [100, 120],
                        "Z01010100": [60, 70],
                        "Z01010610": [40, 50],
                    },
                )
            ]
        )

        self.assertEqual(result.summary["input_statement_types"], ["balance"])
        self.assertEqual(result.summary["missing_statement_types"], ["profit", "cashflow"])
        self.assertFalse(result.passed)
        self.assertEqual(result.summary["total_checks"], 20)
        self.assertEqual(result.summary["passed_checks"], 2)
        self.assertEqual(result.summary["failed_checks"], 18)
        self.assertEqual(result.summary["skipped_checks"], 0)

    def test_inspect_mapped_results_prefers_view_data(self) -> None:
        result = FinancialStatementInspectCore().inspect_mapped_results(
            [
                MappedStatementResult(
                    statement_type="balance",
                    table_name="资产负债表",
                    canonical_data_full={
                        "Z01010001": [100, 100],
                        "Z01010100": [100, 100],
                    },
                    view_data_full={
                        "Z01010001": [100, 100],
                        "Z01010100": [90, 90],
                    },
                )
            ]
        )

        details = {detail["check"]: detail for detail in result.details}
        self.assertFalse(result.passed)
        self.assertEqual(details["流动资产合计(年初)"]["result"], "fail")
        self.assertEqual(
            [item["code"] for item in details["流动资产合计(年初)"]["suspects"]],
            ["Z01010001", "Z01010100"],
        )

    def test_inspect_mapped_results_uses_semantic_inference_to_explain_view_region_failure(self) -> None:
        result = FinancialStatementInspectCore().inspect_mapped_results(
            [
                MappedStatementResult(
                    statement_type="balance",
                    table_name="资产负债表",
                    canonical_data_full={
                        "Z01000001": [598345.12, 493072.44],
                        "Z01010001": [100000, 120000],
                        "ZY2015058": [498345.12, 373072.44],
                        "Z01030001": [659330.00, 659330.00],
                        "Z01030002": [260984.88, 386257.56],
                        "Z01030003": [398345.12, 273072.44],
                        "Z01030004": ["", ""],
                        "Z01030005": [0, 0],
                        "Z01040100": [100000, 100000],
                    },
                    view_data_full={
                        "ZY2015058": [498345.12, 373072.44],
                        "Z01030000": [0, 0],
                        "Z01040100": [100000, 100000],
                    },
                )
            ]
        )

        details = {detail["check"]: detail for detail in result.details}
        non_current_assets = details["非流动资产合计(期末)"]
        self.assertEqual(
            non_current_assets["reason"],
            "使用固定资产内部勾稽推理值后等式成立，疑似固定资产字段有误",
        )
        self.assertEqual(
            non_current_assets["semantic_attribution"]["culprit_code"],
            "Z01030000",
        )
        self.assertTrue(
            non_current_assets["semantic_attribution"]["validation_chain"]["supports_parent_check"]
        )
        self.assertIsNone(
            non_current_assets["semantic_attribution"]["validation_chain"]["supports_grandparent_check"]
        )

    def test_inspect_profit_mapped_results_returns_profit_summary(self) -> None:
        result = FinancialStatementInspectCore().inspect_mapped_results(
            [
                MappedStatementResult(
                    statement_type="profit",
                    table_name="利润表",
                    canonical_data_full={
                        "L00000000": [900, 1000],
                        "L02010100": [350, 400],
                        "L02010800": [8, 10],
                        "L02010900": [45, 50],
                        "L03040000": [55, 60],
                        "L02011000": [65, 70],
                        "L03050000": [18, 20],
                        "L02011100": [4, 5],
                        "L04020000": [12, 15],
                        "SY1000006": [1, 2],
                        "L02011200": [2, 3],
                        "SY1000016": [3, 4],
                        "SG5020000": [4, 5],
                        "L02011300": [5, 6],
                        "L04010000": [385, 430],
                        "L04050000": [15, 20],
                        "L04070000": [8, 10],
                        "L05010000": [392, 440],
                        "L04010100": [32, 40],
                        "L06010000": [360, 400],
                        "L05010200": [220, 250],
                        "L05010300": [140, 150],
                        "L06010100": [8, 10],
                        "L07000000": [368, 410],
                    },
                    view_data_full={
                        "L00000000": [900, 1000],
                        "L02010100": [350, 400],
                        "L02010800": [8, 10],
                        "L02010900": [45, 50],
                        "L03040000": [55, 60],
                        "L02011000": [65, 70],
                        "L03050000": [18, 20],
                        "L02011100": [4, 5],
                        "L04020000": [12, 15],
                        "SY1000006": [1, 2],
                        "L02011200": [2, 3],
                        "SY1000016": [3, 4],
                        "SG5020000": [4, 5],
                        "L02011300": [5, 6],
                        "L04010000": [385, 430],
                        "L04050000": [15, 20],
                        "L04070000": [8, 10],
                        "L05010000": [392, 440],
                        "L04010100": [32, 40],
                        "L06010000": [360, 400],
                        "L05010200": [220, 250],
                        "L05010300": [140, 150],
                        "L06010100": [8, 10],
                        "L07000000": [368, 410],
                    },
                )
            ]
        )

        self.assertEqual(result.summary["input_statement_types"], ["profit"])
        self.assertEqual(result.summary["missing_statement_types"], ["balance", "cashflow"])
        self.assertTrue(result.passed)
        self.assertEqual(result.summary["total_checks"], 5)
        self.assertEqual(result.summary["passed_checks"], 5)
        self.assertEqual(result.summary["failed_checks"], 0)
        self.assertEqual(result.summary["skipped_checks"], 0)

    def test_inspect_cashflow_mapped_results_returns_cashflow_summary(self) -> None:
        result = FinancialStatementInspectCore().inspect_mapped_results(
            [
                MappedStatementResult(
                    statement_type="cashflow",
                    table_name="现金流量表",
                    canonical_data_full={
                        "X01040000": [115],
                        "X01010000": [100],
                        "X01020000": [10],
                        "X01030000": [5],
                        "X01090000": [140],
                        "X01050000": [90],
                        "X01060000": [20],
                        "X01070000": [10],
                        "X01011800": [20],
                        "X01100000": [-25],
                        "X02050000": [45],
                        "X02010000": [20],
                        "X02020000": [5],
                        "X02030000": [10],
                        "X02030100": [4],
                        "X02040000": [6],
                        "X02090000": [31],
                        "X02060000": [11],
                        "X02070000": [7],
                        "X02080200": [5],
                        "X02080300": [8],
                        "X02100000": [14],
                        "X03040000": [95],
                        "X03010000": [30],
                        "X02080500": [40],
                        "X03020100": [15],
                        "X03030000": [10],
                        "X03080000": [60],
                        "X03050000": [25],
                        "X03060000": [20],
                        "X03070000": [15],
                        "X03090000": [35],
                    },
                    view_data_full={
                        "X01040000": [115],
                        "X01010000": [100],
                        "X01020000": [10],
                        "X01030000": [5],
                        "X01090000": [140],
                        "X01050000": [90],
                        "X01060000": [20],
                        "X01070000": [10],
                        "X01011800": [20],
                        "X01100000": [-25],
                        "X02050000": [45],
                        "X02010000": [20],
                        "X02020000": [5],
                        "X02030000": [10],
                        "X02030100": [4],
                        "X02040000": [6],
                        "X02090000": [31],
                        "X02060000": [11],
                        "X02070000": [7],
                        "X02080200": [5],
                        "X02080300": [8],
                        "X02100000": [14],
                        "X03040000": [95],
                        "X03010000": [30],
                        "X02080500": [40],
                        "X03020100": [15],
                        "X03030000": [10],
                        "X03080000": [60],
                        "X03050000": [25],
                        "X03060000": [20],
                        "X03070000": [15],
                        "X03090000": [35],
                    },
                )
            ]
        )

        self.assertEqual(result.summary["input_statement_types"], ["cashflow"])
        self.assertEqual(result.summary["missing_statement_types"], ["balance", "profit"])
        self.assertTrue(result.passed)
        self.assertEqual(result.summary["total_checks"], 9)
        self.assertEqual(result.summary["passed_checks"], 9)
        self.assertEqual(result.summary["failed_checks"], 0)
        self.assertEqual(result.summary["skipped_checks"], 0)

    def test_inspect_empty_results_returns_zero_summary(self) -> None:
        result = FinancialStatementInspectCore().inspect_mapped_results([])

        self.assertFalse(result.passed)
        self.assertEqual(result.summary["total_checks"], 0)
        self.assertEqual(result.merged_data["balance"], {})


if __name__ == "__main__":
    unittest.main()
