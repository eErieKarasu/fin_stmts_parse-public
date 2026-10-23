import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from apps.fin_stmts_parse.src.core.audit import AuditFirmEvidence, AuditFirmResult
from lwade_utils.bootload import load_entry_module


os.environ["RUNNING_ENV"] = "local"

module = load_entry_module("apps/fin_stmts_parse_mcp", "mcp", "service.py")


class FinStmtsAuditFirmServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = module.FinStmtsAuditFirmService.__new__(module.FinStmtsAuditFirmService)
        self.service.audit_core = Mock()

    def tearDown(self) -> None:
        module.audit_firm_service = None

    def test_audit_firm_supports_local_path_input(self):
        self.service.audit_core.extract_local_file.return_value = AuditFirmResult(
            audit_status="audited",
            audit_firm_name="中兴华会计师事务所（特殊普通合伙）",
            confidence="high",
            evidence=[
                AuditFirmEvidence(
                    page=3,
                    text="中兴华会计师事务所（特殊普通合伙）",
                )
            ],
        )

        with patch.object(module, "batch_download", return_value=None):
            result = self.service.fin_stmts_parse_audit_firm(
                files=[{"path": "/tmp/report.pdf"}],
                session_id="session-1",
            )

        self.assertEqual(
            result,
            [
                {
                    "message": "识别成功",
                    "file_name": "report.pdf",
                    "audit_status": "audited",
                    "audit_firm_name": "中兴华会计师事务所（特殊普通合伙）",
                    "confidence": "high",
                    "evidence": [
                        {
                            "page": 3,
                            "text": "中兴华会计师事务所（特殊普通合伙）",
                        }
                    ],
                }
            ],
        )
        self.service.audit_core.extract_local_file.assert_called_once()

    def test_audit_firm_returns_unsupported_file_type(self):
        with patch.object(module, "batch_download", return_value=None):
            result = self.service.fin_stmts_parse_audit_firm(
                files=[{"path": "/tmp/notes.txt"}],
                session_id="session-1",
            )

        self.assertEqual(
            result,
            [
                {
                    "message": "不支持的文件类型",
                    "file_name": "notes.txt",
                    "audit_status": "unknown",
                    "audit_firm_name": "",
                    "confidence": "low",
                    "evidence": [],
                }
            ],
        )
        self.service.audit_core.extract_local_file.assert_not_called()

    def test_audit_firm_failure_is_reported_per_file(self):
        self.service.audit_core.extract_local_file.side_effect = [
            RuntimeError("mocked audit error"),
            AuditFirmResult(audit_status="unaudited", confidence="high"),
        ]

        with patch.object(module, "batch_download", return_value=None):
            result = self.service.fin_stmts_parse_audit_firm(
                files=[
                    {"path": "/tmp/broken.pdf"},
                    {"path": "/tmp/monthly.pdf"},
                ],
                session_id="session-1",
            )

        self.assertEqual(result[0]["message"], "识别失败: mocked audit error")
        self.assertEqual(result[0]["audit_status"], "unknown")
        self.assertEqual(result[1]["message"], "识别成功")
        self.assertEqual(result[1]["audit_status"], "unaudited")

    def test_audit_firm_downloads_to_daily_persistent_dir_without_cleaning(self):
        self.service.audit_core.extract_local_file.return_value = AuditFirmResult(
            audit_status="audited",
            audit_firm_name="测试事务所",
            confidence="high",
        )

        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"MCP_PERSISTENT_BASE_DIR": temp_dir},
        ), patch.object(
            module,
            "batch_download",
            return_value=None,
        ) as mock_download:
            self.service.fin_stmts_parse_audit_firm(
                files=[{"path": "/tmp/report.pdf"}],
                session_id="session-1",
            )

            date_prefix = module.datetime.now().strftime("%Y%m%d")
            expected_download_dir = str(Path(temp_dir) / date_prefix / "download")
            download_args, download_kwargs = mock_download.call_args

        self.assertEqual(download_args[1], expected_download_dir)
        self.assertEqual(download_kwargs["clean_dir"], False)

    def test_audit_firm_requires_session_id(self):
        with self.assertRaisesRegex(ValueError, "session_id 不能为空"):
            self.service.fin_stmts_parse_audit_firm(
                files=[{"path": "/tmp/report.pdf"}],
                session_id="",
            )

    def test_tool_wrapper_only_forwards_files_and_session_id(self):
        expected = [
            {
                "message": "未识别到审计信息",
                "file_name": "demo.pdf",
                "audit_status": "unknown",
                "audit_firm_name": "",
                "confidence": "low",
                "evidence": [],
            }
        ]
        mock_service = Mock()
        mock_service.fin_stmts_parse_audit_firm.return_value = expected

        with patch.object(module, "get_audit_firm_service", return_value=mock_service):
            result = module.fin_stmts_parse_audit_firm(
                files=[{"path": "/tmp/demo.pdf"}],
                session_id="session-1",
            )

        mock_service.fin_stmts_parse_audit_firm.assert_called_once_with(
            files=[{"path": "/tmp/demo.pdf"}],
            session_id="session-1",
        )
        self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
