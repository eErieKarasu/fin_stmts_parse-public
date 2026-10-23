import unittest
from unittest import mock

from apps.fin_stmts_parse.src.base_financial_processor import (
    BaseFinancialProcessor,
    StatementPageMetadata,
)
from apps.fin_stmts_parse.src.statement_metadata_resolver import (
    StatementPageMetadata as ResolverPageMetadata,
)


class StatementPageMetadataTest(unittest.TestCase):
    def setUp(self) -> None:
        with mock.patch.object(BaseFinancialProcessor, "_initialize_openai_client"):
            self.processor = BaseFinancialProcessor(config={})

    def test_metadata_model_remains_available_from_base_module(self) -> None:
        self.assertIs(StatementPageMetadata, ResolverPageMetadata)

    def test_renderer_normalizes_decorated_title_from_metadata_object(self) -> None:
        rendered = self.processor.render_statement_markdown_with_metadata(
            "| 项目 | 金额 |\n| --- | --- |\n| 营业收入 | 100 |",
            "利润表",
            StatementPageMetadata(title=" # 损 益 表 # "),
        )

        self.assertTrue(rendered.startswith("# 损 益 表\n"))
        self.assertEqual(rendered.count("#"), 1)
        self.assertIn("| 营业收入 | 100 |", rendered)

    def test_processor_resolves_and_renders_metadata_through_component(self) -> None:
        markdown = (
            "# 资产负债表\n编制单位：测试有限公司\n2024年3月31日\n单位：元\n\n"
            "| 项目 | 年初余额 | 期末余额 |\n| --- | --- | --- |\n| 货币资金 | 1 | 2 |"
        )
        page_metadata = self.processor.metadata_resolver.extract_statement_metadata_from_text(
            markdown, "资产负债表", source="markdown", confidence="high"
        )
        file_metadata = self.processor.metadata_resolver.extract_statement_metadata_from_filename(
            "2026年3月报表.pdf", "资产负债表"
        )
        self.assertTrue(self.processor.metadata_resolver.needs_vl_recheck(page_metadata, file_metadata))
        merged = self.processor.metadata_resolver.merge_statement_metadata(page_metadata, file_metadata)
        resolved = self.processor.metadata_resolver.resolve_statement_metadata_date(merged, file_metadata)

        rendered = self.processor.render_statement_markdown_with_metadata(
            markdown, "资产负债表", resolved
        )

        self.assertEqual(resolved.date, "202603")
        self.assertEqual(resolved.to_dict()["date_source"], "file_name")
        self.assertTrue(resolved.to_dict()["date_warnings"])
        self.assertIn("编制单位：测试有限公司", rendered)
        self.assertIn("2026年3月", rendered)
        self.assertNotIn("2024年3月31日", rendered)
        self.assertEqual(rendered.count("# 资产负债表"), 1)
        self.assertIn("| 货币资金 | 1 | 2 |", rendered)

    def test_vl_metadata_still_uses_rule_normalization(self) -> None:
        self.processor.client.chat.completions.create.return_value.choices[0].message.content = (
            '{"title":"利润表","accounting_form":"会计02表",'
            '"company_name":"测试有限公司","date_raw":"2026年1-3月",'
            '"unit":"万元","confidence":"高"}'
        )

        with mock.patch.object(self.processor, "encode_image", return_value="image"):
            metadata = self.processor.extract_statement_metadata_with_vl("/tmp/demo.png", "利润表")

        self.assertEqual(metadata.date, "202603")
        self.assertEqual(metadata.company_name, "测试有限公司")
        self.assertEqual(metadata.accounting_form, "会计02表")
        self.assertEqual(metadata.unit, "万元")
        self.assertEqual(metadata.confidence, "high")
        self.assertEqual(metadata.date_source, "vl_metadata")

    def test_parse_analysis_response_preserves_title_and_consolidation_flag(self) -> None:
        result = self.processor._parse_analysis_response(
            """
            {"extracted_title":"合并资产负债表","is_consolidated":true,
            "has_target_table":true,"table_type":"合并资产负债表"}
            """,
            ["合并资产负债表"],
        )

        self.assertTrue(result["has_target_table"])
        self.assertEqual(result["table_type"], "合并资产负债表")
        self.assertEqual(result["extracted_title"], "合并资产负债表")
        self.assertTrue(result["is_consolidated"])

    def test_render_statement_markdown_replaces_existing_header_without_duplication(self) -> None:
        rendered = self.processor.render_statement_markdown_with_metadata(
            """
            # 资产负债表
            单位：元

            | 资产 | 年初余额 | 期末余额 |
            | --- | --- | --- |
            | 货币资金 | 1 | 2 |
            """,
            "资产负债表",
            StatementPageMetadata(
                title="资产负债表",
                accounting_form="会企01表",
                company_name="测试公司",
                date_raw="2023年12月31日",
                date="202312",
                unit="元",
                source="markdown",
                confidence="high",
            ),
        )

        self.assertEqual(rendered.count("# 资产负债表"), 1)
        self.assertIn("会企01表", rendered)
        self.assertIn("编制单位：测试公司", rendered)
        self.assertIn("2023年12月31日", rendered)
        self.assertIn("| 货币资金 | 1 | 2 |", rendered)


if __name__ == "__main__":
    unittest.main()
