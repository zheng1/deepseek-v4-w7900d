#!/usr/bin/env bash
set -euo pipefail

export MODEL="${MODEL:-/data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-MXFP4_MOE-requant-from-Q8_0.gguf}"
export CTX_SIZE="${CTX_SIZE:-16384}"
export PARALLEL="${PARALLEL:-4}"
export BATCH_SIZE="${BATCH_SIZE:-512}"
export UBATCH_SIZE="${UBATCH_SIZE:-256}"
export SERVER_EXTRA_ARGS="${SERVER_EXTRA_ARGS:---cache-ram 0 --no-cache-idle-slots --no-cache-prompt --slot-prompt-similarity 0}"

exec /root/deepseek-v4-w7900d/scripts/run_server.sh
