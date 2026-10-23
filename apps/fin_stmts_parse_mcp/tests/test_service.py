import asyncio
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from apps.fin_stmts_parse.src.core.contracts import StatementMarkdownDocument
from lwade_utils.bootload import load_entry_module


os.environ["RUNNING_ENV"] = "local"

module = load_entry_module("apps/fin_stmts_parse_mcp", "mcp", "service.py")


class MCPProgressReporterTests(unittest.TestCase):
    def test_reporter_sends_progress_notification(self):
        events = []

        class FakeContext:
            async def report_progress(self, progress, total, message):
                events.append(
                    {
                        "progress": progress,
                        "total": total,
                        "message": message,
                    }
                )

        def run_async(fn, *args):
            return asyncio.run(fn(*args))

        with patch.object(module.anyio.from_thread, "run", side_effect=run_async):
            reporter = module.MCPProgressReporter(FakeContext(), total=5)
            reporter.report("正在执行勾稽校验", progress=3)

        self.assertEqual(
            events,
            [
                {
                    "progress": 3.0,
                    "total": 5.0,
                    "message": "正在执行勾稽校验",
                }
            ],
        )


class FinStmtsParseMarkdownTests(unittest.TestCase):
    def setUp(self):
        self.service = module.FinStmtsMarkdownService.__new__(module.FinStmtsMarkdownService)
        self.service.markdown_fact_builder = Mock()
        self.service.markdown_fact_builder.build_rows.return_value = []
        self.service.repository = Mock()

    def test_parse_returns_one_result_per_input_file(self):
        extracted_by_name = {
            "standalone.pdf": [
                StatementMarkdownDocument(
                    table_name="资产负债表",
                    date="202412",
                    company_name="测试公司",
                    is_consolidated=False,
                    content="# 资产负债表\n\n| 项目 | 期末余额 |\n| --- | --- |\n| 货币资金 | 100 |",
                )
            ],
            "consolidated.pdf": [
                StatementMarkdownDocument(
                    table_name="合并利润表",
                    date="202409",
                    company_name="测试公司",
                    is_consolidated=True,
                    content="# 合并利润表\n\n| 项目 | 本年累计金额 |\n| --- | --- |\n| 营业总收入 | 300 |",
                )
            ],
            "empty.pdf": [],
        }

        def fake_extract(local_path, is_consolidated, report_type):
            self.assertIsNone(is_consolidated)
            self.assertIsNone(report_type)
            return extracted_by_name[os.path.basename(local_path)]

        with patch.object(module, "batch_download", return_value=None), patch.object(
            self.service,
            "_extract_markdown_documents",
            side_effect=fake_extract,
        ):
            result = self.service.parse_fin_stmts_markdown(
                session_id="session-1",
                files=[
                    {"path": "/tmp/standalone.pdf"},
                    {"path": "/tmp/consolidated.pdf"},
                    {"path": "/tmp/notes.txt"},
                    {"path": "/tmp/empty.pdf"},
                ]
            )

        self.assertEqual(len(result), 4)

        standalone_result = result[0]
        self.assertEqual(
            standalone_result,
            {
                "message": "解析成功",
                "file_name": "standalone.pdf",
                "company_name": "测试公司",
                "markdown_files": [
                    {
                        "table_name": "资产负债表",
                        "table_type": "balance",
                        "is_consolidated": False,
                        "date": "202412",
                        "period": "YEAR",
                        "content": "# 资产负债表\n\n| 项目 | 期末余额 |\n| --- | --- |\n| 货币资金 | 100 |",
                    }
                ],
            },
        )

        consolidated_result = result[1]
        self.assertEqual(consolidated_result["file_name"], "consolidated.pdf")
        self.assertEqual(consolidated_result["message"], "解析成功")
        self.assertEqual(consolidated_result["company_name"], "测试公司")
        self.assertEqual(
            consolidated_result["markdown_files"][0],
            {
                "table_name": "合并利润表",
                "table_type": "profit",
                "is_consolidated": True,
                "date": "202409",
                "period": "QUATER",
                "content": "# 合并利润表\n\n| 项目 | 本年累计金额 |\n| --- | --- |\n| 营业总收入 | 300 |",
            },
        )
        self.assertEqual(
            set(consolidated_result["markdown_files"][0].keys()),
            {"table_name", "table_type", "is_consolidated", "date", "period", "content"},
        )

        unsupported_result = result[2]
        self.assertEqual(
            unsupported_result,
            {
                "message": "不支持的文件类型",
                "file_name": "notes.txt",
                "company_name": "",
                "markdown_files": [],
            },
        )

        empty_result = result[3]
        self.assertEqual(
            empty_result,
            {
                "message": "未识别到财报表格内容",
                "file_name": "empty.pdf",
                "company_name": "",
                "markdown_files": [],
            },
        )

    def test_parse_processes_files_concurrently_and_preserves_input_order(self):
        barrier = threading.Barrier(2)
        completion_order = []
        observed_session_ids = []
        observation_lock = threading.Lock()
        second_file_completed = threading.Event()

        def fake_extract(local_path, is_consolidated, report_type):
            file_name = os.path.basename(local_path)
            with observation_lock:
                observed_session_ids.append(
                    module.request_context.get().get("session_id")
                )

            barrier.wait(timeout=2)
            if file_name == "first.pdf":
                if not second_file_completed.wait(timeout=2):
                    raise RuntimeError("第二个文件未并发完成")
            with observation_lock:
                completion_order.append(file_name)
            if file_name == "second.pdf":
                second_file_completed.set()
            return []

        with patch.dict(
            os.environ,
            {"MCP_PARSE_MAX_WORKERS": "2"},
        ), patch.object(
            module,
            "batch_download",
            return_value=None,
        ), patch.object(
            self.service,
            "_extract_markdown_documents",
            side_effect=fake_extract,
        ):
            result = self.service.parse_fin_stmts_markdown(
                session_id="session-concurrent",
                files=[
                    {"path": "/tmp/first.pdf"},
                    {"path": "/tmp/second.pdf"},
                ],
            )

        self.assertEqual(
            [item["file_name"] for item in result],
            ["first.pdf", "second.pdf"],
        )
        self.assertEqual(completion_order[0], "second.pdf")
        self.assertEqual(
            observed_session_ids,
            ["session-concurrent", "session-concurrent"],
        )

    def test_concurrent_parse_isolates_unexpected_file_failure(self):
        def fake_build_file_result(*, input_file, **kwargs):
            if input_file.fileName == "broken.pdf":
                raise RuntimeError("unexpected worker error")
            return {
                "message": "解析成功",
                "file_name": input_file.fileName,
                "company_name": "",
                "markdown_files": [],
            }

        with patch.dict(
            os.environ,
            {"MCP_PARSE_MAX_WORKERS": "2"},
        ), patch.object(
            self.service,
            "_build_file_result",
            side_effect=fake_build_file_result,
        ):
            result = self.service.parse_fin_stmts_markdown(
                session_id="session-1",
                files=[
                    {"path": "/tmp/broken.pdf"},
                    {"path": "/tmp/healthy.pdf"},
                ],
            )

        self.assertEqual(
            result[0],
            {
                "message": "解析失败: unexpected worker error",
                "file_name": "broken.pdf",
                "company_name": "",
                "markdown_files": [],
            },
        )
        self.assertEqual(result[1]["message"], "解析成功")

    def test_concurrent_parse_aggregates_progress_outside_workers(self):
        worker_progress_values = []
        progress = Mock()

        def fake_build_file_result(*, input_file, progress, **kwargs):
            worker_progress_values.append(progress)
            return {
                "message": "解析成功",
                "file_name": input_file.fileName,
                "company_name": "",
                "markdown_files": [],
            }

        with patch.dict(
            os.environ,
            {"MCP_PARSE_MAX_WORKERS": "2"},
        ), patch.object(
            self.service,
            "_build_file_result",
            side_effect=fake_build_file_result,
        ):
            self.service.parse_fin_stmts_markdown(
                session_id="session-1",
                files=[
                    {"path": "/tmp/first.pdf"},
                    {"path": "/tmp/second.pdf"},
                ],
                progress=progress,
            )

        self.assertEqual(worker_progress_values, [None, None])
        self.assertEqual(progress.report.call_count, 3)
        self.assertEqual(
            progress.report.call_args_list[0].kwargs,
            {"progress": 2},
        )
        self.assertEqual(
            progress.report.call_args_list[-1].kwargs,
            {"progress": 4.0},
        )

    def test_parse_returns_public_markdown_fields_only(self):
        extracted_by_name = {
            "demo.pdf": [
                StatementMarkdownDocument(
                    table_name="资产负债表",
                    date="202412",
                    unit="元",
                    company_name="测试公司",
                    is_consolidated=False,
                    content="# 资产负债表\n\n<table><tr><td>货币资金</td></tr></table>",
                    source_file_name="demo.pdf",
                    source_file_path="/tmp/demo.pdf",
                )
            ],
        }

        with patch.object(module, "batch_download", return_value=None), patch.object(
            self.service,
            "_extract_markdown_documents",
            side_effect=lambda local_path, is_consolidated, report_type: extracted_by_name[os.path.basename(local_path)],
        ):
            result = self.service.parse_fin_stmts_markdown(
                session_id="session-1",
                files=[{"path": "/tmp/demo.pdf"}]
            )

        self.assertEqual(
            result[0]["markdown_files"],
            [
                {
                    "table_name": "资产负债表",
                    "table_type": "balance",
                    "is_consolidated": False,
                    "date": "202412",
                    "period": "YEAR",
                    "content": "# 资产负债表\n\n<table><tr><td>货币资金</td></tr></table>",
                    "unit": "元",
                }
            ],
        )
        self.assertNotIn("company_name", result[0]["markdown_files"][0])
        self.assertNotIn("source_file_name", result[0]["markdown_files"][0])
        self.assertNotIn("source_file_path", result[0]["markdown_files"][0])

    def test_parse_returns_page_when_document_contains_page(self):
        extracted_by_name = {
            "demo.pdf": [
                StatementMarkdownDocument(
                    table_name="资产负债表",
                    page=23,
                    date="202512",
                    company_name="测试公司",
                    is_consolidated=False,
                    content="# 资产负债表\n\n| 项目 | 期末余额 |\n| --- | --- |\n| 货币资金 | 100 |",
                )
            ],
        }

        with patch.object(module, "batch_download", return_value=None), patch.object(
            self.service,
            "_extract_markdown_documents",
            side_effect=lambda local_path, is_consolidated, report_type: extracted_by_name[os.path.basename(local_path)],
        ):
            result = self.service.parse_fin_stmts_markdown(
                session_id="session-1",
                files=[{"path": "/tmp/demo.pdf"}]
            )

        self.assertEqual(result[0]["markdown_files"][0]["page"], 23)
        self.assertEqual(result[0]["markdown_files"][0]["period"], "YEAR")
        self.assertEqual(result[0]["markdown_files"][0]["table_type"], "balance")

    def test_parse_returns_half_year_period_for_june_statement(self):
        extracted_by_name = {
            "demo.pdf": [
                StatementMarkdownDocument(
                    table_name="利润表",
                    date="202506",
                    company_name="测试公司",
                    is_consolidated=False,
                    content="# 利润表\n\n| 项目 | 金额 |\n| --- | --- |\n| 营业收入 | 100 |",
                )
            ],
        }

        with patch.object(module, "batch_download", return_value=None), patch.object(
            self.service,
            "_extract_markdown_documents",
            side_effect=lambda local_path, is_consolidated, report_type: extracted_by_name[os.path.basename(local_path)],
        ):
            result = self.service.parse_fin_stmts_markdown(
                session_id="session-1",
                files=[{"path": "/tmp/demo.pdf"}]
            )

        self.assertEqual(result[0]["markdown_files"][0]["period"], "INTERIM")
        self.assertEqual(result[0]["markdown_files"][0]["table_type"], "profit")

    def test_parse_returns_empty_company_name_when_documents_conflict(self):
        extracted_by_name = {
            "conflict.pdf": [
                StatementMarkdownDocument(
                    table_name="资产负债表",
                    date="202412",
                    company_name="公司甲",
                    is_consolidated=False,
                    content="# 资产负债表\n\n| 项目 | 期末余额 |\n| --- | --- |\n| 货币资金 | 100 |",
                ),
                StatementMarkdownDocument(
                    table_name="利润表",
                    date="202412",
                    company_name="公司乙",
                    is_consolidated=False,
                    content="# 利润表\n\n| 项目 | 金额 |\n| --- | --- |\n| 营业收入 | 100 |",
                ),
            ],
        }

        with patch.object(module, "batch_download", return_value=None), patch.object(
            self.service,
            "_extract_markdown_documents",
            side_effect=lambda local_path, is_consolidated, report_type: extracted_by_name[os.path.basename(local_path)],
        ):
            result = self.service.parse_fin_stmts_markdown(
                session_id="session-1",
                files=[{"path": "/tmp/conflict.pdf"}]
            )

        self.assertEqual(result[0]["company_name"], "")

    def test_parse_failure_is_reported_per_file(self):
        with patch.object(module, "batch_download", return_value=None), patch.object(
            self.service,
            "_extract_markdown_documents",
            side_effect=RuntimeError("mocked parse error"),
        ):
            result = self.service.parse_fin_stmts_markdown(
                session_id="session-1",
                files=[{"path": "/tmp/broken.pdf"}]
            )

        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0],
            {
                "message": "解析失败: mocked parse error",
                "file_name": "broken.pdf",
                "company_name": "",
                "markdown_files": [],
            },
        )

    def test_parse_persists_markdown_rows_after_successful_extraction(self):
        document = StatementMarkdownDocument(
            table_name="资产负债表",
            page=23,
            date="202412",
            company_name="测试公司",
            is_consolidated=False,
            content="# 资产负债表\n\n| 项目 | 期末余额 |",
        )
        markdown_row = Mock()
        self.service.markdown_fact_builder.build_rows.return_value = [
            markdown_row
        ]

        with patch.object(module, "batch_download", return_value=None), patch.object(
            self.service,
            "_extract_markdown_documents",
            return_value=[document],
        ):
            result = self.service.parse_fin_stmts_markdown(
                session_id="session-1",
                files=[{"path": "/tmp/demo.pdf"}],
            )

        self.assertEqual(result[0]["message"], "解析成功")
        self.service.markdown_fact_builder.build_rows.assert_called_once_with(
            session_id="session-1",
            company_name="测试公司",
            file_name="demo.pdf",
            documents=[document],
        )
        self.service.repository.replace_file_markdown.assert_called_once_with(
            session_id="session-1",
            file_name="demo.pdf",
            rows=[markdown_row],
        )

    def test_parse_reports_markdown_persistence_failure_but_returns_content(self):
        document = StatementMarkdownDocument(
            table_name="利润表",
            date="202412",
            company_name="测试公司",
            is_consolidated=False,
            content="# 利润表\n\n| 项目 | 本期金额 |",
        )
        self.service.markdown_fact_builder.build_rows.return_value = [Mock()]
        self.service.repository.replace_file_markdown.side_effect = RuntimeError(
            "database unavailable"
        )

        with patch.object(module, "batch_download", return_value=None), patch.object(
            self.service,
            "_extract_markdown_documents",
            return_value=[document],
        ):
            result = self.service.parse_fin_stmts_markdown(
                session_id="session-1",
                files=[{"path": "/tmp/demo.pdf"}],
            )

        self.assertEqual(
            result[0]["message"],
            "解析成功但 Markdown 入库失败: database unavailable",
        )
        self.assertEqual(
            result[0]["markdown_files"][0]["content"],
            document.content,
        )

    def test_parse_reports_normalization_failure_without_replacing_database(self):
        document = StatementMarkdownDocument(
            table_name="利润表",
            date="202412",
            company_name="测试公司",
            is_consolidated=False,
            content="<table><tr><th>项目</th></tr>",
        )
        self.service.markdown_fact_builder.build_rows.side_effect = ValueError(
            "HTML table 标签未闭合"
        )

        with patch.object(module, "batch_download", return_value=None), patch.object(
            self.service,
            "_extract_markdown_documents",
            return_value=[document],
        ):
            result = self.service.parse_fin_stmts_markdown(
                session_id="session-1",
                files=[{"path": "/tmp/demo.pdf"}],
            )

        self.assertEqual(
            result[0]["message"],
            "解析成功但 Markdown 入库失败: HTML table 标签未闭合",
        )
        self.assertEqual(result[0]["markdown_files"][0]["content"], document.content)
        self.service.repository.replace_file_markdown.assert_not_called()

    def test_parse_empty_result_does_not_replace_previous_markdown(self):
        with patch.object(module, "batch_download", return_value=None), patch.object(
            self.service,
            "_extract_markdown_documents",
            return_value=[],
        ):
            result = self.service.parse_fin_stmts_markdown(
                session_id="session-1",
                files=[{"path": "/tmp/empty.pdf"}],
            )

        self.assertEqual(result[0]["message"], "未识别到财报表格内容")
        self.service.markdown_fact_builder.build_rows.assert_not_called()
        self.service.repository.replace_file_markdown.assert_not_called()

    def test_duplicate_input_names_are_deduped_with_suffix_one(self):
        normalized = self.service._normalize_files(
            files=[
                {"path": "/tmp/demo.pdf"},
                {"path": "/var/tmp/demo.pdf"},
                {"fileName": "demo.pdf", "fileUrl": "https://example.com/demo.pdf"},
            ]
        )

        self.assertEqual(
            [item.fileName for item in normalized],
            ["demo.pdf", "demo_1.pdf", "demo_2.pdf"],
        )

    def test_parse_downloads_to_daily_persistent_dir_without_cleaning(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"MCP_PERSISTENT_BASE_DIR": temp_dir},
        ), patch.object(
            module,
            "batch_download",
            return_value=None,
        ) as mock_download, patch.object(
            self.service,
            "_extract_markdown_documents",
            return_value=[],
        ):
            self.service.parse_fin_stmts_markdown(
                session_id="session-1",
                files=[{"path": "/tmp/demo.pdf"}],
            )

            date_prefix = module.datetime.now().strftime("%Y%m%d")
            expected_download_dir = str(Path(temp_dir) / date_prefix / "download")
            download_args, download_kwargs = mock_download.call_args

        self.assertEqual(download_args[1], expected_download_dir)
        self.assertEqual(download_kwargs["clean_dir"], False)

    def test_parse_core_output_uses_daily_persistent_output_dir(self):
        self.service.parse_core = Mock()
        self.service.parse_core.parse_local_file.return_value = []

        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"MCP_PERSISTENT_BASE_DIR": temp_dir},
        ):
            self.service._extract_markdown_documents(
                local_path="/tmp/demo.pdf",
                is_consolidated=None,
                report_type=None,
            )

            date_prefix = module.datetime.now().strftime("%Y%m%d")
            expected_output_dir = str(Path(temp_dir) / date_prefix / "output")
            call_kwargs = self.service.parse_core.parse_local_file.call_args.kwargs

        self.assertEqual(call_kwargs["output_dir"], expected_output_dir)

    def test_parse_requires_session_id(self):
        with self.assertRaisesRegex(ValueError, "session_id 不能为空"):
            self.service.parse_fin_stmts_markdown(
                files=[{"path": "/tmp/demo.pdf"}],
                session_id="",
            )

    def test_tool_wrapper_only_forwards_files_and_session_id(self):
        expected = [
            {
                "message": "解析成功",
                "file_name": "demo.pdf",
                "company_name": "",
                "markdown_files": [],
            }
        ]
        mock_service = Mock()
        mock_service.parse_fin_stmts_markdown.return_value = expected

        with patch.object(module, "get_markdown_service", return_value=mock_service):
            result = module.parse_fin_stmts_markdown(
                files=[{"path": "/tmp/demo.pdf"}],
                session_id="session-1",
            )

        mock_service.parse_fin_stmts_markdown.assert_called_once_with(
            files=[{"path": "/tmp/demo.pdf"}],
            session_id="session-1",
        )
        self.assertEqual(result, expected)


