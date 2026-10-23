import unittest

from apps.fin_stmts_parse.src.persistence.markdown_content_normalizer import (
    MarkdownStorageContentNormalizer,
    MarkdownStorageNormalizationError,
)


class MarkdownStorageContentNormalizerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.normalizer = MarkdownStorageContentNormalizer()

    def test_markdown_only_content_is_unchanged(self) -> None:
        content = (
            "# 资产负债表\n\n"
            "| 项目 | 期末余额 |\n"
            "| --- | --- |\n"
            "| 货币资金 | 100 |"
        )

        self.assertEqual(self.normalizer.normalize(content), content)

    def test_html_table_is_replaced_in_place(self) -> None:
        content = (
            "# 利润表\n\n单位：元\n\n"
            "<table><thead><tr><th>项目</th><th>金额</th></tr></thead>"
            "<tbody><tr><td>营业收入</td><td>1,000</td></tr></tbody></table>"
            "\n\n备注：未经审计"
        )

        normalized = self.normalizer.normalize(content)

        self.assertEqual(
            normalized,
            "# 利润表\n\n单位：元\n\n"
            "| 项目 | 金额 |\n"
            "| --- | --- |\n"
            "| 营业收入 | 1,000 |"
            "\n\n备注：未经审计",
        )
        self.assertNotIn("<table", normalized.lower())

    def test_mixed_markdown_and_multiple_html_tables_keep_order(self) -> None:
        content = (
            "| 既有 | Markdown |\n| --- | --- |\n| A | 1 |\n\n"
            "<table><tr><th>项目</th><th>金额</th></tr>"
            "<tr><td>B</td><td>2</td></tr></table>\n\n"
            "中间文字\n\n"
            "<TABLE><TR><TH>项目</TH><TH>金额</TH></TR>"
            "<TR><TD>C</TD><TD>3</TD></TR></TABLE>"
        )

        normalized = self.normalizer.normalize(content)

        self.assertLess(normalized.index("| A | 1 |"), normalized.index("| B | 2 |"))
        self.assertLess(normalized.index("| B | 2 |"), normalized.index("中间文字"))
        self.assertLess(normalized.index("中间文字"), normalized.index("| C | 3 |"))
        self.assertNotRegex(normalized.lower(), r"</?table\b")

    def test_rowspan_colspan_and_cell_text_are_flattened_deterministically(self) -> None:
        content = """
<table>
  <caption>资产明细</caption>
  <thead>
    <tr><th rowspan="2">项目</th><th colspan="2">金额</th></tr>
    <tr><th>期初</th><th>期末</th></tr>
  </thead>
  <tbody>
    <tr><td rowspan="2">现金</td><td>1</td><td>2</td></tr>
    <tr><td colspan="2">3 | 4<br>备注&nbsp;值</td></tr>
  </tbody>
</table>
""".strip()

        normalized = self.normalizer.normalize(content)

        self.assertEqual(
            normalized,
            "**资产明细**\n\n"
            "| 项目 | 金额<br>期初 | 金额<br>期末 |\n"
            "| --- | --- | --- |\n"
            "| 现金 | 1 | 2 |\n"
            "| 现金 | 3 &#124; 4<br>备注 值 |  |",
        )

    def test_inline_tags_preserve_text_without_numeric_coercion(self) -> None:
        content = (
            "<table><tr><th>编码</th><th>金额</th></tr>"
            "<tr><td><span>001</span></td><td><b>(1,234.00)</b></td></tr>"
            "</table>"
        )

        normalized = self.normalizer.normalize(content)

        self.assertIn("| 001 | (1,234.00) |", normalized)

    def test_leading_metadata_row_is_preserved_before_explicit_header(self) -> None:
        content = (
            "<table>"
            "<tr><td colspan=\"2\">资产负债表</td></tr>"
            "<tr><th>项目</th><th>期末余额</th></tr>"
            "<tr><td>货币资金</td><td>100</td></tr>"
            "</table>"
        )

        normalized = self.normalizer.normalize(content)

        self.assertEqual(
            normalized,
            "资产负债表\n\n"
            "| 项目 | 期末余额 |\n"
            "| --- | --- |\n"
            "| 货币资金 | 100 |",
        )

    def test_optional_html_cell_and_row_end_tags_can_be_omitted(self) -> None:
        normalized = self.normalizer.normalize(
            "<table><tr><th>项目<th>金额<tr><td>现金<td>100</table>"
        )

        self.assertEqual(
            normalized,
            "| 项目 | 金额 |\n"
            "| --- | --- |\n"
            "| 现金 | 100 |",
        )

    def test_unclosed_html_table_raises(self) -> None:
        with self.assertRaisesRegex(
            MarkdownStorageNormalizationError,
            "table 标签未闭合",
        ):
            self.normalizer.normalize(
                "<table><tr><th>项目</th></tr>"
            )

    def test_nested_html_table_raises(self) -> None:
        with self.assertRaisesRegex(
            MarkdownStorageNormalizationError,
            "嵌套 HTML 表格",
        ):
            self.normalizer.normalize(
                "<table><tr><td><table><tr><td>嵌套</td></tr></table>"
                "</td></tr></table>"
            )


if __name__ == "__main__":
    unittest.main()
