# DeepSeek-V4-Flash on 8x W7900D: Low-bit and KV Cache Round 2

Date: 2026-05-09

Hardware and runtime:

- GPU: 8 x AMD Radeon PRO W7900D, 48 GB each
- Runtime: bati.cpp / llama.cpp ROCm build
- Stable serving endpoint: `http://127.0.0.1:8080`
- Current best performance model: `/data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-MXFP4_MOE-requant-from-Q8_0.gguf`
- Conservative quality baseline: `/data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-Q8_0-bati-local.gguf`

## Executive Summary

本轮继续沿着低精度和显存优化方向实验。结论发生了变化：当前性能最优的是 MXFP4_MOE GGUF + bati.cpp ROCm + layer split。Q8_0 仍然是最保守的质量基线，但不再是性能最优解。

| Direction | Result | Decision |
| --- | --- | --- |
| MXFP4_MOE requantized from Q8_0 | 成功量化、CLI 成功、llama-bench 成功、vLLM benchmark 成功。它只把 MoE expert 张量压到 MXFP4，其余大量张量仍保持 Q8_0。 | 当前性能最优。建议作为博客里的推荐性能路线，同时标注需要补充质量评估。 |
| Q2_K from ModelScope official weights | 成功本地转换、CLI 成功、llama-bench 成功、vLLM benchmark 成功。显存和磁盘占用显著下降，但吞吐没有提升。 | 只作为省显存/省磁盘方案，不作为性能优化方案。 |
| Q3_K_M requantized from Q8_0 | 成功量化、CLI 成功、llama-bench 成功、vLLM benchmark 成功。性能低于 Q8_0。 | 不作为生产默认；可作为内存压力更高时的候选。 |
| Q4_K_M requantized from Q8_0 | 量化成功，短 CLI 成功，但更长 benchmark 触发 DeepSeek4 assert。 | 不发布为稳定方案。等待 native Q4_K_M GGUF 完整下载后再测。 |
| Native Q4_K_M GGUF | ModelScope 没有对应社区 GGUF 镜像，HF 下载中。 | 下载继续后台跑，完成后再做正式 native Q4 测试。 |
| KV cache quantization | Q8_0 baseline 的 f16 KV 可跑；q8_0/q4_0 KV 在 ROCm concat kernel 报 unsupported concat type。 | 当前 bati.cpp/ROCm DeepSeek4 路径不能用 KV cache quantization。 |

## ModelSource Decision

优先使用 ModelScope 的要求是合理的。本机已有官方权重：

```text
/data/models/deepseek-ai/DeepSeek-V4-Flash
```

Q2_K 是从这个 ModelScope 官方 safetensors 本地转换出来的：

```bash
export LLAMA_CPP_LIBGGML=/root/bati.cpp/build-hip/bin/libggml.so
export LD_LIBRARY_PATH=/root/bati.cpp/build-hip/bin:${LD_LIBRARY_PATH:-}

/data/bati-convert-venv/bin/python /root/bati.cpp/convert_hf_to_gguf.py \
  /data/models/deepseek-ai/DeepSeek-V4-Flash \
  --outfile /data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-Q2_K-modelscope-local.gguf \
  --outtype q2_k \
  --deepseek4-expert-workers 16
```

但当前转换器不能直接从 safetensors 输出 Q3_K_M / Q4_K_M。它暴露的 `--outtype` 是：

```text
f32, f16, bf16, q8_0, iq2_xxs, iq2_xs, q2_k, tq1_0, tq2_0, auto
```

所以 Q3_K_M / Q4_K_M / MXFP4_MOE 本地实验采用 `llama-quantize` 从 Q8_0 GGUF 重量化：

```bash
/root/bati.cpp/build-hip/bin/llama-quantize --allow-requantize \
  /data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-Q8_0-bati-local.gguf \
  /data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-Q3_K_M-requant-from-Q8_0.gguf \
  Q3_K_M 64
```

Q3_K_M 结果：

```text
model size  = 288244.36 MiB (8.50 BPW)
quant size  = 129131.14 MiB (3.81 BPW)
quantize time = 543091.34 ms
artifact = /data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-Q3_K_M-requant-from-Q8_0.gguf
```

MXFP4_MOE 结果：

```text
model size  = 288244.36 MiB (8.50 BPW)
quant size  = 147892.36 MiB (4.36 BPW)
quantize time = 459303.42 ms
artifact = /data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-MXFP4_MOE-requant-from-Q8_0.gguf
```

注意：`MXFP4_MOE` 不是全模型 FP4。日志显示它主要转换 `ffn_*_exps.weight` 这类 MoE expert 张量到 `mxfp4`，attention、embedding、indexer 等大量张量仍保持 Q8_0。这也是它比 Q3_K_M 更大、但速度和稳定性更好的原因。

## llama-bench Results

Common settings:

```text
split_mode = layer
n_gpu_layers = 99
flash_attn = true
batch = 512
ubatch = 256
cache_k/cache_v = f16
no_op_offload = 1
```

