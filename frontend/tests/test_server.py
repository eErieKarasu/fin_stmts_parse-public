import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from frontend import server
from frontend.server import Handler


class FrontendMultiUploadTests(unittest.TestCase):
    def test_index_uses_configured_mcp_url(self):
        index_path = server.ROOT / "index.html"
        with patch.object(server, "DEFAULT_MCP_URL", "http://127.0.0.1:8001/mcp?a=1&b=2"):
            rendered = server.read_frontend_asset(index_path).decode("utf-8")

        self.assertIn(
            'value="http://127.0.0.1:8001/mcp?a=1&amp;b=2"',
            rendered,
        )
        self.assertNotIn(server.MCP_URL_PLACEHOLDER, rendered)

    def test_save_uploads_collects_all_files_and_deduplicates_names(self):
        form = {
            "files": [
                SimpleNamespace(filename="report.pdf", file=io.BytesIO(b"first")),
                SimpleNamespace(filename="report.pdf", file=io.BytesIO(b"second")),
                SimpleNamespace(filename="profit.xlsx", file=io.BytesIO(b"third")),
            ]
        }

        with tempfile.TemporaryDirectory() as upload_dir:
            saved_files = Handler.save_uploads(form, upload_dir)
            saved_contents = [
                (Path(item["path"]).name, Path(item["path"]).read_bytes())
                for item in saved_files
            ]

        self.assertEqual(
            [item["fileName"] for item in saved_files],
            ["report.pdf", "report_1.pdf", "profit.xlsx"],
        )
        self.assertEqual(
            saved_contents,
            [
                ("report.pdf", b"first"),
                ("report_1.pdf", b"second"),
                ("profit.xlsx", b"third"),
            ],
        )


class FrontendMultiUploadPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_upload_pipeline_sends_all_files_in_one_parse_call(self):
        files = [
            {"path": "/tmp/first.pdf", "fileName": "first.pdf"},
            {"path": "/tmp/second.xlsx", "fileName": "second.xlsx"},
        ]
        parse_results = [
            {"file_name": "first.pdf", "markdown_files": []},
            {"file_name": "second.xlsx", "markdown_files": []},
        ]
        pipeline_result = {
            "parse_results": parse_results,
            "map_results": [],
            "inspect_result": [],
        }

        with patch.object(
            server,
            "call_tool",
            new=AsyncMock(return_value=parse_results),
        ) as mock_call_tool, patch.object(
            server,
            "run_map_inspect_pipeline",
            new=AsyncMock(return_value=pipeline_result),
        ) as mock_map_inspect:
            result = await server.run_upload_pipeline(
                {
                    "mcp_url": "http://127.0.0.1:8765/",
                    "session_id": "frontend-test",
                    "files": files,
                    "report_status": "0",
                }
            )

        mock_call_tool.assert_awaited_once_with(
            "http://127.0.0.1:8765/",
            "parse_fin_stmts_markdown",
            {"files": files, "session_id": "frontend-test"},
            progress_callback=None,
        )
        mock_map_inspect.assert_awaited_once_with(
            mcp_url="http://127.0.0.1:8765/",
            session_id="frontend-test",
            parse_results=parse_results,
            report_status="0",
            progress_callback=None,
        )
        self.assertEqual(result, pipeline_result)


if __name__ == "__main__":
    unittest.main()
