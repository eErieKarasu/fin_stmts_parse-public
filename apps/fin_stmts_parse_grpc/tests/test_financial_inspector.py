#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from decimal import Decimal
from pathlib import Path
import sys
import unittest


TESTS_DIR = Path(__file__).resolve().parent
APP_DIR = TESTS_DIR.parent
APPS_DIR = APP_DIR.parent

for path in (APP_DIR, APPS_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from fin_stmts_parse.src.financial_inspector import FinancialInspector


class FinancialInspectorTest(unittest.TestCase):
    def setUp(self):
        self.inspector = FinancialInspector()

    def test_check_sum_rule_distinguishes_unmatched_and_zero(self):
        data = {
            "Z02000001": [Decimal("0"), Decimal("100")],
            "Z02010001": [Decimal("0"), Decimal("100")],
            "Z02020000": [Decimal("0"), Decimal("0")],
            "ZY2015061": ["", ""],
        }
        rule = {
            "name": "负债合计",
            "total_code": "Z02000001",
            "component_codes": ["Z02010001", "Z02020000", "ZY2015061"],
        }

        detail = self.inspector._check_sum_rule(data, rule, 1, "期末")

        self.assertEqual(detail["components"]["Z02010001"]["value"], Decimal("100"))
        self.assertEqual(detail["components"]["Z02020000"]["value"], Decimal("0"))
        self.assertIsNone(detail["components"]["ZY2015061"]["value"])
        self.assertEqual(detail["_matched_component_count"], 2)
        self.assertEqual(detail["_missing_component_count"], 1)
        self.assertEqual(detail["missing"], [{"code": "ZY2015061", "name": "非流动负债合计"}])

    def test_variant_prefers_track_with_markdown_hit(self):
        data = {
            "Z02000001": [Decimal("0"), Decimal("200")],
            "Z02010001": [Decimal("0"), Decimal("100")],
            "ZY2015061": ["", ""],
            "Z02020000": [Decimal("0"), Decimal("0")],
            "Z01044104": ["", Decimal("90")],
        }
        rule = next(r for r in self.inspector.BALANCE_RULES if r["name"] == "负债合计")

        detail = self.inspector._check_rule(data, rule, 1, "期末")

        self.assertEqual(detail["result"], "fail")
        self.assertIn("Z02020000", detail["components"])
        self.assertIn("Z01044104", detail["components"])
        self.assertNotIn("ZY2015061", detail["components"])

    def test_track_resolution_prefers_markdown_supported_fail_track(self):
        data = {
            "ZY2015061": [Decimal("0"), Decimal("100")],
            "Z02020100": [Decimal("0"), Decimal("0")],
            "Z02020300": ["", ""],
            "L02060000": ["", ""],
            "Z02011500": ["", ""],
            "Z02020000": [Decimal("0"), Decimal("100")],
            "Z02020200": [Decimal("0"), Decimal("0")],
            "Z02020400": ["", ""],
            "Z02020500": [Decimal("0"), Decimal("0")],
        }

        rules = [
            next(r for r in self.inspector.BALANCE_RULES if r["name"] == "非流动负债合计"),
            next(r for r in self.inspector.BALANCE_RULES if r["name"] == "长期负债合计"),
        ]

        details = []
        for rule in rules:
            detail = self.inspector._check_rule(data, rule, 1, "期末")
            detail["_group"] = rule.get("group")
            detail["_track"] = rule.get("track")
            detail["_period_idx"] = 1
            details.append(detail)

        self.assertEqual(details[0]["result"], "fail")
        self.assertEqual(details[1]["result"], "fail")

        self.inspector._resolve_track_groups(details)

        self.assertEqual(details[0]["result"], "skip")
        self.assertEqual(details[0]["reason"], "替代轨更贴近markdown命中")
        self.assertEqual(details[1]["result"], "fail")


if __name__ == "__main__":
    unittest.main()
