#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Orientation inference adapter.

This module isolates the external orientation classifier invocation so the
financial parsing pipeline only depends on a stable Python API.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict


ALLOWED_ANGLES = {0, 90, 180, 270}
DEFAULT_TIMEOUT_SECONDS = 15
SCRIPT_PATH = Path(__file__).resolve().parent / "orientation_model" / "predict_onnx.py"


class OrientationInferenceError(RuntimeError):
    """Raised when orientation inference fails or returns invalid data."""


def _extract_json_payload(stdout: str) -> Dict[str, Any]:
    text = stdout.strip()
    if not text:
        raise OrientationInferenceError("Orientation script returned empty stdout.")

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or start >= end:
            raise OrientationInferenceError(
                f"Orientation script stdout is not valid JSON: {text}"
            ) from None
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise OrientationInferenceError(
                f"Orientation script stdout contains malformed JSON: {text}"
            ) from exc

    if not isinstance(payload, dict):
        raise OrientationInferenceError(
            f"Orientation script returned non-object JSON: {payload}"
        )
    return payload


def predict_image_orientation(
    image_path: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """
    Run the external orientation classifier and return normalized prediction data.
    """
    if not SCRIPT_PATH.exists():
        raise OrientationInferenceError(
            f"Orientation script not found: {SCRIPT_PATH}"
        )

    cmd = [sys.executable, str(SCRIPT_PATH), "--image", image_path]
    env = os.environ.copy()

    # The grpc/mcp runners install app-specific dependencies into custom target
    # directories and inject them into the current process via sys.path.
    # When orientation inference launches a fresh Python subprocess, those
    # in-memory sys.path edits are lost unless we forward them through PYTHONPATH.
    python_path_entries = []
    existing_pythonpath = env.get("PYTHONPATH", "")
    if existing_pythonpath:
        python_path_entries.extend(
            [entry for entry in existing_pythonpath.split(os.pathsep) if entry]
        )
    python_path_entries.extend([entry for entry in sys.path if entry])

    deduped_pythonpath = []
    seen = set()
    for entry in python_path_entries:
        normalized = str(Path(entry).resolve()) if entry else ""
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped_pythonpath.append(normalized)

    if deduped_pythonpath:
        env["PYTHONPATH"] = os.pathsep.join(deduped_pythonpath)

    try:
        result = subprocess.run(
            cmd,
            cwd=str(SCRIPT_PATH.parent),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise OrientationInferenceError(
            f"Orientation inference timed out after {timeout_seconds}s for {image_path}"
        ) from exc
    except OSError as exc:
        raise OrientationInferenceError(
            f"Failed to start orientation script: {exc}"
        ) from exc

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        details = stderr or stdout or f"exit_code={result.returncode}"
        raise OrientationInferenceError(
            f"Orientation script failed for {image_path}: {details}"
        )

    payload = _extract_json_payload(result.stdout)
    angle = payload.get("angle")
    if angle not in ALLOWED_ANGLES:
        raise OrientationInferenceError(
            f"Invalid orientation angle returned: {angle}"
        )

    return {
        "angle": angle,
        "confidence": payload.get("confidence"),
        "device_used": payload.get("device_used") or payload.get("backend"),
        "processing_time_ms": payload.get("processing_time_ms"),
    }
