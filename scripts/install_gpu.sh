#!/usr/bin/env bash
set -euo pipefail

python -m pip install --upgrade pip
python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
python -m pip install --upgrade transformers accelerate peft bitsandbytes 'qwen-vl-utils[decord]' Pillow safetensors
python scripts/check_gpu_env.py
