"""Report the runtime required for Qwen2.5-VL inference and LoRA."""

from __future__ import annotations

import importlib.util
import json
import platform
import sys


def version(name: str):
    try:
        module = __import__(name)
        return getattr(module, "__version__", "installed")
    except Exception as exc:
        return f"missing: {type(exc).__name__}"


def main() -> None:
    packages = ["torch", "transformers", "accelerate", "peft", "bitsandbytes", "qwen_vl_utils", "PIL"]
    report = {"python": sys.version.split()[0], "platform": platform.platform(), "packages": {p: version(p) for p in packages}}
    try:
        import torch
        report["cuda"] = {"available": torch.cuda.is_available(), "version": torch.version.cuda, "device_count": torch.cuda.device_count(), "devices": [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]}
        if torch.cuda.is_available():
            report["cuda"]["memory_gb"] = [round(torch.cuda.get_device_properties(i).total_memory / 2**30, 2) for i in range(torch.cuda.device_count())]
    except Exception as exc:
        report["cuda"] = {"error": str(exc)}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    required = ["torch", "transformers", "accelerate", "peft", "qwen_vl_utils"]
    missing = [name for name in required if importlib.util.find_spec(name) is None]
    if missing:
        print("Missing packages:", ", ".join(missing))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
