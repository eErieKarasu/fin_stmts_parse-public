import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from types import SimpleNamespace

import fitz

from apps.fin_stmts_parse.src.base_financial_processor import BaseFinancialProcessor
from apps.fin_stmts_parse.src.page_classification import PageDiscoveryError, classification
from apps.fin_stmts_parse.src.pdf_page_discovery import (
    PDFPageDiscovery, classify_statement_text, group_statement_pages, resolve_continuations,
    restore_statement_title_lines,
)
from apps.fin_stmts_parse.src.pdf_financial_parser import PDFFinancialProcessor
from apps.fin_stmts_parse.tests.test_statement_page_processor import make_page_processor


PROSE = "公司坚持服务客户，重视产品研发和质量管理，积极拓展销售渠道，持续提升客户服务水平。" * 4


def statement_text(kind="利润表", *, continuation=False):
    subjects = {
        "资产负债表": ["货币资金", "存货", "资产总计"],
        "利润表": ["营业收入", "营业成本", "净利润"],
        "现金流量表": ["销售商品收到的现金", "购买商品支付的现金", "现金及现金等价物"],
    }[kind.removeprefix("合并")]
    headers = "年初余额 | 期末余额" if "资产负债表" in kind else "上期金额 | 本期金额"
    title = kind + ("（续）" if continuation else "")
    return (f"# {title}\n编制单位：测试有限公司\n2024年12月31日\n单位：元\n"
            f"| 项目 | {headers} |\n| --- | --- | --- |\n" +
            "\n".join(f"| {name} | 90 | 100 |" for name in subjects))


PROFIT = statement_text("合并利润表")


def model_payload(kind="利润表", markdown=None, company="测试有限公司"):
    return {"title": kind, "company_name": company, "date_raw": "2024年12月31日", "unit": "元",
            "markdown": markdown if markdown is not None else statement_text(kind)}


def make_group_processor(*, use_paddle=True):
    processor = make_page_processor(use_paddle=use_paddle)
    processor.extract_discovery_text.return_value = statement_text()
    processor.extract_statement_group_with_vl = mock.Mock(side_effect=lambda images, kind: model_payload(kind))
    processor.extract_company_name_from_image = mock.Mock(side_effect=AssertionError("extra image company call"))
    processor.extract_statement_metadata_with_vl = mock.Mock(side_effect=AssertionError("extra metadata call"))
    processor.company_name_resolver.extract_from_text = mock.Mock(side_effect=AssertionError("extra text company call"))
    return processor


class TextClassificationTest(unittest.TestCase):
    def test_only_explicit_notes_heading_marks_section_boundary(self):
        result = classify_statement_text("# 2024年度财务报表附注\n" + PROSE)
        self.assertEqual(result.get("document_section"), "notes")
        for text in (PROSE + "请参见财务报表附注", "# 审计报告\n" + PROSE,
                     "目录\n资产负债表........10\n利润表........11\n财务报表附注........12"):
            self.assertNotIn("document_section", classify_statement_text(text))

    def test_six_titles_and_aliases_match(self):
        for kind in ("资产负债表", "利润表", "现金流量表", "合并资产负债表", "合并利润表", "合并现金流量表"):
            with self.subTest(kind=kind):
                result = classify_statement_text(statement_text(kind))
                self.assertEqual(result["status"], "matched")
                self.assertEqual(result["table_type"], kind)
        result = classify_statement_text(statement_text().replace("# 利润表", "# 母公司损 益 表（续）"))
        self.assertEqual(result["table_type"], "利润表")

    def test_prose_toc_and_explicit_other_statements_are_negative(self):
        for text in (PROSE, PROSE + "请参见资产负债表", "目录\n资产负债表........10\n利润表........11",
                     "目录\n资产负债表\n10\n利润表\n11\n现金流量表\n12",
                     "# 合并所有者权益变动表\n项目 本期 上期\n未分配利润 10 20\n实收资本 30 40"):
            with self.subTest(text=text[:30]):
                self.assertEqual(classify_statement_text(text)["status"], "not_matched")

    def test_ambiguous_or_broken_text_remains_uncertain(self):
        for text in ("", "�" * 100, "资产负债表", "会企01表", "会企０２表", "续表",
                     PROFIT + "\n现金流量表", "balance sheet " * 20):
            with self.subTest(text=text[:30]):
                result = classify_statement_text(text)
                self.assertEqual(result["status"], "uncertain")
                self.assertIsNone(result["has_target_table"])

    def test_equity_movement_without_title_is_not_balance_continuation(self):
        text = "项目 其他权益工具 资本公积 其他综合收益 专项储备 未分配利润 所有者权益合计\n本期增减变动 10 20\n利润分配 30 40"
        self.assertEqual(classify_statement_text(text)["status"], "not_matched")

    def test_untitled_continuation_uses_neighbor_scope(self):
        text = statement_text("资产负债表").replace("# 资产负债表", "续表")
        detections = {0: classify_statement_text(statement_text("合并资产负债表")), 1: classify_statement_text(text)}
        resolve_continuations(detections)
        self.assertEqual(detections[1]["table_type"], "合并资产负债表")
        self.assertEqual(group_statement_pages(detections, {"合并资产负债表"})[0]["pages"], [0, 1])

    def test_conflicting_neighbors_leave_scope_uncertain(self):
        text = statement_text("资产负债表").replace("# 资产负债表", "续表")
        detections = {0: classify_statement_text(statement_text("合并资产负债表")),
                      1: classify_statement_text(text), 2: classify_statement_text(statement_text("资产负债表"))}
        resolve_continuations(detections)
        self.assertEqual(detections[1]["status"], "uncertain")


