import unittest
from datetime import datetime
from unittest import mock

from apps.fin_stmts_parse.src.markdown_table_extractor import MarkdownTableExtractor
from apps.fin_stmts_parse.src.statement_metadata_resolver import (
    StatementMetadataResolver,
    StatementPageMetadata,
)


class StatementMetadataResolverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.table_extractor = MarkdownTableExtractor(llm_client=None)
        self.resolver = StatementMetadataResolver(
            date_parser=self.table_extractor.parse_date_from_header,
            markdown_metadata_extractor=self.table_extractor.extract_metadata_from_markdown,
            logger=mock.Mock(),
        )

    def test_normalize_metadata_supports_aliases_and_candidate_evidence(self) -> None:
        metadata = self.resolver.normalize_metadata({
            "表名": " # 利润表 # ",
            "accountingForm": " 会计02表 ",
            "companyName": " 测试有限公司 ",
            "日期": "202603",
            "单位": " 万元 ",
            "confidence": "高",
            "dateSource": "file_name",
            "dateCandidates": [{
                "date": "202603", "source": "file_name", "confidence": "高", "weight": "95",
            }],
            "dateWarnings": [" 日期冲突 ", "日期冲突"],
        })

        self.assertEqual(metadata.title, "利润表")
        self.assertEqual(metadata.accounting_form, "会计02表")
        self.assertEqual(metadata.company_name, "测试有限公司")
        self.assertEqual(metadata.date, "202603")
        self.assertEqual(metadata.unit, "万元")
        self.assertEqual(metadata.confidence, "high")
        self.assertEqual(metadata.date_source, "file_name")
        self.assertEqual(metadata.date_candidates[0]["weight"], 95.0)
        self.assertEqual(metadata.date_warnings, ("日期冲突",))

    def test_normalize_metadata_reuses_existing_page_metadata(self) -> None:
        metadata = StatementPageMetadata(date="202603", unit="元")

        self.assertIs(self.resolver.normalize_metadata(metadata), metadata)

    def test_normalization_rejects_non_mapping_inputs(self) -> None:
        for value in (None, "not a metadata object", [], 123):
            with self.subTest(value=value):
                self.assertEqual(self.resolver.normalize_metadata(value), StatementPageMetadata())
                self.assertEqual(self.resolver.normalize_vl_response(value), StatementPageMetadata())

    def test_normalize_vl_response_keeps_raw_date_priority_and_aliases(self) -> None:
        metadata = self.resolver.normalize_vl_response({
            "title": "利润表",
            "accountingForm": "会计02表",
            "companyName": "编制单位：测试有限公司",
            "dateRaw": "2026年1-3月",
            "date": "202512",
            "unit": "万元",
            "confidence": "高",
        }, "利润表")

        self.assertEqual(metadata.company_name, "测试有限公司")
        self.assertEqual(metadata.accounting_form, "会计02表")
        self.assertEqual(metadata.date, "202603")
        self.assertEqual(metadata.date_raw, "2026年1-3月")
        self.assertEqual(metadata.unit, "万元")
        self.assertEqual(metadata.confidence, "high")
        self.assertEqual(metadata.date_source, "vl_metadata")
        self.assertEqual({candidate["date"] for candidate in metadata.date_candidates}, {"202603", "202512"})
        self.assertTrue(metadata.date_warnings)

    def test_needs_vl_recheck_only_for_missing_fields_or_date_conflict(self) -> None:
        cases = [
            ({"date": "202603", "unit": "元"}, None, False),
            ({"date": "202603", "unit": "元"}, {"date": "202603"}, False),
            ({"date": "202603", "unit": "元"}, {"date": "202512"}, True),
            ({"date": "202603"}, None, True),
            ({"unit": "元"}, None, True),
        ]
        for metadata, file_metadata, expected in cases:
            with self.subTest(metadata=metadata, file_metadata=file_metadata):
                self.assertEqual(self.resolver.needs_vl_recheck(metadata, file_metadata), expected)

    def test_resolves_text_with_only_injected_parsing_functions(self) -> None:
        date_parser = mock.Mock(return_value=datetime(2026, 3, 31))
        metadata_extractor = mock.Mock(return_value={"单位": "万元"})
        resolver = StatementMetadataResolver(
            date_parser=date_parser,
            markdown_metadata_extractor=metadata_extractor,
        )
        text = "利润表\n编制单位：测试有限公司\n2026年1-3月"

        metadata = resolver.extract_statement_metadata_from_text(text, "利润表")

        self.assertEqual(metadata.date, "202603")
        self.assertEqual(metadata.date_raw, "2026年1-3月")
        self.assertEqual(metadata.company_name, "测试有限公司")
        self.assertEqual(metadata.unit, "万元")
        date_parser.assert_called_once_with("2026年1-3月")
        metadata_extractor.assert_called_once_with(text)

    def test_date_parser_failure_preserves_unknown_explicit_date(self) -> None:
        resolver = StatementMetadataResolver(
            date_parser=mock.Mock(side_effect=ValueError("invalid date")),
            markdown_metadata_extractor=lambda text: {"日期": "202512", "单位": "元"},
        )

        metadata = resolver.extract_statement_metadata_from_text("利润表\n2025年第13期")

        self.assertEqual(metadata.date_raw, "2025年第13期")
        self.assertEqual(metadata.date, "N/A")
        self.assertEqual(metadata.date_candidates, ())
        self.assertEqual(metadata.unit, "元")

    def test_extracts_profit_header_metadata_from_markdown_text(self) -> None:
        metadata = self.resolver.extract_statement_metadata_from_text(
            """
            # 损 益 表
            会计02表
            编制单位：示例企业060 2023年度 单位：元

            | 项目 | 行次 | 本年累计数 | 上年年末数 |
            | --- | --- | --- | --- |
            | 一、营业收入 |  | 51,042,173.20 | 42,051,630.75 |
            """,
            table_type="利润表",
        )

        self.assertEqual(metadata.title, "损 益 表")
        self.assertEqual(metadata.accounting_form, "会计02表")
        self.assertEqual(metadata.company_name, "示例企业060")
        self.assertEqual(metadata.date_raw, "2023年度")
        self.assertEqual(metadata.date, "202312")
        self.assertEqual(metadata.unit, "元")

    def test_extracts_balance_header_metadata_from_markdown_text(self) -> None:
        metadata = self.resolver.extract_statement_metadata_from_text(
            """
            资产负债表
            会企01表
            编制单位：示例企业060
            2023年12月31日
            金额单位：元

            | 资产 | 年初余额 | 期末余额 |
            | --- | --- | --- |
            | 货币资金 | 14,157,382.11 | 24,251,885.02 |
            """,
            table_type="资产负债表",
        )

        self.assertEqual(metadata.title, "资产负债表")
        self.assertEqual(metadata.accounting_form, "会企01表")
        self.assertEqual(metadata.company_name, "示例企业060")
        self.assertEqual(metadata.date_raw, "2023年12月31日")
        self.assertEqual(metadata.date, "202312")
        self.assertEqual(metadata.unit, "元")

    def test_extracts_range_period_header_metadata_from_markdown_text(self) -> None:
        metadata = self.resolver.extract_statement_metadata_from_text(
            """
            # 利润表
            编制单位：测试有限公司 2026年1-3月 单位：万元

            | 项目 | 本期金额 |
            | --- | --- |
            | 一、营业收入 | 100 |
            """,
            table_type="利润表",
        )

        self.assertEqual(metadata.date_raw, "2026年1-3月")
        self.assertEqual(metadata.date, "202603")
        self.assertEqual(metadata.unit, "万元")

    def test_markdown_metadata_extracts_range_period_as_end_month(self) -> None:
        metadata = self.table_extractor.extract_metadata_from_markdown(
            "编制单位：测试有限公司 2026年1-3月 单位：元"
        )

        self.assertEqual(metadata["日期"], "202603")

    def test_extracts_issue_period_header_metadata_as_month(self) -> None:
        metadata = self.resolver.extract_statement_metadata_from_text(
            """
            # 利润表
            编制单位：测试有限公司 2025年第3期 单位：元

            | 项目 | 本期金额 |
            | --- | --- |
            | 一、营业收入 | 100 |
            """,
            table_type="利润表",
        )

        self.assertEqual(metadata.date_raw, "2025年第3期")
        self.assertEqual(metadata.date, "202503")

    def test_markdown_metadata_extracts_issue_period_as_month(self) -> None:
        metadata = self.table_extractor.extract_metadata_from_markdown(
            "编制单位：测试有限公司 2025年03期 单位：元"
        )

        self.assertEqual(metadata["日期"], "202503")

    def test_invalid_issue_period_does_not_fallback_to_year_end(self) -> None:
        statement_metadata = self.resolver.extract_statement_metadata_from_text(
            "编制单位：测试有限公司 2025年第13期 单位：元",
            table_type="利润表",
        )
        markdown_metadata = self.table_extractor.extract_metadata_from_markdown(
            "编制单位：测试有限公司 2025年第13期 单位：元"
        )

        self.assertEqual(statement_metadata.date_raw, "2025年第13期")
        self.assertEqual(statement_metadata.date, "N/A")
        self.assertEqual(markdown_metadata["日期"], "N/A")

    def test_extracts_date_metadata_from_filename(self) -> None:
        examples = {
            "2026年3月报表.pdf": "202603",
            "26年3月即期财报.pdf": "202603",
            "2026年1-3月报表.pdf": "202603",
            "2025年第3期报表.pdf": "202503",
            "demo_2026-03.pdf": "202603",
            "demo_202603.pdf": "202603",
        }

        for file_name, expected_date in examples.items():
            with self.subTest(file_name=file_name):
                metadata = self.resolver.extract_statement_metadata_from_filename(
                    file_name,
                    table_type="利润表",
                )

                self.assertEqual(metadata.date, expected_date)
                self.assertEqual(metadata.date_source, "file_name")
                self.assertEqual(metadata.date_candidates[0]["source"], "file_name")

    def test_filename_invalid_issue_period_is_ignored(self) -> None:
        metadata = self.resolver.extract_statement_metadata_from_filename(
            "2025年第13期报表.pdf",
            table_type="利润表",
        )

        self.assertEqual(metadata.date, "N/A")
        self.assertEqual(metadata.date_candidates, ())

    def test_metadata_conflict_with_filename_requires_vl_recheck(self) -> None:
        page_metadata = self.resolver.extract_statement_metadata_from_text(
            "资产负债表\n2024 年 3 月\n单位：元",
            table_type="资产负债表",
        )
        file_metadata = self.resolver.extract_statement_metadata_from_filename(
            "2026年3月报表.pdf",
            table_type="资产负债表",
        )

        self.assertTrue(
            self.resolver.needs_vl_recheck(page_metadata, file_metadata)
        )

    def test_resolves_filename_date_over_conflicting_markdown_without_vl(self) -> None:
        page_metadata = self.resolver.extract_statement_metadata_from_text(
            "资产负债表\n2024 年 3 月\n单位：元",
            table_type="资产负债表",
        )
        file_metadata = self.resolver.extract_statement_metadata_from_filename(
            "2026年3月报表.pdf",
            table_type="资产负债表",
        )
        merged = self.resolver.merge_statement_metadata(page_metadata, file_metadata)

        resolved = self.resolver.resolve_statement_metadata_date(
            merged,
            file_metadata,
        )

        self.assertEqual(resolved.date, "202603")
        self.assertEqual(resolved.date_source, "file_name")
        self.assertTrue(resolved.date_warnings)

    def test_vl_metadata_wins_over_filename_when_available(self) -> None:
        page_metadata = self.resolver.extract_statement_metadata_from_text(
            "资产负债表\n2024 年 3 月\n单位：元",
            table_type="资产负债表",
        )
        file_metadata = self.resolver.extract_statement_metadata_from_filename(
            "2026年3月报表.pdf",
            table_type="资产负债表",
        )
        vl_metadata = StatementPageMetadata(
            date_raw="2024年3月31日",
            date="202403",
            source="vl_metadata",
            confidence="high",
            date_source="vl_metadata",
            date_candidates=(
                {
                    "date": "202403",
                    "raw": "2024年3月31日",
                    "source": "vl_metadata",
                    "confidence": "high",
                    "weight": 110,
                },
            ),
        )
        merged = self.resolver.merge_statement_metadata(
            page_metadata,
            file_metadata,
            vl_metadata,
        )

        resolved = self.resolver.resolve_statement_metadata_date(
            merged,
            file_metadata,
            vl_metadata,
        )

        self.assertEqual(resolved.date, "202403")
        self.assertEqual(resolved.date_source, "vl_metadata")

    def test_file_level_vote_repairs_conflicting_table_date(self) -> None:
        balance_metadata = self.resolver.extract_statement_metadata_from_text(
            "资产负债表\n2026年3月31日\n单位：元",
            table_type="资产负债表",
        )
        profit_metadata = self.resolver.extract_statement_metadata_from_text(
            "利润表\n2026年1-3月\n单位：元",
            table_type="利润表",
        )
        cashflow_metadata = self.resolver.extract_statement_metadata_from_text(
            "现金流量表\n2024年1-3月\n单位：元",
            table_type="现金流量表",
        )

        vote_metadata = self.resolver.resolve_file_level_statement_date_metadata(
            [balance_metadata, profit_metadata, cashflow_metadata],
        )
        resolved_cashflow = self.resolver.resolve_statement_metadata_date(
            cashflow_metadata,
            vote_metadata,
        )

        self.assertEqual(vote_metadata.date, "202603")
        self.assertEqual(resolved_cashflow.date, "202603")
        self.assertTrue(vote_metadata.date_warnings)

    def test_merge_keeps_high_confidence_date_over_low_confidence(self) -> None:
        merged = self.resolver.merge_statement_metadata(
            StatementPageMetadata(date="202312", source="markdown", confidence="high"),
            StatementPageMetadata(date="202406", source="request", confidence="low"),
        )

        self.assertEqual(merged.date, "202312")


if __name__ == "__main__":
    unittest.main()
