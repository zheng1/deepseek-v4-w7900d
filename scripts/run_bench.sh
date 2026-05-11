#!/usr/bin/env bash
set -euo pipefail

MODEL="${MODEL:-/data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-Q8_0-bati-local.gguf}"
OUT_DIR="${OUT_DIR:-/root/deepseek-v4-w7900d/results}"
mkdir -p "$OUT_DIR"

export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0,1,2,3,4,5,6,7}"
export ROCR_VISIBLE_DEVICES="${ROCR_VISIBLE_DEVICES:-0,1,2,3,4,5,6,7}"

/root/bati.cpp/build-hip/bin/llama-bench \
  -m "$MODEL" \
  -sm layer \
  -ngl 99 \
  -fa 1 \
  -p 512,2048,4096 \
  -n 128 \
  -b 2048 \
  -ub 512 \
  -r 3 \
  -o jsonl | tee "$OUT_DIR/llama-bench-layer-fa.jsonl"