class McpToolAuditLogTests(unittest.TestCase):
    def test_tool_call_log_writes_full_input_and_output(self):
        input_content = "input-content-" * 100
        output_content = "output-content-" * 100
        expected_output = {"content": output_content}

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            module,
            "_resolve_mcp_tool_log_dir",
            return_value=Path(temp_dir),
        ):
            result = module._run_mcp_tool_call(
                "demo_tool",
                {
                    "session_id": "session-1",
                    "content": input_content,
                },
                lambda: expected_output,
            )

            log_paths = list(Path(temp_dir).glob("mcp_tools_*.jsonl"))
            records = log_paths[0].read_text(encoding="utf-8").splitlines()

        self.assertEqual(result, expected_output)
        self.assertEqual(len(log_paths), 1)
        self.assertEqual(len(records), 1)

        record = json.loads(records[0])
        self.assertEqual(record["event"], "mcp_tool_call")
        self.assertEqual(record["tool"], "demo_tool")
        self.assertEqual(record["session_id"], "session-1")
        self.assertEqual(record["status"], "success")
        self.assertEqual(record["input"]["content"], input_content)
        self.assertEqual(record["output"]["content"], output_content)
        self.assertNotIn("input_summary", record)
        self.assertNotIn("output_summary", record)
        self.assertNotIn("truncated", record)


if __name__ == "__main__":
    unittest.main()
