"""本地中文文字识别，用于 PDF 定位；不还原表格、不调用远程接口。"""

from pathlib import Path
from threading import Lock


_engine = None
_engine_lock = Lock()


def _create_engine():
    import rapidocr

    # 固定使用 rapidocr 3.8.4 wheel 自带的中文 PP-OCRv4 mobile 模型。
    # 显式指定本地路径，缺失时直接报错，禁止解析请求中隐式下载。
    model_dir = Path(rapidocr.__file__).resolve().parent / "models"
    models = {
        "Det.model_path": "ch_PP-OCRv4_det_mobile.onnx",
        "Rec.model_path": "ch_PP-OCRv4_rec_mobile.onnx",
        "Cls.model_path": "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
    }
    params = {}
    for key, name in models.items():
        path = model_dir / name
        if not path.is_file():
            raise RuntimeError(f"本地 OCR 模型缺失: {path}；请安装 rapidocr==3.8.4")
        params[key] = str(path)
    params.update({
        # 整页方向由项目已有分类器纠正，避免再做文本行方向分类。
        "Global.use_cls": False,
        "Global.log_level": "warning",
        "EngineConfig.onnxruntime.intra_op_num_threads": 2,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
    })
    return rapidocr.RapidOCR(params=params)


def extract_page_text(image_path: str) -> str:
    """进程内复用模型，按坐标恢复页首标题，其余文字框仍按换行分隔。"""
    from .pdf_page_discovery import restore_statement_title_lines

    global _engine
    # RapidOCR 调用会更新内部状态，串行保护共享实例，避免并发污染。
    # ONNX 内部使用有限线程；方向纠正仍可与 OCR 并行。
    with _engine_lock:
        if _engine is None:
            _engine = _create_engine()
        result = _engine(image_path)
        if result is None or not hasattr(result, "txts"):
            raise RuntimeError("RapidOCR 返回结构异常")
        if result.txts is None:
            return ""
        if any(not isinstance(text, str) for text in result.txts):
            raise RuntimeError("RapidOCR 返回无效文字")
        return restore_statement_title_lines(result.txts, getattr(result, "boxes", None))


if __name__ == "__main__":
    # Docker 构建时离线校验依赖和三个模型能否加载。
    _create_engine()
