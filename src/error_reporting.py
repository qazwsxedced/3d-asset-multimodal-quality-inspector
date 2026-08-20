"""Consistent, actionable error messages for inspection jobs."""

from __future__ import annotations

import json
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def format_failure_message(error: BaseException, log_path: Path | None = None) -> str:
    """Turn an internal exception into a concise bilingual operator message."""
    detail = str(error).strip() or type(error).__name__
    lowered = detail.lower()
    if "timed out" in lowered or "timeout" in lowered:
        headline = "Blender 检测超时 / Blender inspection timed out"
        action = "请降低预览分辨率或诊断三角形上限，并查看日志。 / Reduce preview resolution or the diagnostic triangle limit and review the log."
    elif "cancelled" in lowered or "canceled" in lowered:
        headline = "检测已取消 / Inspection cancelled"
        action = "可以重新准备资产后再次运行。 / Prepare the asset again and retry."
    elif "required inspection outputs are incomplete" in lowered:
        headline = "检测产物不完整 / Inspection outputs are incomplete"
        action = "请检查日志中列出的具体文件；不要将本次结果视为可发布。 / Check the listed files in the log; do not treat this result as publishable."
    elif "requires torch" in lowered or "qwen-vl-utils" in lowered:
        headline = "VLM 依赖不可用 / VLM dependencies are unavailable"
        action = "请安装 VLM 依赖，或切换到 Rule baseline。 / Install the VLM dependencies or switch to Rule baseline."
    elif "blender job failed" in lowered:
        headline = "Blender 检测失败 / Blender inspection failed"
        action = "请查看 Blender 日志尾部和状态文件。 / Review the tail of the Blender log and the job status file."
    else:
        headline = "检测失败 / Inspection failed"
        action = "请查看错误详情和日志后重试。 / Review the error details and log, then retry."
    log_line = f" 日志 / Log: {log_path}" if log_path else ""
    return f"{headline}。{action} 详情 / Details: {detail}.{log_line}"


def write_failure_log(path: Path, operation: str, error: BaseException) -> None:
    """Persist structured failure data without exposing a Python traceback in the UI."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "operation": operation,
        "error_type": type(error).__name__,
        "message": str(error),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "traceback": traceback.format_exc(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
