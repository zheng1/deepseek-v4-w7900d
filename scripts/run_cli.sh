#!/usr/bin/env bash
set -euo pipefail

MODEL="${MODEL:-/data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-Q8_0-bati-local.gguf}"
PROMPT_FILE="${PROMPT_FILE:-/root/deepseek-v4-w7900d/results/prompt-chat.txt}"
N_PREDICT="${N_PREDICT:-128}"
CTX_SIZE="${CTX_SIZE:-4096}"
BATCH_SIZE="${BATCH_SIZE:-512}"
UBATCH_SIZE="${UBATCH_SIZE:-256}"

export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0,1,2,3,4,5,6,7}"
export ROCR_VISIBLE_DEVICES="${ROCR_VISIBLE_DEVICES:-0,1,2,3,4,5,6,7}"

/root/bati.cpp/build-hip/bin/llama-completion \
  -m "$MODEL" \
  -f "$PROMPT_FILE" \
  -sm layer \
  -ngl 99 \
  -c "$CTX_SIZE" \
  -b "$BATCH_SIZE" \
  -ub "$UBATCH_SIZE" \
  -n "$N_PREDICT" \
  -fa on \
  -fit off \
  --no-op-offload \
  --no-warmup \
  -no-cnv \
  --no-display-prompt \
  --simple-io \
  --temp 0
