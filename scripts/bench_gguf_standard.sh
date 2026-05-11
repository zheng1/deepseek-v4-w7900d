#!/usr/bin/env bash
set -euo pipefail

MODEL="${MODEL:-/data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-Q8_0-bati-local.gguf}"
LABEL="${LABEL:-$(basename "$MODEL" .gguf)}"
OUT_DIR="${OUT_DIR:-/root/deepseek-v4-w7900d/results/bench}"
PROMPTS="${PROMPTS:-512}"
GENS="${GENS:-64}"
REPEATS="${REPEATS:-2}"
BATCH_SIZE="${BATCH_SIZE:-512}"
UBATCH_SIZE="${UBATCH_SIZE:-256}"
N_THREADS="${N_THREADS:-64}"
N_GPU_LAYERS="${N_GPU_LAYERS:-99}"
SPLIT_MODE="${SPLIT_MODE:-layer}"
FLASH_ATTN="${FLASH_ATTN:-1}"
TYPE_K="${TYPE_K:-f16}"
TYPE_V="${TYPE_V:-f16}"

mkdir -p "$OUT_DIR"

export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0,1,2,3,4,5,6,7}"
export ROCR_VISIBLE_DEVICES="${ROCR_VISIBLE_DEVICES:-0,1,2,3,4,5,6,7}"

out="$OUT_DIR/llama-bench-${LABEL}-sm-${SPLIT_MODE}-fa${FLASH_ATTN}-p${PROMPTS}-n${GENS}-b${BATCH_SIZE}-ub${UBATCH_SIZE}-r${REPEATS}.jsonl"
err="${out%.jsonl}.err.log"

/root/bati.cpp/build-hip/bin/llama-bench \
  -m "$MODEL" \
  -sm "$SPLIT_MODE" \
  -ngl "$N_GPU_LAYERS" \
  -fa "$FLASH_ATTN" \
  -p "$PROMPTS" \
  -n "$GENS" \
  -b "$BATCH_SIZE" \
  -ub "$UBATCH_SIZE" \
  -t "$N_THREADS" \
  -r "$REPEATS" \
  -ctk "$TYPE_K" \
  -ctv "$TYPE_V" \
  --no-op-offload 1 \
  -o jsonl \
  2> "$err" | tee "$out"