class TitleGeometryTest(unittest.TestCase):
    @staticmethod
    def ocr_page(kind, fragments, *, supplement=False):
        # 与扫描件一致：大字距标题拆框，正文仍具有完整的科目和金额。
        texts = [fragment[0] for fragment in fragments]
        boxes = [[[left, top], [right, top], [right, bottom], [left, bottom]]
                 for _, left, top, right, bottom in fragments]
        body = statement_text(kind).splitlines()[1:]
        if supplement:
            body.extend(["补充资料", "净利润 10 20", "财务费用 30 40"])
        for index, text in enumerate(body):
            top = 220 + index * 40
            texts.append(text)
            boxes.append([[100, top], [700, top], [700, top + 24], [100, top + 24]])
        return texts, boxes

    def test_fragmented_titles_restore_three_independent_statement_groups(self):
        pages = [
            ("资产负债表", [("资产", 618, 145, 769, 189),
                           ("负", 812, 150, 860, 180), ("债表", 842, 146, 1052, 186)]),
            ("利润表", [("利润表", 600, 130, 800, 170)]),
            ("现金流量表", [(char, 590 + index * 112, 126, 635 + index * 112, 164)
                            for index, char in enumerate("现金流量表")]),
        ]
        detections = {}
        for page, (kind, fragments) in enumerate(pages, 5):
            texts, boxes = self.ocr_page(kind, fragments, supplement=kind == "现金流量表")
            restored = restore_statement_title_lines(texts, boxes)
            detections[page] = classify_statement_text(restored, source="rapidocr")
            self.assertEqual(detections[page]["table_type"], kind)
            self.assertEqual(detections[page]["status"], "matched")
            # 只替换标题，正文的文字框顺序及分隔保持不变。
            self.assertEqual(restored.splitlines()[1:], texts[len(fragments):])
        resolve_continuations(detections)
        self.assertEqual(group_statement_pages(detections, {kind for kind, _ in pages}), [
            {"table_type": "资产负债表", "pages": [5]},
            {"table_type": "利润表", "pages": [6]},
            {"table_type": "现金流量表", "pages": [7]},
        ])

    def test_fragment_order_uses_horizontal_coordinates_and_keeps_scope(self):
        texts, boxes = self.ocr_page("合并资产负债表", [
            ("表（续）", 900, 130, 1040, 170), ("合并", 400, 130, 500, 170),
            ("资产负债", 550, 130, 850, 170),
        ])
        result = classify_statement_text(restore_statement_title_lines(texts, boxes))
        self.assertEqual(result["table_type"], "合并资产负债表")
        self.assertEqual(result["extracted_title"], "合并资产负债表(续)")

    def test_different_visual_rows_are_not_joined(self):
        texts, boxes = self.ocr_page("资产负债表", [
            ("资产", 400, 100, 500, 130), ("负债表", 520, 150, 700, 180),
        ])
        self.assertEqual(restore_statement_title_lines(texts, boxes), "\n".join(texts))

    def test_body_references_are_not_joined_into_titles(self):
        texts, boxes = self.ocr_page("资产负债表", [("报告说明", 400, 100, 700, 130)])
        texts.extend(["资产", "负债表"])
        boxes.extend([[[100, 1000], [200, 1000], [200, 1030], [100, 1030]],
                      [[250, 1000], [400, 1000], [400, 1030], [250, 1030]]])
        self.assertEqual(restore_statement_title_lines(texts, boxes), "\n".join(texts))

    def test_same_row_page_number_or_prose_prevents_title_recovery(self):
        for extra in ("10", "详见"):
            texts, boxes = self.ocr_page("资产负债表", [
                ("资产", 400, 100, 500, 130), ("负债表", 520, 100, 700, 130),
                (extra, 800, 100, 900, 130),
            ])
            self.assertEqual(restore_statement_title_lines(texts, boxes), "\n".join(texts))

    def test_absent_or_invalid_coordinates_preserve_original_text(self):
        texts = ["资产", "负债表", "正文"]
        for boxes in (None, [], [None] * 3, [[[0, 0]] * 4] * 3,
                      [[[0, 0], [100, 0], [100, float("nan")], [0, 30]]] * 3):
            with self.subTest(boxes=boxes):
                self.assertEqual(restore_statement_title_lines(texts, boxes), "\n".join(texts))


