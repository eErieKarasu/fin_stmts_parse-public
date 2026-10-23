"""将 best_model.pth 导出为 ONNX 格式。

用法:
    python export_onnx.py                        # 默认导出到 best_model.onnx
    python export_onnx.py -o model_fp16.onnx      # 指定输出路径
"""

import argparse
from pathlib import Path

import torch

from model import build_model

MODEL_PATH = Path(__file__).parent / "best_model.pth"


def export(output_path: str):
    model = build_model(num_classes=4, pretrained=False)
    model.load_state_dict(
        torch.load(MODEL_PATH, map_location="cpu", weights_only=True)
    )
    model.eval()

    dummy_input = torch.randn(1, 3, 224, 224)

    torch.onnx.export(
        model,
        dummy_input,
        output_path,
        dynamo=False,
        opset_version=17,
        input_names=["image"],
        output_names=["logits"],
        dynamic_axes={
            "image": {0: "batch_size"},
            "logits": {0: "batch_size"},
        },
    )
    print(f"ONNX 模型已导出: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="导出 ONNX 模型")
    parser.add_argument(
        "-o", "--output",
        default=str(Path(__file__).parent / "best_model.onnx"),
        help="输出 ONNX 文件路径 (默认 best_model.onnx)",
    )
    args = parser.parse_args()
    export(args.output)