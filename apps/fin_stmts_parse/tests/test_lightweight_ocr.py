import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import cv2
import numpy as np

from apps.fin_stmts_parse.src import lightweight_ocr
from apps.fin_stmts_parse.src.base_financial_processor import BaseFinancialProcessor
from apps.fin_stmts_parse.src.orientation_inference import OrientationInferenceError


class LightweightOCRTest(unittest.TestCase):
    def test_ocr_coordinates_restore_fragmented_title(self):
        result = SimpleNamespace(
            txts=("资产", "负债表", "项目 期初 期末", "货币资金 10 20", "资产总计 30 40"),
            boxes=[[[left, top], [right, top], [right, top + 30], [left, top + 30]]
                   for left, right, top in ((100, 200, 50), (220, 400, 50),
                                            (100, 500, 200), (100, 500, 300), (100, 500, 400))],
        )
        with mock.patch.object(lightweight_ocr, "_engine", mock.Mock(return_value=result)):
            self.assertEqual(lightweight_ocr.extract_page_text("page.png"),
                             "资产负债表\n项目 期初 期末\n货币资金 10 20\n资产总计 30 40")

    def test_engine_is_reused_and_chinese_lines_are_preserved(self):
        engine = mock.Mock(return_value=SimpleNamespace(txts=("资产负债表", "流动资产", "存货", "100.00")))
        with mock.patch.object(lightweight_ocr, "_engine", None), mock.patch.object(
            lightweight_ocr, "_create_engine", return_value=engine,
        ) as create:
            for path in ("one.png", "two.png"):
                self.assertEqual(lightweight_ocr.extract_page_text(path), "资产负债表\n流动资产\n存货\n100.00")
            create.assert_called_once()
            self.assertEqual(engine.call_count, 2)

    def test_engine_failure_propagates_and_initialization_can_retry(self):
        with mock.patch.object(lightweight_ocr, "_engine", None), mock.patch.object(
            lightweight_ocr, "_create_engine", side_effect=[RuntimeError("missing model"),
                mock.Mock(return_value=SimpleNamespace(txts=None))],
        ):
            with self.assertRaisesRegex(RuntimeError, "missing model"):
                lightweight_ocr.extract_page_text("one.png")
            self.assertEqual(lightweight_ocr.extract_page_text("two.png"), "")

    def test_invalid_response_propagates(self):
        with mock.patch.object(lightweight_ocr, "_engine", mock.Mock(return_value=None)):
            with self.assertRaisesRegex(RuntimeError, "返回结构异常"):
                lightweight_ocr.extract_page_text("one.png")


class StrictOrientationTest(unittest.TestCase):
    def test_existing_classifier_corrects_all_four_angles(self):
        processor = BaseFinancialProcessor.__new__(BaseFinancialProcessor)
        processor.logger = mock.Mock()
        processor._orientation_timeout_seconds = 15
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "page.png")
            original = np.arange(6 * 9 * 3, dtype=np.uint8).reshape(6, 9, 3)
            rotations = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180,
                         270: cv2.ROTATE_90_COUNTERCLOCKWISE}
            for angle in (0, 90, 180, 270):
                with self.subTest(angle=angle):
                    cv2.imwrite(path, original if not angle else cv2.rotate(original, rotations[angle]))
                    with mock.patch("apps.fin_stmts_parse.src.base_financial_processor.predict_image_orientation",
                                    return_value={"angle": angle}):
                        corrected = processor.correct_image_orientation(path, strict=True)
                    np.testing.assert_array_equal(cv2.imread(corrected), original)
                    if corrected != path:
                        Path(corrected).unlink()

    def test_strict_mode_reports_error_and_legacy_mode_keeps_fallback(self):
        processor = BaseFinancialProcessor.__new__(BaseFinancialProcessor)
        processor.logger = mock.Mock()
        processor._orientation_timeout_seconds = 15
        with mock.patch("apps.fin_stmts_parse.src.base_financial_processor.cv2.imread", return_value=np.zeros((4, 4, 3))), \
             mock.patch("apps.fin_stmts_parse.src.base_financial_processor.predict_image_orientation",
                        side_effect=OrientationInferenceError("timeout")):
            with self.assertRaises(OrientationInferenceError):
                processor.correct_image_orientation("page.png", strict=True)
            self.assertEqual(processor.correct_image_orientation("page.png"), "page.png")
