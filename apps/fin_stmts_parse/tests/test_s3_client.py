import unittest
from unittest import mock

from botocore.exceptions import ClientError

from apps.fin_stmts_parse.utils.s3_client import S3Client


class S3ClientUploadFileTest(unittest.TestCase):
    def setUp(self) -> None:
        self._instances = dict(S3Client._instances)
        self._connection_locks = dict(S3Client._connection_locks)
        S3Client._instances.clear()
        S3Client._connection_locks.clear()

    def tearDown(self) -> None:
        S3Client._instances.clear()
        S3Client._instances.update(self._instances)
        S3Client._connection_locks.clear()
        S3Client._connection_locks.update(self._connection_locks)

    def test_upload_file_returns_presigned_url(self) -> None:
        ins = S3Client("oss")
        ins.bucket = "demo-bucket"
        ins.s3_client = mock.Mock()
        ins.s3_client.generate_presigned_url.return_value = "http://example.com/presigned"

        with mock.patch.object(S3Client, "_ensure_ready", return_value=True):
            file_url = S3Client.upload_file(
                "/tmp/report.pdf",
                "llm/report_gen/report.pdf",
                days=7,
                config_key="oss",
                expires=7200,
            )

        self.assertEqual(file_url, "http://example.com/presigned")
        ins.s3_client.upload_file.assert_called_once()
        upload_args, upload_kwargs = ins.s3_client.upload_file.call_args
        self.assertEqual(upload_args[:3], ("/tmp/report.pdf", "demo-bucket", "llm/report_gen/report.pdf"))
        self.assertIn("ExpiryDays=7", upload_kwargs["ExtraArgs"]["Tagging"])
        ins.s3_client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "demo-bucket", "Key": "llm/report_gen/report.pdf"},
            ExpiresIn=7200,
        )

    def test_upload_file_returns_none_on_client_error(self) -> None:
        ins = S3Client("oss")
        ins.bucket = "demo-bucket"
        ins.s3_client = mock.Mock()
        ins.s3_client.upload_file.side_effect = ClientError(
            error_response={"Error": {"Code": "500", "Message": "boom"}},
            operation_name="upload_file",
        )

        with mock.patch.object(S3Client, "_ensure_ready", return_value=True):
            file_url = S3Client.upload_file("/tmp/report.pdf", "llm/report_gen/report.pdf", config_key="oss")

        self.assertIsNone(file_url)
        ins.s3_client.generate_presigned_url.assert_not_called()


if __name__ == "__main__":
    unittest.main()