| Model | Model size | Prefill | Decode | Notes |
| --- | ---: | ---: | ---: | --- |
| MXFP4_MOE requant | 155.08 GB | 118.04 tok/s at p512 | 9.52 tok/s at n64 | Current performance winner |
| Q8_0 local | 302.25 GB | 115.66 tok/s at p512 | 9.22 tok/s at n64 | Conservative quality baseline |
| Q2_K ModelScope local | 105.52 GB | 102.69 tok/s at p512 | 9.12 tok/s at n64 | Saves memory, no speed win |
| Q3_K_M requant | 135.40 GB | 95.18 tok/s at p512 | 8.98 tok/s at n64 | Saves memory, slower than Q8 |
| Q4_K_M requant | 171.91 GB | 88.75 tok/s at p64 only | not stable | Longer benchmark hit DeepSeek4 assert |

MXFP4_MOE CLI smoke test succeeded:

```text
prompt eval: 8.28 tok/s
decode eval: 4.13 tok/s
```

Q3_K_M CLI smoke test also succeeded:

```text
prompt eval: 8.65 tok/s
decode eval: 4.10 tok/s
```

Q2_K CLI smoke test succeeded but was not faster:

```text
prompt eval: 6.30 tok/s
decode eval: 3.35 tok/s
```

The practical read is: naive lower-bit model weights reduce memory pressure but do not automatically improve throughput. Q2_K and Q3_K_M are smaller than MXFP4_MOE but slower. The useful compromise is MXFP4_MOE, because it compresses the MoE expert tensors while keeping the rest of the model in Q8_0.

## vLLM Benchmark Client Results

These numbers use `vllm bench serve` only as the benchmark client. The serving backend is still bati.cpp / llama.cpp through the OpenAI-compatible `/v1/completions` endpoint.

Short request case:

```text
random input = 128 tokens
random output = 64 tokens
num_prompts = 8
max_concurrency = 1
```

| Model | Successful | Output tok/s | Total tok/s | Mean TTFT | Mean TPOT | Mean E2E |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| MXFP4_MOE requant | 8/8 | 6.89 | 20.66 | 1771 ms | 119.4 ms | 9294 ms |
| Q8_0 local | 8/8 | 6.82 | 20.46 | 1671 ms | 122.4 ms | 9383 ms |
| Q2_K ModelScope local | 8/8 | 6.67 | 20.01 | 2064 ms | 119.6 ms | 9596 ms |
| Q3_K_M requant | 8/8 | 6.47 | 19.43 | 2036 ms | 124.7 ms | 9877 ms |

Longer prefill case:

```text
random input = 1024 tokens
random output = 128 tokens
num_prompts = 4
max_concurrency = 1
```

| Model | Successful | Output tok/s | Total tok/s | Mean TTFT | Mean TPOT | Mean E2E |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| MXFP4_MOE requant | 4/4 | 4.54 | 40.90 | 12650 ms | 122.2 ms | 28166 ms |
| Q8_0 local | 4/4 | 4.42 | 39.77 | 12817 ms | 127.2 ms | 28968 ms |
| Q3_K_M requant | 4/4 | 4.09 | 36.77 | 15123 ms | 127.6 ms | 31331 ms |

Concurrency case:

```text
random input = 128 tokens
random output = 64 tokens
num_prompts = 16
max_concurrency = 4
```

| Model | Successful | Output tok/s | Total tok/s | Mean TTFT | Mean TPOT | Mean E2E |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| MXFP4_MOE requant | 16/16 | 6.97 | 20.91 | 25790 ms | 119.1 ms | 33290 ms |
| Q8_0 local | 16/16 | 6.66 | 19.98 | 26976 ms | 125.2 ms | 34862 ms |

Long prompt case:

```text
random input = 4096 tokens
random output = 64 tokens
num_prompts = 2
max_concurrency = 1
```

| Model | Successful | Output tok/s | Total tok/s | Mean TTFT | Mean TPOT | Mean E2E |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| MXFP4_MOE requant | 2/2 | 1.19 | 77.64 | 45339 ms | 130.8 ms | 53579 ms |
| Q8_0 local | 2/2 | 1.17 | 75.85 | 46140 ms | 138.2 ms | 54847 ms |

This confirms the llama-bench result: MXFP4_MOE is the best measured performance route so far. Q3_K_M and Q2_K are useful negative controls: smaller files do not necessarily mean better tok/s on this ROCm stack.

## KV Cache Quantization

The f16 KV baseline is valid:

| KV type | Prefill p512 | Prefill p1024 | Result |
| --- | ---: | ---: | --- |
| f16/f16 | 113.75 tok/s | 102.39 tok/s | Works |

But quantized KV cache fails in the ROCm concat kernel:

```text
/root/bati.cpp/ggml/src/ggml-cuda/concat.cu:183: unsupported concat type: q8_0
/root/bati.cpp/ggml/src/ggml-cuda/concat.cu:183: unsupported concat type: q4_0
```

