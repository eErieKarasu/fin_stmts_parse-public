import unittest

from apps.fin_stmts_parse.src.core.audit import FinancialStatementAuditFirmCore


class FinancialStatementAuditFirmCoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.core = FinancialStatementAuditFirmCore(config={})

    def test_text_with_unique_audit_firm_returns_audited(self) -> None:
        result = self.core.extract_from_text(
            """
审计报告

我们审计了测试公司的财务报表。

中兴华会计师事务所（特殊普通合伙）
中国注册会计师：张三
""",
            page=3,
        )

        self.assertEqual(result.audit_status, "audited")
        self.assertEqual(result.audit_firm_name, "中兴华会计师事务所（特殊普通合伙）")
        self.assertEqual(result.confidence, "high")
        self.assertEqual(result.evidence[0].page, 3)

    def test_text_with_unaudited_phrase_returns_unaudited(self) -> None:
        result = self.core.extract_from_text("本财务报表未经审计，仅供内部管理使用。")

        self.assertEqual(result.audit_status, "unaudited")
        self.assertEqual(result.audit_firm_name, "")
        self.assertEqual(result.confidence, "high")

    def test_text_without_audit_information_returns_unknown(self) -> None:
        result = self.core.extract_from_text("资产负债表\n编制单位：测试公司\n单位：元")

        self.assertEqual(result.audit_status, "unknown")
        self.assertEqual(result.audit_firm_name, "")
        self.assertEqual(result.confidence, "low")
        self.assertEqual(result.evidence, [])

    def test_multiple_audit_firm_candidates_return_unknown(self) -> None:
        result = self.core.extract_from_text(
            """
天健会计师事务所（特殊普通合伙）
中兴华会计师事务所（特殊普通合伙）
"""
        )

        self.assertEqual(result.audit_status, "unknown")
        self.assertEqual(result.audit_firm_name, "")
        self.assertEqual(result.confidence, "low")
        self.assertEqual(len(result.evidence), 2)


if __name__ == "__main__":
    unittest.main()
