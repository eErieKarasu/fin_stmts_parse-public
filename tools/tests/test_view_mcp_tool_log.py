import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tools.view_mcp_tool_log import main


class ViewMcpToolLogTests(unittest.TestCase):
    def write_log(self, records):
        temp_dir = tempfile.TemporaryDirectory()
        log_path = Path(temp_dir.name) / "mcp_tools_2026-05-12.jsonl"
        log_path.write_text(
            "\n".join(json.dumps(record, ensure_ascii=False) for record in records),
            encoding="utf-8",
        )
        return temp_dir, log_path

    def test_main_renders_latest_matching_record_as_pretty_blocks(self):
        large_input = "输入内容-" * 100
        large_output = "输出内容-" * 100
        temp_dir, log_path = self.write_log(
            [
                {
                    "event": "mcp_tool_call",
                    "tool": "fin_stmts_parse_map",
                    "session_id": "session-1",
                    "status": "success",
                    "started_at": "2026-05-12T09:00:00.000+08:00",
                    "finished_at": "2026-05-12T09:00:01.000+08:00",
                    "duration_ms": 1000,
                    "input": {"parse_results": []},
                    "output": [{"message": "old"}],
                },
                {
                    "event": "mcp_tool_call",
                    "tool": "fin_stmts_parse_inspect",
                    "session_id": "session-2",
                    "status": "success",
                    "started_at": "2026-05-12T09:01:00.000+08:00",
                    "finished_at": "2026-05-12T09:01:01.000+08:00",
                    "duration_ms": 1000,
                    "input": {"content": large_input},
                    "output": [{"message": large_output}],
                },
            ]
        )

        try:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        str(log_path),
                        "--tool",
                        "fin_stmts_parse_inspect",
                        "--latest",
                    ]
                )
        finally:
            temp_dir.cleanup()

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("=== MCP TOOL fin_stmts_parse_inspect ===", output)
        self.assertIn("--- input ---", output)
        self.assertIn("--- output ---", output)
        self.assertIn(large_input, output)
        self.assertIn(large_output, output)
        self.assertNotIn("fin_stmts_parse_map", output)

    def test_main_renders_error_record(self):
        temp_dir, log_path = self.write_log(
            [
                {
                    "event": "mcp_tool_call",
                    "tool": "fin_stmts_parse_map",
                    "session_id": "session-1",
                    "status": "error",
                    "started_at": "2026-05-12T09:00:00.000+08:00",
                    "finished_at": "2026-05-12T09:00:01.000+08:00",
                    "duration_ms": 1000,
                    "input": {"parse_results": {"bad": "payload"}},
                    "error": {
                        "type": "ValueError",
                        "message": "parse_results 必须是 parse_fin_stmts_markdown 的完整输出",
                        "traceback": "Traceback ...",
                    },
                },
            ]
        )

        try:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main([str(log_path), "--status", "error"])
        finally:
            temp_dir.cleanup()

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("--- error ---", output)
        self.assertIn("ValueError", output)
        self.assertIn("parse_results 必须是 parse_fin_stmts_markdown 的完整输出", output)


if __name__ == "__main__":
    unittest.main()
