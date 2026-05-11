#!/usr/bin/env bash
set -euo pipefail

IMAGE="${IMAGE:-docker.m.daocloud.io/vllm/vllm-openai-rocm:v0.20.1}"
BASE_URL="${BASE_URL:-http://127.0.0.1:8080}"
MODEL="${MODEL:-DeepSeek-V4-Flash-Q8_0-bati-local.gguf}"
TOKENIZER="${TOKENIZER:-/data/models/deepseek-ai/DeepSeek-V4-Flash}"
RESULT_DIR="${RESULT_DIR:-/root/deepseek-v4-w7900d/results/vllm-bench}"

mkdir -p "$RESULT_DIR"

run_case() {
  local input_len="$1"
  local output_len="$2"
  local num_prompts="$3"
  local concurrency="$4"
  local name="random-i${input_len}-o${output_len}-n${num_prompts}-c${concurrency}"

  docker run --rm --network host \
    -v /data/models:/data/models:ro \
    -v "$RESULT_DIR":/results \
    --entrypoint vllm \
    "$IMAGE" \
    bench serve \
    --backend openai \
    --base-url "$BASE_URL" \
    --endpoint /v1/completions \
    --model "$MODEL" \
    --served-model-name "$MODEL" \
    --tokenizer "$TOKENIZER" \
    --trust-remote-code \
    --dataset-name random \
    --random-input-len "$input_len" \
    --random-output-len "$output_len" \
    --random-range-ratio 0 \
    --num-prompts "$num_prompts" \
    --request-rate inf \
    --max-concurrency "$concurrency" \
    --temperature 0 \
    --ignore-eos \
    --disable-tqdm \
    --percentile-metrics ttft,tpot,itl,e2el \
    --metric-percentiles 50,90,95,99 \
    --metadata \
      backend_server=bati.cpp \
      model=$MODEL \
      split_mode=layer \
      server_np=1 \
      ctx=16384 \
      gpus=8xW7900D \
    --save-result \
    --result-dir /results \
    --result-filename "${name}.json" \
    2>&1 | tee "$RESULT_DIR/${name}.log"
}

run_case 128 64 8 1
run_case 128 64 16 4
run_case 1024 128 4 1
run_case 1024 128 8 4
run_case 4096 64 2 1