So `-ctk q8_0 -ctv q8_0` and `-ctk q4_0 -ctv q4_0` are not usable today for this DeepSeek4 ROCm path.

## Native Q4_K_M Status

Native community Q4_K_M GGUF is still worth testing because it may have a better tensor-type layout than local Q8_0 requantization. However, the community GGUF repos tested were not available on ModelScope, so this path had to fall back to Hugging Face.

Current download:

```text
dir = /data/models/deepseek-v4-native-gguf/batiai-q4km
pid = 3791585
speed = about 6-7 MiB/s
progress = roughly 20%, 19%, 19%, 46% across the four shards
```

The expected model files are:

```text
deepseek-ai-DeepSeek-V4-Flash-Q4_K_M-00001-of-00004.gguf
deepseek-ai-DeepSeek-V4-Flash-Q4_K_M-00002-of-00004.gguf
deepseek-ai-DeepSeek-V4-Flash-Q4_K_M-00003-of-00004.gguf
deepseek-ai-DeepSeek-V4-Flash-Q4_K_M-00004-of-00004.gguf
```

When the download finishes, the next test should load the first shard and run the same smoke and benchmark sequence:

```bash
MODEL=/data/models/deepseek-v4-native-gguf/batiai-q4km/deepseek-ai-DeepSeek-V4-Flash-Q4_K_M-00001-of-00004.gguf \
CTX_SIZE=4096 \
N_PREDICT=16 \
/root/deepseek-v4-w7900d/scripts/run_cli.sh

MODEL=/data/models/deepseek-v4-native-gguf/batiai-q4km/deepseek-ai-DeepSeek-V4-Flash-Q4_K_M-00001-of-00004.gguf \
LABEL=native-q4km \
/root/deepseek-v4-w7900d/scripts/bench_gguf_standard.sh
```

## Reproducibility Artifacts

Standard llama-bench wrapper:

```text
/root/deepseek-v4-w7900d/scripts/bench_gguf_standard.sh
```

Key result files:

```text
/root/deepseek-v4-w7900d/results/bench/llama-bench-layer-fa-b512-ub256-r2.jsonl
/root/deepseek-v4-w7900d/results/bench/llama-bench-mxfp4-moe-requant-sm-layer-fa1-p512-n64-b512-ub256-r2.jsonl
/root/deepseek-v4-w7900d/results/bench/llama-bench-q2k-modelscope-layer-fa-b512-ub256-r2.jsonl
/root/deepseek-v4-w7900d/results/bench/llama-bench-q3km-requant-sm-layer-fa1-p512-n64-b512-ub256-r2.jsonl
/root/deepseek-v4-w7900d/results/vllm-bench/random-i128-o64-n8-c1.json
/root/deepseek-v4-w7900d/results/vllm-bench-mxfp4-moe/random-i128-o64-n8-c1.json
/root/deepseek-v4-w7900d/results/vllm-bench-mxfp4-moe/random-i1024-o128-n4-c1.json
/root/deepseek-v4-w7900d/results/vllm-bench-mxfp4-moe/random-i128-o64-n16-c4.json
/root/deepseek-v4-w7900d/results/vllm-bench-mxfp4-moe/random-i4096-o64-n2-c1.json
/root/deepseek-v4-w7900d/results/vllm-bench-q2k/random-i128-o64-n8-c1.json
/root/deepseek-v4-w7900d/results/vllm-bench-q3km/random-i128-o64-n8-c1.json
/root/deepseek-v4-w7900d/results/vllm-bench-q3km/random-i1024-o128-n4-c1.json
/root/deepseek-v4-w7900d/results/kv-cache-bench/q8-f16.jsonl
/root/deepseek-v4-w7900d/results/kv-cache-bench/q8-q8_0.err.log
/root/deepseek-v4-w7900d/results/kv-cache-bench/q8-q4_0.err.log
```

## Current Recommendation

Use MXFP4_MOE for the current performance-oriented serving path:

```bash
MODEL=/data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-MXFP4_MOE-requant-from-Q8_0.gguf \
CTX_SIZE=16384 \
PARALLEL=1 \
BATCH_SIZE=512 \
UBATCH_SIZE=256 \
/root/deepseek-v4-w7900d/scripts/run_server.sh
```

Keep Q8_0 as the conservative quality baseline until a task-level quality evaluation is done.

For the public blog, present Q2/Q3 as negative but useful experiments and MXFP4_MOE as the practical optimization:

- they prove that lower-bit GGUF can run on the 8 x W7900D stack
- Q2/Q3 reduce model memory footprint substantially but do not improve prefill, decode, TTFT, or TPOT
- MXFP4_MOE cuts the Q8 file from about 302 GB model-size accounting to about 155 GB and improves the measured serving benchmarks
- KV cache quantization is blocked by ROCm concat type support
- native Q4_K_M is still worth re-testing after the slow community GGUF download finishes
