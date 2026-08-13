param(
  [string]$TorchIndex = "https://download.pytorch.org/whl/cu124",
  [switch]$UseLatestTransformers
)

$ErrorActionPreference = "Stop"
python -m pip install --upgrade pip
python -m pip install torch torchvision --index-url $TorchIndex
if ($UseLatestTransformers) {
  python -m pip install --upgrade git+https://github.com/huggingface/transformers.git
} else {
  python -m pip install --upgrade transformers
}
python -m pip install --upgrade accelerate peft bitsandbytes "qwen-vl-utils[decord]" Pillow safetensors
python scripts/check_gpu_env.py
