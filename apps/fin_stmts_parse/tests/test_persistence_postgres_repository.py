import unittest
from types import SimpleNamespace

from apps.fin_stmts_parse.src.persistence.contracts import FinancialStatementFactRow
from apps.fin_stmts_parse.src.persistence.postgres_repository import (
    PostgresFinancialStatementRepository,
)


class _FakeCursor:
    def __init__(self):
        self.execute_calls = []
        self.executemany_calls = []

    def execute(self, sql, params=None):
        self.execute_calls.append((sql, params))

    def executemany(self, sql, params_seq):
        self.executemany_calls.append((sql, list(params_seq)))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class _FakeConnection:
    def __init__(self):
        self.cursor_obj = _FakeCursor()
        self.commit_called = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commit_called = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class _FailingCursor(_FakeCursor):
    def executemany(self, sql, params_seq):
        super().executemany(sql, params_seq)
        raise RuntimeError("mocked insert failure")


class _FailingConnection(_FakeConnection):
    def __init__(self):
        super().__init__()
        self.cursor_obj = _FailingCursor()


class PostgresFinancialStatementRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = PostgresFinancialStatementRepository(
            {
                "postgres": {
                    "dsn": "postgresql://user:pass@localhost:5432/db",
                    "table_names": {
                        "balance": "fin_stmts_parse_results_balance",
                        "profit": "fin_stmts_parse_results_profit",
                        "cashflow": "fin_stmts_parse_results_cashflow",
                    },
                }
            }
        )

    def test_replace_session_snapshot_creates_tables_then_replaces_matching_file_rows(self) -> None:
        fake_connection = _FakeConnection()
        self.repository._connect = lambda: fake_connection

        self.repository.replace_session_snapshot(
            "session-1",
            [
                FinancialStatementFactRow(
                    session_id="session-1",
                    company_name="测试公司",
                    item_name="货币资金",
                    fns_cycle="12",
                    fns_year="2024",
                    report_cycle_type="",
                    report_type="1",
                    begin_amt="90.25",
                    end_amt="100.5",
                    report_status="0",
                    stat_date="2026-04-12 10:00:00",
                    file_name="demo.pdf",
                    extension_field="",
                    stat_is_audit="",
                    statement_type="balance",
                    source_group_key="file-1",
                )
            ],
        )

        execute_calls = fake_connection.cursor_obj.execute_calls
        create_table_calls = [
            call for call in execute_calls if call[0].startswith("CREATE TABLE IF NOT EXISTS ")
        ]
        alter_begin_calls = [
            call for call in execute_calls if "ALTER COLUMN begin_amt DROP NOT NULL" in call[0]
        ]
        alter_end_calls = [
            call for call in execute_calls if "ALTER COLUMN end_amt DROP NOT NULL" in call[0]
        ]
        create_session_index_calls = [
            call
            for call in execute_calls
            if call[0].startswith("CREATE INDEX IF NOT EXISTS idx_")
            and call[0].endswith("(session_id)")
        ]
        create_session_file_index_calls = [
            call for call in execute_calls if "_session_id_file_name" in call[0]
        ]
        create_snapshot_index_calls = [
            call for call in execute_calls if "_snapshot " in call[0]
        ]
        deleted_calls = [
            call for call in execute_calls if call[0].startswith("DELETE FROM ")
        ]

        created_tables = [call[0].split()[5] for call in create_table_calls]
        self.assertEqual(
            created_tables,
            [
                "fin_stmts_parse_results_balance",
                "fin_stmts_parse_results_profit",
                "fin_stmts_parse_results_cashflow",
            ],
        )
        self.assertEqual(len(alter_begin_calls), 3)
        self.assertEqual(len(alter_end_calls), 3)
        self.assertTrue(
            all("begin_amt varchar" in call[0] and "begin_amt varchar NOT NULL" not in call[0] for call in create_table_calls)
        )
        self.assertTrue(
            all("end_amt varchar" in call[0] and "end_amt varchar NOT NULL" not in call[0] for call in create_table_calls)
        )
        created_session_index_names = [
            call[0].split()[5] for call in create_session_index_calls
        ]
        self.assertEqual(
            created_session_index_names,
            [
                "idx_fin_stmts_parse_results_balance_session_id",
                "idx_fin_stmts_parse_results_profit_session_id",
                "idx_fin_stmts_parse_results_cashflow_session_id",
            ],
        )
        created_session_file_index_names = [
            call[0].split()[5] for call in create_session_file_index_calls
        ]
        self.assertEqual(
            created_session_file_index_names,
            [
                "idx_fin_stmts_parse_results_balance_session_id_file_name",
                "idx_fin_stmts_parse_results_profit_session_id_file_name",
                "idx_fin_stmts_parse_results_cashflow_session_id_file_name",
            ],
        )
        created_snapshot_index_names = [
            call[0].split()[5] for call in create_snapshot_index_calls
        ]
        self.assertEqual(
            created_snapshot_index_names,
            [
                "idx_fin_stmts_parse_results_balance_snapshot",
                "idx_fin_stmts_parse_results_profit_snapshot",
                "idx_fin_stmts_parse_results_cashflow_snapshot",
            ],
        )
        deleted_tables = [call[0].split()[2] for call in deleted_calls]
        self.assertEqual(
            deleted_tables,
            [
                "fin_stmts_parse_results_balance",
            ],
        )
        self.assertTrue(
            all(
                call[1] == ("session-1", "demo.pdf", "0", "1")
                for call in deleted_calls
            )
        )
        self.assertTrue(
            all(
                "WHERE session_id = %s AND file_name = %s "
                "AND report_status = %s AND report_type = %s" in call[0]
                for call in deleted_calls
            )
        )
        self.assertEqual(len(fake_connection.cursor_obj.executemany_calls), 1)
        self.assertIn(
            "INSERT INTO fin_stmts_parse_results_balance",
            fake_connection.cursor_obj.executemany_calls[0][0],
        )
        self.assertTrue(fake_connection.commit_called)

    def test_replace_session_snapshot_preserves_null_empty_and_zero_amounts(self) -> None:
        fake_connection = _FakeConnection()
        self.repository._connect = lambda: fake_connection

        rows = [
            FinancialStatementFactRow(
                session_id="session-1",
                company_name="测试公司",
                item_name="货币资金",
                fns_cycle="12",
                fns_year="2024",
                report_cycle_type="",
                report_type="1",
                begin_amt=None,
                end_amt=None,
                report_status="0",
                stat_date="2026-04-12 10:00:00",
                file_name="demo.pdf",
                extension_field="",
                stat_is_audit="",
                statement_type="balance",
                source_group_key="file-a",
            ),
            FinancialStatementFactRow(
                session_id="session-1",
                company_name="测试公司",
                item_name="营业总收入",
                fns_cycle="12",
                fns_year="2024",
                report_cycle_type="",
                report_type="1",
                begin_amt="",
                end_amt="0.0",
                report_status="0",
                stat_date="2026-04-12 10:00:00",
                file_name="demo.pdf",
                extension_field="",
                stat_is_audit="",
                statement_type="profit",
                source_group_key="file-b",
            ),
        ]

        self.repository.replace_session_snapshot("session-1", rows)

        inserts_by_table = {
            sql.split()[2]: params
            for sql, params in fake_connection.cursor_obj.executemany_calls
        }
        balance_rows = inserts_by_table["fin_stmts_parse_results_balance"]
        profit_rows = inserts_by_table["fin_stmts_parse_results_profit"]
        self.assertIsNone(balance_rows[0][7])
        self.assertIsNone(balance_rows[0][8])
        self.assertEqual(profit_rows[0][7], "")
        self.assertEqual(profit_rows[0][8], "0.0")

    def test_replace_session_snapshot_dedupes_file_names_across_statement_tables(self) -> None:
        fake_connection = _FakeConnection()
        self.repository._connect = lambda: fake_connection

        rows = [
            FinancialStatementFactRow(
                session_id="session-1",
                company_name="测试公司",
                item_name="货币资金",
                fns_cycle="12",
                fns_year="2024",
                report_cycle_type="",
                report_type="1",
                begin_amt="90.25",
                end_amt="100.5",
                report_status="0",
                stat_date="2026-04-12 10:00:00",
                file_name="demo.pdf",
                extension_field="",
                stat_is_audit="",
                statement_type="balance",
                source_group_key="file-a",
            ),
            FinancialStatementFactRow(
                session_id="session-1",
                company_name="测试公司",
                item_name="资产总计",
                fns_cycle="12",
                fns_year="2024",
                report_cycle_type="",
                report_type="1",
                begin_amt="270.25",
                end_amt="300.5",
                report_status="0",
                stat_date="2026-04-12 10:00:00",
                file_name="demo.pdf",
                extension_field="",
                stat_is_audit="",
                statement_type="balance",
                source_group_key="file-a",
            ),
            FinancialStatementFactRow(
                session_id="session-1",
                company_name="测试公司",
                item_name="营业总收入",
                fns_cycle="12",
                fns_year="2024",
                report_cycle_type="",
                report_type="1",
                begin_amt="",
                end_amt="1000.0",
                report_status="0",
                stat_date="2026-04-12 10:00:00",
                file_name="demo.pdf",
                extension_field="",
                stat_is_audit="",
                statement_type="profit",
                source_group_key="file-b",
            ),
        ]

        self.repository.replace_session_snapshot("session-1", rows)

        inserts_by_table = {
            sql.split()[2]: params
            for sql, params in fake_connection.cursor_obj.executemany_calls
        }
        balance_rows = inserts_by_table["fin_stmts_parse_results_balance"]
        profit_rows = inserts_by_table["fin_stmts_parse_results_profit"]
        self.assertEqual(balance_rows[0][11], "demo.pdf")
        self.assertEqual(balance_rows[1][11], "demo.pdf")
        self.assertEqual(profit_rows[0][11], "demo_1.pdf")

    def test_replace_session_snapshot_deletes_target_files_even_when_rows_are_empty(self) -> None:
        fake_connection = _FakeConnection()
        self.repository._connect = lambda: fake_connection

        self.repository.replace_session_snapshot(
            "session-1",
            [],
            report_status="0",
            target_sources=[
                SimpleNamespace(
                    file_name="demo.pdf",
                    source_group_key="file-a",
                    mapped_result=SimpleNamespace(
                        statement_type="balance",
                        is_consolidated=False,
                    ),
                )
            ],
        )

        deleted_calls = [
            call
            for call in fake_connection.cursor_obj.execute_calls
            if call[0].startswith("DELETE FROM ")
        ]
        self.assertEqual(len(fake_connection.cursor_obj.executemany_calls), 0)
        self.assertEqual(len(deleted_calls), 1)
        self.assertTrue(
            all(
                call[1] == ("session-1", "demo.pdf", "0", "1")
                for call in deleted_calls
            )
        )

    def test_replace_session_snapshot_keeps_status_and_report_type_in_delete_scope(self) -> None:
        fake_connection = _FakeConnection()
        self.repository._connect = lambda: fake_connection

        self.repository.replace_session_snapshot(
            "session-1",
            [],
            report_status="1",
            target_sources=[
                SimpleNamespace(
                    file_name="demo.pdf",
                    source_group_key="file-a",
                    mapped_result=SimpleNamespace(
                        statement_type="balance",
                        is_consolidated=False,
                    ),
                ),
                SimpleNamespace(
                    file_name="demo.pdf",
                    source_group_key="file-a",
                    mapped_result=SimpleNamespace(
                        statement_type="balance",
                        is_consolidated=True,
                    ),
                ),
            ],
        )

        deleted_calls = [
            call
            for call in fake_connection.cursor_obj.execute_calls
            if call[0].startswith("DELETE FROM ")
        ]
        self.assertEqual(
            deleted_calls,
            [
                (
                    "DELETE FROM fin_stmts_parse_results_balance "
                    "WHERE session_id = %s AND file_name = %s "
                    "AND report_status = %s AND report_type = %s",
                    ("session-1", "demo.pdf", "1", "1"),
                ),
                (
                    "DELETE FROM fin_stmts_parse_results_balance "
                    "WHERE session_id = %s AND file_name = %s "
                    "AND report_status = %s AND report_type = %s",
                    ("session-1", "demo.pdf", "1", "2"),
                ),
            ],
        )

    def test_replace_session_snapshot_requires_status_for_empty_target_sources(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "target_sources 非空时必须显式传入 report_status",
        ):
            self.repository.replace_session_snapshot(
                "session-1",
                [],
                target_sources=[
                    SimpleNamespace(
                        file_name="demo.pdf",
                        source_group_key="file-a",
                        mapped_result=SimpleNamespace(
                            statement_type="balance",
                            is_consolidated=False,
                        ),
                    )
                ],
            )

    def test_replace_file_markdown_only_replaces_markdown_rows_for_file(self) -> None:
        fake_connection = _FakeConnection()
        self.repository._connect = lambda: fake_connection

        self.repository.replace_file_markdown(
            session_id="session-1",
            file_name="demo.pdf",
            rows=[
                self._make_markdown_row(
                    statement_type="balance",
                    report_type="1",
                    item_name="资产负债表",
                    content="balance markdown",
                ),
                self._make_markdown_row(
                    statement_type="profit",
                    report_type="2",
                    item_name="合并利润表",
                    content="profit markdown",
                ),
                self._make_markdown_row(
                    statement_type="cashflow",
                    report_type="1",
                    item_name="现金流量表",
                    content="cashflow markdown",
                ),
            ],
        )

        execute_calls = fake_connection.cursor_obj.execute_calls
        advisory_lock_calls = [
            call
            for call in execute_calls
            if "pg_advisory_xact_lock" in call[0]
        ]
        markdown_delete_calls = [
            call
            for call in execute_calls
            if call[0].startswith("DELETE FROM ")
            and "report_status = %s" in call[0]
        ]
        markdown_index_calls = [
            call
            for call in execute_calls
            if call[0].startswith("CREATE UNIQUE INDEX IF NOT EXISTS ux_")
        ]

        self.assertEqual(len(advisory_lock_calls), 1)
        self.assertEqual(
            advisory_lock_calls[0][1],
            ("session-1\x1fdemo.pdf",),
        )
        self.assertEqual(len(markdown_delete_calls), 3)
        self.assertTrue(
            all(
                call[1] == ("session-1", "demo.pdf", "-1")
                for call in markdown_delete_calls
            )
        )
        self.assertEqual(len(markdown_index_calls), 3)

        inserts_by_table = {
            sql.split()[2]: params
            for sql, params in fake_connection.cursor_obj.executemany_calls
        }
        self.assertEqual(
            set(inserts_by_table),
            {
                "fin_stmts_parse_results_balance",
                "fin_stmts_parse_results_profit",
                "fin_stmts_parse_results_cashflow",
            },
        )
        self.assertEqual(
            inserts_by_table["fin_stmts_parse_results_balance"][0][9],
            "-1",
        )
        self.assertEqual(
            inserts_by_table["fin_stmts_parse_results_balance"][0][12],
            "balance markdown",
        )
        self.assertTrue(fake_connection.commit_called)

    def test_replace_file_markdown_does_not_commit_when_insert_fails(self) -> None:
        failing_connection = _FailingConnection()
        self.repository._connect = lambda: failing_connection

        with self.assertRaisesRegex(RuntimeError, "mocked insert failure"):
            self.repository.replace_file_markdown(
                session_id="session-1",
                file_name="demo.pdf",
                rows=[
                    self._make_markdown_row(
                        statement_type="balance",
                        report_type="1",
                        item_name="资产负债表",
                        content="balance markdown",
                    )
                ],
            )

        self.assertFalse(failing_connection.commit_called)

    def test_replace_file_markdown_rejects_duplicate_statement_report_type(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "同一物理表和 report_type",
        ):
            self.repository.replace_file_markdown(
                session_id="session-1",
                file_name="demo.pdf",
                rows=[
                    self._make_markdown_row(
                        statement_type="balance",
                        report_type="1",
                        item_name="资产负债表",
                        content="first",
                    ),
                    self._make_markdown_row(
                        statement_type="balance",
                        report_type="1",
                        item_name="资产负债表",
                        content="second",
                    ),
                ],
            )

    def test_replace_session_snapshot_rejects_markdown_status_rows(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "report_status 必须为 0 或 1",
        ):
            self.repository.replace_session_snapshot(
                "session-1",
                [
                    self._make_markdown_row(
                        statement_type="balance",
                        report_type="1",
                        item_name="资产负债表",
                        content="raw markdown",
                    )
                ],
            )

    def test_replace_session_snapshot_raises_for_missing_or_invalid_table_names(self) -> None:
        missing_table_repository = PostgresFinancialStatementRepository(
            {
                "postgres": {
                    "dsn": "postgresql://user:pass@localhost:5432/db",
                    "table_names": {
                        "balance": "fin_stmts_parse_results_balance",
                        "profit": "",
                        "cashflow": "fin_stmts_parse_results_cashflow",
                    },
                }
            }
        )
        with self.assertRaisesRegex(ValueError, "postgres.table_names.profit"):
            missing_table_repository.replace_session_snapshot("session-1", [])

        invalid_table_repository = PostgresFinancialStatementRepository(
            {
                "postgres": {
                    "dsn": "postgresql://user:pass@localhost:5432/db",
                    "table_names": {
                        "balance": "fin_stmts_parse_results_balance",
                        "profit": "bad-table-name",
                        "cashflow": "fin_stmts_parse_results_cashflow",
                    },
                }
            }
        )
        with self.assertRaisesRegex(ValueError, "postgres.table_names.profit"):
            invalid_table_repository.replace_session_snapshot("session-1", [])

    @staticmethod
    def _make_markdown_row(
        *,
        statement_type: str,
        report_type: str,
        item_name: str,
        content: str,
    ) -> FinancialStatementFactRow:
        return FinancialStatementFactRow(
            session_id="session-1",
            company_name="测试公司",
            item_name=item_name,
            fns_cycle="12",
            fns_year="2024",
            report_cycle_type="YEAR",
            report_type=report_type,
            begin_amt=None,
            end_amt=None,
            report_status="-1",
            stat_date="2026-07-20 10:00:00",
            file_name="demo.pdf",
            extension_field=content,
            stat_is_audit="",
            statement_type=statement_type,
            source_group_key=f"{statement_type}:{report_type}",
        )


if __name__ == "__main__":
    unittest.main()
