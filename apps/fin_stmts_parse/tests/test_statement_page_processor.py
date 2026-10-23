import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import fitz
import requests

from apps.fin_stmts_parse.src.base_financial_processor import BaseFinancialProcessor
from apps.fin_stmts_parse.src.image_financial_parser import ImageFinancialProcessor
from apps.fin_stmts_parse.src.pdf_financial_parser import PDFFinancialProcessor
from apps.fin_stmts_parse.src.statement_metadata_resolver import StatementPageMetadata
from apps.fin_stmts_parse.src.statement_page_processor import StatementPageProcessor


def profit_markdown(company="测试有限公司", item="营业收入", value=100):
    return (
        f"# 利润表\n编制单位：{company}\n2026年3月31日\n单位：元\n\n"
        "| 项目 | 上年同期累计金额 | 本年累计金额 |\n| --- | --- | --- |\n"
        f"| {item} | 90 | {value} |"
    )


def make_page_processor(*, use_paddle=False):
    with mock.patch.object(BaseFinancialProcessor, "_initialize_openai_client"):
        processor = StatementPageProcessor({}, use_paddle=use_paddle)
    processor.logger = mock.Mock()
    processor.analyze_page_content = mock.Mock(return_value={
        "has_target_table": True, "table_type": "利润表", "extracted_title": "利润表",
    })
    processor.remove_watermark_from_file = mock.Mock(side_effect=lambda path, **kwargs: path)
    processor.correct_image_orientation = mock.Mock(side_effect=lambda path, **kwargs: path)
    processor.extract_company_name_from_image = mock.Mock(return_value="")
    processor.extract_statement_metadata_with_vl = mock.Mock(return_value=StatementPageMetadata())
    processor.extract_table_with_vl = mock.Mock(return_value=profit_markdown())
    processor._extract_with_paddle = mock.Mock(return_value=profit_markdown())
    processor.extract_discovery_text = mock.Mock(return_value=profit_markdown())
    return processor


class StatementPageProcessorTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.source = self.directory / "2026年3月.png"
        self.source.write_bytes(b"source image")
        self.processor = make_page_processor(use_paddle=True)

    def test_non_statement_skips_preprocessing_and_extraction(self):
        self.processor.analyze_page_content.return_value = {"has_target_table": False}
        self.assertIsNone(self.processor.process_page(str(self.source)))
        self.processor.remove_watermark_from_file.assert_not_called()
        self.processor._extract_with_paddle.assert_not_called()
        self.assertTrue(self.source.exists())

    def test_reuses_pdf_classification_and_original_filename(self):
        analysis = self.processor.analyze_page_content.return_value
        result = self.processor.process_page(
            str(self.source), analysis_result=analysis,
            source_file_path="/reports/2026年3月.pdf", page_number=7,
        )
        self.processor.analyze_page_content.assert_not_called()
        self.assertEqual(result.source_file_path, "/reports/2026年3月.pdf")
        self.assertEqual(result.page_number, 7)
        self.assertEqual(result.metadata.date, "202603")
        self.assertTrue(result.is_valid)
        self.processor.extract_table_with_vl.assert_not_called()
        self.assertTrue(self.source.exists())

    def test_paddle_failure_retries_once_and_uses_final_company_name(self):
        self.processor._extract_with_paddle.return_value = "提取失败: API 调用超时"
        self.processor.extract_table_with_vl.return_value = profit_markdown(company="回退公司")
        attempts = []
        result = self.processor.process_page(
            str(self.source), on_extraction=lambda method, content: attempts.append((method, content))
        )
        self.assertTrue(result.is_valid)
        self.assertEqual(result.extraction_method, "VL大模型(回退)")
        self.assertEqual(result.company_name, "回退公司")
        self.assertEqual(result.metadata.company_name, "回退公司")
        self.processor.extract_table_with_vl.assert_called_once()
        self.assertEqual([item[0] for item in attempts], ["PaddleOCRVL", "VL大模型(回退)"])
        self.assertIn("回退公司", attempts[-1][1])

    def test_invalid_fallback_keeps_last_result(self):
        self.processor._extract_with_paddle.return_value = "首次提取失败"
        self.processor.extract_table_with_vl.return_value = "回退也无表格"
        result = self.processor.process_page(str(self.source))
        self.assertFalse(result.is_valid)
        self.assertEqual(result.markdown, "回退也无表格")
        self.assertEqual(result.extraction_method, "VL大模型(回退-仍无效)")
        self.assertEqual(result.variants[0].data, {})

    def test_raised_fallback_keeps_primary_result(self):
        self.processor._extract_with_paddle.return_value = "首次提取失败"
        self.processor.extract_table_with_vl.side_effect = RuntimeError("VLM unavailable")
        result = self.processor.process_page(str(self.source))
        self.assertFalse(result.is_valid)
        self.assertEqual(result.markdown, "首次提取失败")
        self.assertEqual(result.extraction_method, "PaddleOCRVL")

    def test_vlm_primary_is_not_retried(self):
        processor = make_page_processor()
        processor.extract_table_with_vl.return_value = "无表格"
        result = processor.process_page(str(self.source))
        self.assertFalse(result.is_valid)
        processor.extract_table_with_vl.assert_called_once()
        processor._extract_with_paddle.assert_not_called()

    def test_http_timeout_from_paddle_uses_vlm_fallback(self):
        del self.processor._extract_with_paddle
        with mock.patch("requests.post", side_effect=requests.exceptions.Timeout) as post:
            result = self.processor.process_page(str(self.source))
        self.assertTrue(result.is_valid)
        self.assertEqual(result.extraction_method, "VL大模型(回退)")
        self.assertEqual(post.call_args.kwargs["json"]["fileType"], 1)
        self.processor.extract_table_with_vl.assert_called_once()

    def test_paddle_layout_markdown_is_normalized_before_parsing(self):
        del self.processor._extract_with_paddle
        response = mock.Mock(status_code=200)
        response.json.return_value = {"result": {"layoutParsingResults": [
            {"markdown": {"text": profit_markdown().replace("| 100 |", "| $100$ |")}},
        ]}}
        with mock.patch("requests.post", return_value=response):
            result = self.processor.process_page(str(self.source))
        self.assertTrue(result.is_valid)
        self.assertNotIn("$100$", result.markdown)
        self.assertEqual(result.variants[0].data["营业收入"], [90.0, 100.0])
        self.processor.extract_table_with_vl.assert_not_called()

    def test_any_invalid_variant_triggers_fallback(self):
        invalid = [
            {"table_type": "合并利润表", "is_consolidated": True, "data": {"营业收入": [90, 100]}},
            {"table_type": "利润表", "is_consolidated": False, "data": {}},
        ]
        valid = [dict(invalid[0]), dict(invalid[1], data={"营业收入": [9, 10]})]
        self.processor._parse_extracted_statement_variants = mock.Mock(side_effect=[invalid, valid])
        result = self.processor.process_page(str(self.source))
        self.assertTrue(result.is_valid)
        self.assertEqual(len(result.variants), 2)
        self.processor.extract_table_with_vl.assert_called_once()

    def test_cleanup_runs_after_metadata_failure(self):
        processed = self.directory / "processed.png"
        rotated = self.directory / "rotated.png"
        processed.write_bytes(b"processed")
        rotated.write_bytes(b"rotated")
        self.processor.remove_watermark_from_file.return_value = str(processed)
        self.processor.remove_watermark_from_file.side_effect = None
        self.processor.correct_image_orientation.return_value = str(rotated)
        self.processor.correct_image_orientation.side_effect = None
        self.processor.metadata_resolver.extract_statement_metadata_from_text = mock.Mock(
            side_effect=RuntimeError("metadata failure")
        )
        with self.assertRaisesRegex(RuntimeError, "metadata failure"):
            self.processor.process_page(str(self.source))
        self.assertTrue(self.source.exists())
        self.assertFalse(processed.exists())
        self.assertFalse(rotated.exists())

    def test_cleanup_deduplicates_paths_and_preserves_source(self):
        processed = self.directory / "processed.png"
        for rotation_returns_source in (False, True):
            with self.subTest(rotation_returns_source=rotation_returns_source):
                processed.write_bytes(b"processed")
                self.processor.remove_watermark_from_file.side_effect = None
                self.processor.remove_watermark_from_file.return_value = str(processed)
                self.processor.correct_image_orientation.side_effect = None
                self.processor.correct_image_orientation.return_value = str(
                    self.source if rotation_returns_source else processed
                )
                with mock.patch(
                    "apps.fin_stmts_parse.src.statement_page_processor.os.remove", wraps=os.remove
                ) as remove:
                    self.processor.process_page(str(self.source))
                    remove.assert_called_once_with(str(processed))
                self.assertTrue(self.source.exists())

    def test_raw_extraction_is_available_when_parsing_raises(self):
        attempts = []
        self.processor._parse_extracted_statement_variants = mock.Mock(side_effect=ValueError("parse failure"))
        with self.assertRaisesRegex(ValueError, "parse failure"):
            self.processor.process_page(
                str(self.source), on_extraction=lambda method, text: attempts.append((method, text))
            )
        self.assertEqual(attempts, [("PaddleOCRVL", profit_markdown())])


class DocumentPageIntegrationTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def make_pdf(self, count):
        path = self.directory / "2026年3月.pdf"
        with fitz.open() as doc:
            for _ in range(count):
                doc.new_page(width=100, height=100)
            doc.save(path)
        return path

    def test_pdf_and_image_share_output_contract(self):
        from apps.fin_stmts_parse.tests.test_pdf_page_discovery import make_group_processor, model_payload, statement_text
        pdf_path = self.make_pdf(1).rename(self.directory / "2024年12月.pdf")
        image_path = self.directory / "2024年12月.png"
        image_path.write_bytes(b"source image")
        results = []
        for processor_cls, source in ((PDFFinancialProcessor, pdf_path), (ImageFinancialProcessor, image_path)):
            processor = make_page_processor(use_paddle=True)
            processor.extract_discovery_text.return_value = statement_text()
            processor._extract_with_paddle.return_value = statement_text()
            processor.extract_statement_group_with_vl = mock.Mock(return_value=model_payload())
            parser = processor_cls({}, page_processor=processor)
            if processor_cls is PDFFinancialProcessor:
                result = parser.process_pdf(str(source), output_dir=str(self.directory / "pdf"))
                self.assertEqual(result[0]["page"], 1)
                processor.analyze_page_content.assert_not_called()
                processor.extract_statement_group_with_vl.assert_called_once()
            else:
                result = parser.process_image(str(source))
                self.assertNotIn("page", result[0])
            results.append(result[0])
        for key in ("表名", "日期", "单位", "company_name", "合并", "数据", "Markdown"):
            self.assertEqual(results[0][key], results[1][key], key)

    def test_pdf_merges_pages_in_one_request_and_releases_images(self):
        from apps.fin_stmts_parse.tests.test_pdf_page_discovery import make_group_processor, model_payload, statement_text
        processor = make_group_processor()
        pdf_path = self.make_pdf(2)
        processor.extract_discovery_text.return_value = statement_text()
        processor.extract_statement_group_with_vl.side_effect = None
        processor.extract_statement_group_with_vl.return_value = model_payload()
        parser = PDFFinancialProcessor({}, page_processor=processor)
        result = parser.process_pdf(str(pdf_path), output_dir=str(self.directory))
        self.assertEqual(len(result), 1)
        self.assertEqual(set(result[0]["数据"]), {"营业收入", "营业成本", "净利润"})
        processor.extract_statement_group_with_vl.assert_called_once()
        paths = processor.extract_statement_group_with_vl.call_args.args[0]
        self.assertEqual([Path(path).stem for path in paths], ["page_01", "page_02"])
        self.assertTrue(all(not Path(path).exists() for path in paths))
        self.assertTrue(pdf_path.exists())

    def test_failed_group_is_reported_after_other_group_finishes(self):
        from apps.fin_stmts_parse.tests.test_pdf_page_discovery import make_group_processor, statement_text
        processor = make_group_processor()
        processor.extract_discovery_text.side_effect = lambda path: statement_text(
            "资产负债表" if Path(path).stem == "page_01" else "利润表"
        )
        process_statement = processor.process_statement
        def process(images, **kwargs):
            if kwargs["table_type"] == "资产负债表":
                raise RuntimeError("group extraction failed")
            return process_statement(images, **kwargs)
        processor.process_statement = mock.Mock(side_effect=process)
        parser = PDFFinancialProcessor({}, page_processor=processor)
        with self.assertRaisesRegex(RuntimeError, "group extraction failed"):
            parser.process_pdf(str(self.make_pdf(2)), output_dir=str(self.directory))
        self.assertEqual(processor.process_statement.call_count, 2)
        self.assertEqual(len(list(self.directory.glob("*_raw.md"))), 1)

    def test_missing_metadata_does_not_trigger_extra_model_calls(self):
        from apps.fin_stmts_parse.tests.test_pdf_page_discovery import make_group_processor
        processor = make_group_processor()
        processor.extract_statement_group_with_vl.side_effect = None
        processor.extract_statement_group_with_vl.return_value = {
            "title": "利润表", "company_name": "", "date_raw": "", "unit": "",
            "markdown": "| 项目 | 上期金额 | 本期金额 |\n| --- | --- | --- |\n| 营业收入 | 1 | 2 |",
        }
        result = processor.process_statement(["image.png"], table_type="利润表", source_file_path="demo.pdf", page_numbers=[1])
        self.assertEqual(result.company_name, "")
        self.assertEqual(result.metadata.date, "N/A")
        processor.extract_statement_group_with_vl.assert_called_once()
        processor.extract_statement_metadata_with_vl.assert_not_called()
        processor.extract_company_name_from_image.assert_not_called()


if __name__ == "__main__":
    unittest.main()