class ClassificationFailureTest(unittest.TestCase):
    def test_invalid_vlm_responses_remain_uncertain_for_image_entry(self):
        processor = make_page_processor()
        for response in ('{}', '[]', '不是资产负债表', None, '{"has_target_table":"false"}',
                         '{"has_target_table":true,"table_type":"未知"}'):
            result = processor._parse_analysis_response(response, processor.get_target_tables(None))
            self.assertEqual(result["status"], "uncertain")
            self.assertIsNone(result["has_target_table"])

    def test_image_api_error_is_failed(self):
        processor = make_page_processor()
        processor.encode_image = mock.Mock(return_value="image")
        processor.client.chat.completions.create.side_effect = TimeoutError("timeout")
        result = BaseFinancialProcessor.analyze_page_content(processor, "page.png")
        self.assertEqual(result["status"], "failed")
        processor.analyze_page_content.return_value = result
        with self.assertRaises(PageDiscoveryError):
            processor.process_page("page.png")

    def test_ocr_retry_recovers_without_vlm(self):
        processor = make_group_processor()
        processor.extract_discovery_text.side_effect = [TimeoutError("timeout"), PROSE]
        result = PDFPageDiscovery({}, processor).resolve("page.png", classification("uncertain"))
        self.assertEqual(result["status"], "not_matched")
        self.assertEqual(result["ocr_calls"], 2)
        processor.analyze_page_content.assert_not_called()

    def test_ocr_failure_never_silently_switches_to_model(self):
        processor = make_group_processor()
        processor.extract_discovery_text.side_effect = TimeoutError("timeout")
        result = PDFPageDiscovery({}, processor).resolve("page.png", classification("uncertain"))
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["has_target_table"])
        processor.analyze_page_content.assert_not_called()

    def test_orientation_failure_does_not_attempt_ocr(self):
        processor = make_group_processor()
        processor.correct_image_orientation.side_effect = RuntimeError("orientation failed")
        result = PDFPageDiscovery({}, processor).resolve("page.png", classification("uncertain"))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["source"], "orientation")
        self.assertEqual(result["ocr_calls"], 0)
        processor.extract_discovery_text.assert_not_called()

    def test_empty_ocr_is_uncertain_not_a_negative_page(self):
        processor = make_group_processor()
        processor.extract_discovery_text.return_value = ""
        result = PDFPageDiscovery({}, processor).resolve("page.png", classification("uncertain"))
        self.assertEqual(result["status"], "uncertain")
        self.assertIsNone(result["has_target_table"])


class DiscoveryIntegrationTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def pdf(self, texts):
        path = self.directory / "2024年12月.pdf"
        with fitz.open() as doc:
            for text in texts:
                page = doc.new_page()
                if text:
                    page.insert_textbox(page.rect + (20, 20, -20, -20), text, fontname="china-s", fontsize=10)
            doc.save(path)
        return path

    def test_native_prose_needs_no_render_or_remote_call(self):
        processor = make_group_processor()
        parser = PDFFinancialProcessor({}, page_processor=processor)
        parser.page_renderer.render = mock.Mock()
        self.assertEqual(parser.process_pdf(str(self.pdf([PROSE] * 12))), [])
        parser.page_renderer.render.assert_not_called()
        processor.extract_discovery_text.assert_not_called()
        processor.analyze_page_content.assert_not_called()
        processor.extract_statement_group_with_vl.assert_not_called()

    def test_native_statement_only_calls_group_extraction(self):
        processor = make_group_processor(use_paddle=False)
        parser = PDFFinancialProcessor({}, page_processor=processor)
        result = parser.process_pdf(str(self.pdf([PROFIT])))
        self.assertEqual(result[0]["表名"], "合并利润表")
        processor.extract_discovery_text.assert_not_called()
        processor.analyze_page_content.assert_not_called()
        processor.extract_statement_group_with_vl.assert_called_once()

    def test_scanned_prose_is_excluded_by_ocr_without_vlm(self):
        processor = make_group_processor()
        processor.extract_discovery_text.return_value = PROSE
        parser = PDFFinancialProcessor({}, page_processor=processor)
        self.assertEqual(parser.process_pdf(str(self.pdf([""]))), [])
        processor.extract_discovery_text.assert_called_once()
        processor.analyze_page_content.assert_not_called()
        processor.extract_statement_group_with_vl.assert_not_called()
        processor._extract_with_paddle.assert_not_called()

    def test_corrected_image_is_shared_by_ocr_and_vlm_and_removed(self):
        # PDF OCR 不依赖旧的 use_paddle 开关；先纠正方向，再识别和解析。
        processor = make_group_processor(use_paddle=False)
        corrected = self.directory / "corrected.png"
        events = []

        def correct(path, **kwargs):
            events.append("orientation")
            corrected.write_bytes(Path(path).read_bytes())
            return str(corrected)

        def ocr(path):
            events.append("ocr")
            self.assertEqual(path, str(corrected))
            self.assertTrue(corrected.exists())
            return statement_text()

        def extract(paths, kind):
            events.append("vlm")
            self.assertEqual(paths, [str(corrected)])
            self.assertTrue(corrected.exists())
            return model_payload(kind)

        processor.correct_image_orientation.side_effect = correct
        processor.extract_discovery_text.side_effect = ocr
        processor.extract_statement_group_with_vl.side_effect = extract
        result = PDFFinancialProcessor({}, page_processor=processor).process_pdf(str(self.pdf([""])))
        self.assertEqual(len(result), 1)
        self.assertEqual(events, ["orientation", "ocr", "vlm"])
        self.assertFalse(corrected.exists())
        processor._extract_with_paddle.assert_not_called()

    def test_corrected_image_removed_even_when_ocr_fails(self):
        processor = make_group_processor()
        corrected = self.directory / "corrected.png"
        corrected.write_bytes(b"rotated")
        processor.correct_image_orientation.side_effect = None
        processor.correct_image_orientation.return_value = str(corrected)
        processor.extract_discovery_text.side_effect = RuntimeError("OCR offline")
        with self.assertRaises(PageDiscoveryError):
            PDFFinancialProcessor({}, page_processor=processor).process_pdf(str(self.pdf([""])))
        processor.correct_image_orientation.assert_called_once()
        self.assertFalse(corrected.exists())

    def test_mixed_image_page_cannot_be_excluded_by_prose(self):
        doc = mock.MagicMock()
        page = doc.__getitem__.return_value
        page.get_text.return_value = PROSE
        page.get_image_info.return_value = [{"bbox": (0, 0, 500, 700)}]
        page.rect.get_area.return_value = 500 * 800
        self.assertEqual(PDFPageDiscovery({}, make_group_processor()).read_native(doc, 0)["status"], "uncertain")

    def test_ocr_failure_writes_diagnostics_and_cleans_up(self):
        processor = make_group_processor()
        processor.extract_discovery_text.side_effect = TimeoutError("offline")
        parser = PDFFinancialProcessor({}, page_processor=processor)
        with self.assertRaises(PageDiscoveryError) as error:
            parser.process_pdf(str(self.pdf(["", ""])), output_dir=str(self.directory))
        self.assertEqual(set(error.exception.pages), {1, 2})
        report = json.loads(next(self.directory.glob("*_discovery.json")).read_text())
        self.assertEqual(report["vlm_calls"], 0)
        self.assertEqual(report["ocr_calls"], 4)
        self.assertEqual(report["pages"]["1"]["status"], "failed")
        self.assertTrue(all(not Path(call.args[0]).exists() for call in processor.extract_discovery_text.call_args_list))
        processor.extract_statement_group_with_vl.assert_not_called()

    def test_six_tables_eight_pages_make_exactly_six_extraction_calls(self):
        processor = make_group_processor()
        kinds = {6: "合并资产负债表", 7: "合并资产负债表", 8: "资产负债表", 9: "资产负债表",
                 10: "合并利润表", 11: "利润表", 12: "合并现金流量表", 13: "现金流量表"}
        processor.extract_discovery_text.side_effect = lambda path: (
            statement_text(kinds[int(Path(path).stem.split('_')[1])])
            if int(Path(path).stem.split('_')[1]) in kinds else PROSE
        )
        parser = PDFFinancialProcessor({}, page_processor=processor)
        result = parser.process_pdf(str(self.pdf([""] * 107)), output_dir=str(self.directory))
        self.assertEqual(len(result), 6)
        self.assertEqual(processor.extract_discovery_text.call_count, 15)
        self.assertEqual(processor.extract_statement_group_with_vl.call_count, 6)
        groups = {call.args[1]: [Path(path).stem for path in call.args[0]]
                  for call in processor.extract_statement_group_with_vl.call_args_list}
        self.assertEqual(groups["合并资产负债表"], ["page_06", "page_07"])
        self.assertEqual(groups["资产负债表"], ["page_08", "page_09"])
        self.assertEqual({item["company_name"] for item in result}, {"测试有限公司"})
        processor.analyze_page_content.assert_not_called()
        processor.extract_company_name_from_image.assert_not_called()
        processor.extract_statement_metadata_with_vl.assert_not_called()
        processor.company_name_resolver.extract_from_text.assert_not_called()
        report = json.loads(next(self.directory.glob("*_discovery.json")).read_text())
        self.assertEqual(report["extraction_calls"], 6)
        self.assertEqual(report["vlm_calls"], 0)
        self.assertEqual(report["scanned_pages"], 15)

    def test_last_continuation_is_read_beyond_window(self):
        processor = make_group_processor()
        pages = [statement_text("资产负债表"), statement_text("利润表"), statement_text("现金流量表"),
                 statement_text("现金流量表", continuation=True), PROSE]
        processor.extract_discovery_text.side_effect = lambda path: pages[int(Path(path).stem.split('_')[1]) - 1]
        parser = PDFFinancialProcessor({"pdf_parse": {"page_scan": {
            "initial_window_pages": 3, "fallback_full_scan": False,
        }}}, page_processor=processor)
        result = parser.process_pdf(str(self.pdf([""] * 5)), is_consolidated=False)
        self.assertEqual(len(result), 3)
        self.assertEqual(processor.extract_discovery_text.call_count, 5)
        calls = processor.extract_statement_group_with_vl.call_args_list
        self.assertEqual(len(next(call.args[0] for call in calls if call.args[1] == "现金流量表")), 2)

    def test_default_does_not_stop_after_only_three_standalone_tables(self):
        processor = make_group_processor()
        types = ["资产负债表", "利润表", "现金流量表", "合并资产负债表", "合并利润表", "合并现金流量表"]
        result = PDFFinancialProcessor({}, page_processor=processor).process_pdf(
            str(self.pdf([statement_text(kind) for kind in types] + [PROSE]))
        )
        self.assertEqual(len(result), 6)
        self.assertEqual(processor.extract_statement_group_with_vl.call_count, 6)

    def test_three_located_tables_are_extracted_despite_unresolved_pages(self):
        processor = make_group_processor()
        kinds = {5: "资产负债表", 6: "利润表", 7: "现金流量表"}

        def ocr(path):
            page = int(Path(path).stem.split('_')[1])
            if page in kinds:
                return statement_text(kinds[page])
            if page == 10:
                raise TimeoutError("OCR timeout")
            return "" if page in (1, 2, 3, 4, 9, 18, 19, 24, 25) else PROSE

        processor.extract_discovery_text.side_effect = ocr
        result = PDFFinancialProcessor({}, page_processor=processor).process_pdf(
            str(self.pdf([""] * 27)), output_dir=str(self.directory),
        )
        self.assertEqual({item["表名"] for item in result}, set(kinds.values()))
        self.assertEqual(processor.extract_statement_group_with_vl.call_count, 3)
        report = json.loads(next(self.directory.glob("*_discovery.json")).read_text())
        self.assertEqual(report["extraction_calls"], 3)
        self.assertEqual(report["discovery_status"], "partial")
        self.assertIn(10, report["unresolved_pages"])
        self.assertEqual(report["pages"]["10"]["status"], "failed")
        self.assertIsNone(report["pages"]["1"]["has_target_table"])

    def test_notes_boundary_stops_without_waiting_for_consolidated_tables(self):
        processor = make_group_processor()
        pages = ["", statement_text("资产负债表"), statement_text("利润表"),
                 statement_text("现金流量表"), statement_text("现金流量表", continuation=True),
                 "# 财务报表附注\n" + PROSE]
        processor.extract_discovery_text.side_effect = lambda path: pages[int(Path(path).stem.split('_')[1]) - 1]
        result = PDFFinancialProcessor({}, page_processor=processor).process_pdf(
            str(self.pdf([""] * 27)), output_dir=str(self.directory),
        )
        self.assertEqual(len(result), 3)
        self.assertEqual(processor.extract_discovery_text.call_count, 6)
        cash_flow = next(call for call in processor.extract_statement_group_with_vl.call_args_list
                         if call.args[1] == "现金流量表")
        self.assertEqual(len(cash_flow.args[0]), 2)
        report = json.loads(next(self.directory.glob("*_discovery.json")).read_text())
        self.assertEqual(report["stop_reason"], "notes_section")
        self.assertEqual(report["unresolved_pages"], [1])

    def test_even_one_table_can_be_extracted_when_others_are_unresolved(self):
        processor = make_group_processor()
        processor.extract_discovery_text.side_effect = lambda path: (
            statement_text("资产负债表") if Path(path).stem == "page_02" else ""
        )
        result = PDFFinancialProcessor({}, page_processor=processor).process_pdf(str(self.pdf([""] * 3)))
        self.assertEqual([item["表名"] for item in result], ["资产负债表"])
        processor.extract_statement_group_with_vl.assert_called_once()


