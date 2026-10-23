import asyncio
import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from evaluate.run import (
    answer_key,
    answers,
    arguments,
    build_grpc_request,
    compare,
    evaluate,
    load_gold,
    mcp_prediction,
    parse_amount,
    summary,
)


def case_fixture():
    return {
        "file": "files/input.pdf",
        "company": "测试公司",
        "fns_no": "FN191",
        "end_date": "202503",
        "report_type": "QTR",
        "expected": {
            "balance": {"cash": {"name": "现金", "begin": "1.10", "end": "2.20"}},
            "profit": {
                "net": {"name": "净利润", "current": "-3.30"},
                "blank": {"name": "空白", "current": None},
            },
            "cashflow": {},
        },
    }


class GoldTests(unittest.TestCase):
    def test_synthetic_gold_format_is_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gold.json"
            path.write_text(json.dumps({"version": 2, "empty_values_equal_zero": True,
                                        "cases": [case_fixture()]}))
            cases = load_gold(path)
            self.assertEqual(len(cases), 1)
            self.assertEqual(sum(1 for _ in answers(cases[0])), 4)

    def test_bad_gold_is_rejected(self):
        case = case_fixture()
        del case["expected"]["profit"]["net"]["current"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gold.json"
            path.write_text(json.dumps({"version": 2, "empty_values_equal_zero": True, "cases": [case]}))
            with self.assertRaisesRegex(ValueError, "缺少金额"):
                load_gold(path)


class ScoringTests(unittest.TestCase):
    def test_missing_fields_and_failures_stay_in_denominator(self):
        case = case_fixture()
        partial = compare(case, {("balance", "cash", "begin"): "1.10"})
        self.assertEqual((partial["field_matched"], partial["field_total"]), (1, 4))
        good = compare(case, {answer_key(a): a["value"] for a in answers(case)})
        failed = compare(case, {}, failure="timeout")
        result = summary([good, failed])
        self.assertEqual(result["field_exact_match_rate"], .5)
        self.assertEqual(result["failed_cases"], 1)
        self.assertNotIn("numeric_field_total", good)
        self.assertNotIn("numeric_field_exact_match_rate", result)

    def test_amount_rules(self):
        self.assertEqual(parse_amount("(1,234.56)"), parse_amount("-1234.560"))
        for empty in (None, "", "-", "0.0"):
            self.assertEqual(parse_amount(empty), parse_amount("0"))
        for invalid in ("NaN", "Infinity", "bad", True):
            self.assertEqual(parse_amount(invalid)[0], "invalid")

    def test_mcp_selects_period_scope_and_current_value(self):
        def statement(scope, date, values):
            return {"table_type": "profit", "is_consolidated": scope, "date": date,
                    "view_data": [{"code": "net", "values": values}]}
        payload = [{"mapped_results": [
            statement(True, "202503", ["7", "8"]),
            statement(False, "202403", ["9", "10"]),
            statement(False, "2025-03-31", ["100", "-3.30"]),
        ]}]
        self.assertEqual(mcp_prediction(payload, case_fixture()), {("profit", "net", "current"): "-3.30"})

    def test_grpc_request_uses_gold_parameters(self):
        proto = SimpleNamespace(ParseRequest=lambda **values: values)
        request = build_grpc_request(1, case_fixture(), "/tmp/input.pdf", proto)
        self.assertEqual((request["fnsNo"], request["endDate"], request["reportType"]),
                         ("FN191", "202503", "QTR"))
        self.assertEqual(request["finFiles"][0]["fileUrl"], "/tmp/input.pdf")


class RunnerTests(unittest.TestCase):
    def run_fake(self, *, broken=False, connection_error=False, service_root=None):
        first = case_fixture()
        second = copy.deepcopy(first)
        second["file"] = "files/second.pdf"
        calls = []

        class Client:
            def __init__(self, args):
                pass

            async def __aenter__(self):
                if connection_error:
                    raise TimeoutError("connection")
                return self

            async def __aexit__(self, *exc):
                pass

            async def parse(self, case, file_path, index):
                calls.append(file_path)
                if broken and index == 1:
                    raise TimeoutError("parse")
                return {"fixture": True}, {answer_key(a): a["value"] for a in answers(case)}

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            argv = ["grpc", "--output", str(output)]
            if service_root:
                argv += ["--service-root", service_root]
            args = arguments(argv)
            with patch("evaluate.run.safe_source", return_value=Path("/tmp/input.pdf")):
                with contextlib.redirect_stdout(io.StringIO()):
                    code, _ = asyncio.run(evaluate(args, [first, second], client_factory=Client))
            report = json.loads(output.read_text())
        return code, report, calls

    def test_success_and_failure(self):
        code, report, calls = self.run_fake()
        self.assertEqual(code, 0)
        self.assertEqual(report["summary"]["field_exact_match_rate"], 1)
        self.assertEqual(calls, ["/tmp/input.pdf", "/tmp/input.pdf"])
        code, report, _ = self.run_fake(broken=True)
        self.assertEqual(code, 1)
        self.assertEqual(report["summary"]["field_exact_match_rate"], .5)

    def test_service_root_mapping(self):
        code, _, calls = self.run_fake(service_root="/workspace")
        self.assertEqual(code, 0)
        self.assertEqual(calls, ["/workspace/files/input.pdf", "/workspace/files/second.pdf"])

    def test_connection_failure_scores_all_cases(self):
        code, report, calls = self.run_fake(connection_error=True)
        self.assertEqual(code, 1)
        self.assertEqual(report["summary"]["failed_cases"], 2)
        self.assertEqual(calls, [])

    def test_invalid_arguments(self):
        with contextlib.redirect_stderr(io.StringIO()):
            for extra in (["--limit", "0"], ["--fail-under", "1.1"], ["--service-root", "relative"]):
                with self.assertRaises(SystemExit):
                    arguments(["grpc", *extra])


if __name__ == "__main__":
    unittest.main()
