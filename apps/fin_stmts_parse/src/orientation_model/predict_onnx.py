"""使用 ONNX Runtime 进行推理。

用法:
    python predict_onnx.py --image test.jpg
    python predict_onnx.py --folder ./images/
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image

from utils import letterbox

LABEL_TO_ANGLE = {0: 0, 1: 90, 2: 180, 3: 270}
ONNX_PATH = Path(__file__).parent / "best_model.onnx"
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}

MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(1, 1, 3)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(1, 1, 3)


def load_session(onnx_path: str = None):
    path = onnx_path or str(ONNX_PATH)
    providers = ort.get_available_providers()
    session = ort.InferenceSession(path, providers=providers)
    return session


def preprocess(image_path: str) -> np.ndarray:
    img = Image.open(image_path).convert("RGB")
    img = letterbox(img, 224)
    arr = np.array(img, dtype=np.float32) / 255.0
    arr = (arr - MEAN) / STD
    arr = arr.transpose(2, 0, 1)  # HWC -> CHW
    return arr[np.newaxis, ...]     # 添加 batch 维度


def softmax(x):
    e = np.exp(x - np.max(x, axis=-1, keepdims=True))
    return e / e.sum(axis=-1, keepdims=True)


def predict_single(session, image_path: str):
    inp = preprocess(image_path)

    t0 = time.perf_counter()
    logits = session.run(None, {"image": inp})[0]
    elapsed_ms = (time.perf_counter() - t0) * 1000

    probs = softmax(logits)
    pred = int(np.argmax(probs, axis=1)[0])
    conf = float(probs[0, pred])

    return {
        "filename": Path(image_path).name,
        "angle": LABEL_TO_ANGLE[pred],
        "confidence": round(conf, 4),
        "backend": "onnxruntime",
        "device_used": ",".join(session.get_providers()),
        "processing_time_ms": round(elapsed_ms, 2),
    }


def main():
    parser = argparse.ArgumentParser(description="ONNX Runtime 方向分类推理")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--image", type=str, help="单张图片路径")
    group.add_argument("--folder", type=str, help="图片文件夹路径")
    parser.add_argument("--model", type=str, default=None, help="ONNX 模型路径")
    args = parser.parse_args()

    session = load_session(args.model)

    if args.image:
        result = predict_single(session, args.image)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        folder = Path(args.folder)
        images = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMG_EXTS)
        if not images:
            print(f"[Error] {folder} 下未找到图片")
            return
        results = [predict_single(session, str(p)) for p in images]
        print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