class SingleModelRequestTest(unittest.TestCase):
    def test_one_multimodal_call_contains_all_pages_and_metadata(self):
        processor = make_page_processor()
        processor.encode_image = mock.Mock(return_value="encoded")
        client = processor.client.with_options.return_value
        client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(content=json.dumps(model_payload("资产负债表"))),
        )])
        payload = processor.extract_statement_group_with_vl(["one.png", "two.png"], "资产负债表")
        self.assertEqual(payload["company_name"], "测试有限公司")
        processor.client.with_options.assert_called_once_with(max_retries=0)
        client.chat.completions.create.assert_called_once()
        content = client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        self.assertEqual(sum(item["type"] == "image_url" for item in content), 2)
        self.assertIn("company_name", content[0]["text"])

    def test_truncated_response_is_error_without_retry(self):
        processor = make_page_processor()
        processor.encode_image = mock.Mock(return_value="encoded")
        client = processor.client.with_options.return_value
        client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(finish_reason="length")])
        with self.assertRaisesRegex(RuntimeError, "未完整结束"):
            processor.extract_statement_group_with_vl(["one.png"], "利润表")
        client.chat.completions.create.assert_called_once()

    def test_invalid_model_data_does_not_trigger_another_extraction(self):
        processor = make_group_processor()
        processor.extract_statement_group_with_vl.side_effect = None
        processor.extract_statement_group_with_vl.return_value = model_payload(markdown="没有表格")
        with self.assertRaisesRegex(ValueError, "数据校验"):
            processor.process_statement(["page.png"], table_type="利润表", source_file_path="demo.pdf", page_numbers=[1])
        processor.extract_statement_group_with_vl.assert_called_once()
        processor.extract_table_with_vl.assert_not_called()
        processor.extract_company_name_from_image.assert_not_called()


if __name__ == "__main__":
    unittest.main()
