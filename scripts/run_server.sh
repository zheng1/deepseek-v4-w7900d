#!/usr/bin/env bash
set -euo pipefail

MODEL="${MODEL:-/data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-Q8_0-bati-local.gguf}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8080}"
CTX_SIZE="${CTX_SIZE:-16384}"
PARALLEL="${PARALLEL:-1}"
BATCH_SIZE="${BATCH_SIZE:-512}"
UBATCH_SIZE="${UBATCH_SIZE:-256}"
SERVER_EXTRA_ARGS="${SERVER_EXTRA_ARGS:-}"

export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0,1,2,3,4,5,6,7}"
export ROCR_VISIBLE_DEVICES="${ROCR_VISIBLE_DEVICES:-0,1,2,3,4,5,6,7}"
export GGML_HIP_NO_VMM="${GGML_HIP_NO_VMM:-1}"

SERVER_ARGS=(
  /root/bati.cpp/build-hip/bin/llama-server
  -m "$MODEL" \
  -sm layer \
  -ngl 99 \
  -c "$CTX_SIZE" \
  -b "$BATCH_SIZE" \
  -ub "$UBATCH_SIZE" \
  -fa on \
  -fit off \
  --no-op-offload \
  --no-warmup \
  -np "$PARALLEL" \
  --host "$HOST" \
  --port "$PORT"
)

if [[ -n "$SERVER_EXTRA_ARGS" ]]; then
  read -r -a EXTRA_ARGS_ARRAY <<< "$SERVER_EXTRA_ARGS"
  SERVER_ARGS+=("${EXTRA_ARGS_ARRAY[@]}")
fi

exec "${SERVER_ARGS[@]}"
