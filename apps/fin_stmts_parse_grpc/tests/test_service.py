import sys
import unittest
from pathlib import Path
from unittest import mock


TESTS_DIR = Path(__file__).resolve().parent
APP_DIR = TESTS_DIR.parent
APPS_DIR = APP_DIR.parent
PROJECT_DIR = APPS_DIR.parent

for path in (PROJECT_DIR, APP_DIR, APPS_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from financial_report_service import DealStatus
from protos import fin_stmts_parse_pb2
from service import FinStmtsParse


class FinStmtsParseServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.servicer = FinStmtsParse()
        self.request = fin_stmts_parse_pb2.ParseRequest(
            requestId="request-id",
            fnsId="fns-id",
            fnsNo="FN191",
            finFiles=[{"fileName": "report.pdf", "fileUrl": "/tmp/report.pdf"}],
        )

    def _parse_result(self, result):
        financial_service = mock.Mock()
        financial_service.parse_financial_report.return_value = result
        with mock.patch.object(
            self.servicer,
            "_get_financial_service",
            return_value=financial_service,
        ):
            return self.servicer.parseFinStmts(self.request, context=None)

    def test_all_parts_succeeded(self) -> None:
        response = self._parse_result(
            {
                "fnsItemBs": {"BS001": ["100", "200"]},
                "fnsItemIs": {"IS001": ["300"]},
                "fnsItemCs": {"CS001": ["400"]},
                "fnsItemBsFlag": "1",
                "fnsItemIsFlag": "1",
                "fnsItemCsFlag": "1",
            }
        )

        self.assertEqual(response.dealSts, DealStatus.SUCCESS.value)
        self.assertEqual(response.dealRemark, "解析成功。")
        self.assertEqual(response.fnsItemBsFlag, "1")
        self.assertEqual(response.fnsItemIsFlag, "1")
        self.assertEqual(response.fnsItemCsFlag, "1")

    def test_some_parts_failed(self) -> None:
        response = self._parse_result(
            {
                "fnsItemBs": {"BS001": ["0.0", "200"]},
                "fnsItemIs": {"IS001": ["0.0"]},
                "fnsItemCs": {"CS001": ["400"]},
                "fnsItemBsFlag": "1",
                "fnsItemIsFlag": "1",
                "fnsItemCsFlag": "1",
            }
        )

        self.assertEqual(response.dealSts, DealStatus.PARTIAL_SUCCESS.value)
        self.assertEqual(
            response.dealRemark,
            "部分解析成功。资产负债表期初值解析失败、利润表解析失败。",
        )
        self.assertEqual(response.fnsItemBsFlag, "1")
        self.assertEqual(response.fnsItemIsFlag, "1")
        self.assertEqual(response.fnsItemCsFlag, "1")

    def test_all_parts_failed(self) -> None:
        response = self._parse_result(
            {
                "dealSts": DealStatus.FAILED.value,
                "dealRemark": "未能成功解析任何文件",
                "fnsItemBs": {},
                "fnsItemIs": {},
                "fnsItemCs": {},
                "fnsItemBsFlag": "0",
                "fnsItemIsFlag": "0",
                "fnsItemCsFlag": "0",
            }
        )

        self.assertEqual(response.dealSts, DealStatus.FAILED.value)
        self.assertEqual(
            response.dealRemark,
            "解析失败。资产负债表期初值解析失败、资产负债表期末值解析失败、"
            "利润表解析失败、现金流量表解析失败。",
        )
        self.assertEqual(response.fnsItemBsFlag, "0")
        self.assertEqual(response.fnsItemIsFlag, "0")
        self.assertEqual(response.fnsItemCsFlag, "0")

    def test_processing_exception_includes_failed_parts_and_reason(self) -> None:
        financial_service = mock.Mock()
        financial_service.parse_financial_report.side_effect = RuntimeError("模型调用超时")
        with mock.patch.object(
            self.servicer,
            "_get_financial_service",
            return_value=financial_service,
        ):
            response = self.servicer.parseFinStmts(self.request, context=None)

        self.assertEqual(response.dealSts, DealStatus.FAILED.value)
        self.assertEqual(
            response.dealRemark,
            "解析失败。资产负债表期初值解析失败、资产负债表期末值解析失败、"
            "利润表解析失败、现金流量表解析失败。原因：模型调用超时",
        )
        self.assertEqual(response.fnsItemBsFlag, "0")
        self.assertEqual(response.fnsItemIsFlag, "0")
        self.assertEqual(response.fnsItemCsFlag, "0")

    def test_processing_status_is_reserved(self) -> None:
        self.assertEqual(DealStatus.PROCESSING.value, "2")


if __name__ == "__main__":
    unittest.main()
