import unittest

from db_tools.db_cli import compact_cell_value, is_read_only_sql, parse_table_reference, read_sql_text


class DbCliHelpersTest(unittest.TestCase):
    def test_parse_table_reference_defaults_to_public_schema(self) -> None:
        self.assertEqual(
            parse_table_reference("demo_table"),
            ("public", "demo_table"),
        )

    def test_parse_table_reference_accepts_schema_qualified_name(self) -> None:
        self.assertEqual(
            parse_table_reference("analytics.demo_table"),
            ("analytics", "demo_table"),
        )

    def test_compact_cell_value_normalizes_empty_none_and_multiline_values(self) -> None:
        self.assertEqual(compact_cell_value(None, 20), "NULL")
        self.assertEqual(compact_cell_value("", 20), "<empty>")
        self.assertEqual(compact_cell_value("line1\nline2", 20), "line1 | line2")

    def test_compact_cell_value_truncates_long_text(self) -> None:
        self.assertEqual(compact_cell_value("abcdefghijklmnopqrstuvwxyz", 10), "abcdefg...")

    def test_is_read_only_sql(self) -> None:
        self.assertTrue(is_read_only_sql(" select * from demo"))
        self.assertTrue(is_read_only_sql("SHOW search_path"))
        self.assertFalse(is_read_only_sql("insert into demo values (1)"))

    def test_read_sql_text_prefers_inline_query(self) -> None:
        self.assertEqual(read_sql_text("select 1", None), "select 1")


if __name__ == "__main__":
    unittest.main()
