# DeepSeek-V4-Flash on 8x W7900D: vLLM Benchmark Client Results

Date: 2026-05-10

This benchmark uses vLLM only as the benchmark client. The inference backend is still bati.cpp / llama.cpp ROCm server.

## Serving Backend

```text
Backend: bati.cpp / llama.cpp ROCm
Original baseline model: DeepSeek-V4-Flash-Q8_0-bati-local.gguf
Current best measured model: DeepSeek-V4-Flash-MXFP4_MOE-requant-from-Q8_0.gguf
GPUs: 8 x AMD Radeon PRO W7900D, 48 GB each
Split mode: layer
Original serving baseline slots: -np 1
Current multi-slot test server: -np 4
Context: 16384
Batch: 512
UBatch: 256
Flash attention: on
Endpoint: /v1/completions
```

Current performance server command:

```bash
/root/deepseek-v4-w7900d/scripts/run_server_mxfp4_moe.sh
```

## Benchmark Tool

Benchmark script:

```text
/root/deepseek-v4-w7900d/scripts/run_vllm_bench_openai.sh
```

vLLM command shape:

```bash
vllm bench serve \
  --backend openai \
  --base-url http://127.0.0.1:8080 \
  --endpoint /v1/completions \
  --model DeepSeek-V4-Flash-Q8_0-bati-local.gguf \
  --served-model-name DeepSeek-V4-Flash-Q8_0-bati-local.gguf \
  --tokenizer /data/models/deepseek-ai/DeepSeek-V4-Flash \
  --trust-remote-code \
  --dataset-name random \
  --request-rate inf \
  --temperature 0 \
  --ignore-eos
```

Important note: `request-rate=inf` means the benchmark sends requests as fast as allowed by `max-concurrency`. Older concurrency tables were collected before the DeepSeek4 multi-slot fix and used `-np 1`, so they mainly measure queueing behavior. The later `1024 input / 1 output` prefill table was rerun after the fix with `-np 4`.

## Q8_0 Baseline Results

| Case | Requests | Failed | Duration | Input tokens | Output tokens | Req/s | Output tok/s | Total tok/s | Mean TTFT | P95 TTFT | Mean TPOT | P95 TPOT | Mean E2E | P95 E2E |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| random 128 in / 64 out / c1 | 8 | 0 | 75.1s | 1,024 | 512 | 0.107 | 6.82 | 20.46 | 1.67s | 1.86s | 122ms | 126ms | 9.38s | 9.54s |
| random 128 in / 64 out / c4 | 16 | 0 | 153.7s | 2,048 | 1,024 | 0.104 | 6.66 | 19.98 | 26.98s | 31.08s | 125ms | 127ms | 34.86s | 39.03s |
| random 1024 in / 128 out / c1 | 4 | 0 | 115.9s | 4,096 | 512 | 0.035 | 4.42 | 39.77 | 12.82s | 12.96s | 127ms | 128ms | 28.97s | 29.10s |
| random 1024 in / 128 out / c4 | 8 | 0 | 189.1s | 8,192 | 1,024 | 0.042 | 5.42 | 48.74 | 57.22s | 94.88s | 126ms | 127ms | 73.27s | 110.91s |
| random 4096 in / 64 out / c1 | 2 | 0 | 109.7s | 8,192 | 128 | 0.018 | 1.17 | 75.85 | 46.14s | 48.19s | 138ms | 139ms | 54.85s | 56.92s |

Raw outputs:

```text
/root/deepseek-v4-w7900d/results/vllm-bench/*.json
/root/deepseek-v4-w7900d/results/vllm-bench/*.log
```

## MXFP4_MOE Results

Model:

```text
/data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-MXFP4_MOE-requant-from-Q8_0.gguf
```

| Case | Requests | Failed | Output tok/s | Total tok/s | Mean TTFT | Mean TPOT | Mean E2E |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| random 128 in / 64 out / c1 | 8 | 0 | 6.89 | 20.66 | 1.77s | 119ms | 9.29s |
| random 128 in / 64 out / c4 | 16 | 0 | 6.97 | 20.91 | 25.79s | 119ms | 33.29s |
| random 1024 in / 128 out / c1 | 4 | 0 | 4.54 | 40.90 | 12.65s | 122ms | 28.17s |
| random 4096 in / 64 out / c1 | 2 | 0 | 1.19 | 77.64 | 45.34s | 131ms | 53.58s |

## MXFP4_MOE Prefill Stress Results

These runs use `random-input-len=1024` and `random-output-len=1`, so total token throughput is effectively the prefill throughput. The first pair was run on the 128K context server with `-np 1`, before the DeepSeek4 multi-slot fix.

| Case | Requests | Failed | Duration | Input tokens | Output tokens | Req/s | Total tok/s | Mean TTFT | P95 TTFT | Mean E2E | P95 E2E |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| random 1024 in / 1 out / c1 | 10 | 0 | 141.43s | 10,240 | 10 | 0.071 | 72.47 | 14.14s | 14.34s | 14.14s | 14.34s |
| random 1024 in / 1 out / c32 | 100 | 0 | 1340.89s | 102,400 | 100 | 0.075 | 76.44 | 361.47s | 429.20s | 361.47s | 429.20s |

Raw outputs:

```text
/root/deepseek-v4-w7900d/results/vllm-bench-mxfp4-moe-c131072-prefill-c1-10/random-i1024-o1-n10-c1.json
/root/deepseek-v4-w7900d/results/vllm-bench-mxfp4-moe-c131072-prefill-c32-100/random-i1024-o1-n100-c32.json
```

The c32 run is the better stress test for saturated prefill throughput. It confirms that the backend can sustain about 76 tok/s on this 1024/1 workload. It does not make latency look better: because this run used the old `-np 1` server, the extra concurrency mainly fills the queue. That is why total throughput only improves slightly over c1, while P95 TTFT rises to about 429s.

After fixing DeepSeek4 multi-slot startup, I reran the same prefill-shaped workload on `-np 4 -c 16384 -b 512 -ub 256`. For this benchmark I also disabled prompt-cache paths because the random dataset has no useful prefix reuse:

```bash
--cache-ram 0 \
--no-cache-idle-slots \
--no-cache-prompt \
--slot-prompt-similarity 0
```

| Case | Requests | Failed | Duration | Input tokens | Output tokens | Req/s | Total tok/s | Mean TTFT | P95 TTFT | Mean E2E | P95 E2E |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| random 1024 in / 1 out / c1 | 8 | 0 | 95.25s | 8,192 | 8 | 0.084 | 86.09 | 11.91s | 12.94s | 11.91s | 12.94s |
| random 1024 in / 1 out / c2 | 12 | 0 | 144.86s | 12,288 | 12 | 0.083 | 84.91 | 23.52s | 29.02s | 23.52s | 29.02s |
| random 1024 in / 1 out / c4 | 16 | 0 | 200.24s | 16,384 | 16 | 0.080 | 81.90 | 46.79s | 82.56s | 46.79s | 82.56s |

Raw outputs:

```text
/root/deepseek-v4-w7900d/results/vllm-bench-mxfp4-moe-np4-c16384-prefill-cacheoff/random-i1024-o1-n8-c1.json
/root/deepseek-v4-w7900d/results/vllm-bench-mxfp4-moe-np4-c16384-prefill-cacheoff/random-i1024-o1-n12-c2.json
/root/deepseek-v4-w7900d/results/vllm-bench-mxfp4-moe-np4-c16384-prefill-cacheoff/random-i1024-o1-n16-c4.json
```

This is the cleaner current result: `-np 4` is now stable, and `c1` improves from the old 128K-context `-np 1` baseline of 72.47 tok/s to 86.09 tok/s. Increasing benchmark concurrency to 2 or 4 does not increase aggregate prefill throughput on this layer-split ROCm setup; it mostly increases per-request TTFT. That suggests the bottleneck is still the model execution path and multi-GPU pipeline, not the HTTP request queue.

One negative tuning result is worth keeping: `-b 2048 -ub 512 --ctx-checkpoints 0` looked tempting, but it made the `c1` prefill run much worse, dropping to 46.85 total tok/s with a very long tail. The current recommendation stays at `-b 512 -ub 256`.

## `-np` / Parallel Slot Experiment

Upstream llama.cpp server exposes `-np, --parallel N` as the number of server slots. In normal llama-server usage, this is the knob to test when high concurrency is queueing behind one active slot. The corresponding context setting also matters: the effective context per slot is constrained by the total `--ctx-size`, so increasing `-np` usually requires increasing `-c` if each request still needs a large context window.

The first attempt on this DeepSeek4 ROCm build failed during model initialization. I tested both a large and a small context:

| Server config | Result | Failure point |
| --- | --- | --- |
| `-np 2 -c 131072 -b 2048 -ub 256` | failed before `/health` became ready | `llm_build_deepseek4 -> ggml_reshape_3d` |
| `-np 2 -c 32768 -b 512 -ub 256` | failed before `/health` became ready | `llm_build_deepseek4 -> ggml_reshape_3d` |

Raw logs:

```text
/root/deepseek-v4-w7900d/results/llama-server-mxfp4-moe-np2-c131072-b2048.log
/root/deepseek-v4-w7900d/results/llama-server-mxfp4-moe-np2-c32768.log
```

The mismatch was later traced to non-unified KV cache in DeepSeek4 multi-slot mode: a cache tensor carrying the stream dimension, for example `[512, 1, 512, 2]`, was reshaped as if it were single-stream `[512, 1, 512]`. The local fix now automatically enables unified KV cache for DeepSeek4 when `n_seq_max > 1`.

Post-fix smoke tests:

| Server config | Result |
| --- | --- |
| `-np 2 -c 32768 -b 512 -ub 256` | `/health` passed; 2 concurrent completion requests passed |
| `-np 4 -c 16384 -b 512 -ub 256` | `/health` passed; 4 slots launched and completed requests |

Raw logs:

```text
/root/deepseek-v4-w7900d/results/llama-server-mxfp4-moe-np2-c32768-auto-kvu-fix.log
/root/deepseek-v4-w7900d/results/llama-server-mxfp4-moe-np2-auto-kvu-concurrent-smoke.txt
/root/deepseek-v4-w7900d/results/llama-server-mxfp4-moe-np4-c16384-auto-kvu-fix.log
/root/deepseek-v4-w7900d/results/llama-server-mxfp4-moe-np4-auto-kvu-concurrent-smoke.txt
```

The `1024 input / 1 output` table above has now been rerun against `-np 4`. It proves the multi-slot crash is fixed and the server can complete concurrent prefill-style requests without failures. It does not prove a throughput win from concurrency: `c1` remains the best aggregate throughput point in this specific workload.

Additional raw outputs:

```text
/root/deepseek-v4-w7900d/results/vllm-bench-mxfp4-moe/*.json
/root/deepseek-v4-w7900d/results/vllm-bench-mxfp4-moe/*.log
/root/deepseek-v4-w7900d/results/vllm-bench-mxfp4-moe-np4-c16384-prefill-cacheoff/*.json
/root/deepseek-v4-w7900d/results/vllm-bench-mxfp4-moe-np4-c16384-prefill-b2048-ub512-ctxcp0/random-i1024-o1-n8-c1.json
```

## Reading the Numbers

The most important serving metric here is TPOT, because it maps to the decode speed seen by one active request.

Across the Q8 baseline runs:

- TPOT is roughly 122 to 138 ms/token.
- That corresponds to about 7.2 to 8.2 decode tokens/s for one active stream.
- Short prompt single-client serving produces about 6.8 output tokens/s end-to-end.
- 1K prompt single-client serving produces about 4.4 output tokens/s end-to-end.
- 4K prompt single-client serving is prefill dominated, with mean TTFT around 46s.

The concurrency results are not good in the serving sense:

- 128/64 c4 keeps output throughput near c1, but mean TTFT jumps from 1.67s to 26.98s.
- 1024/128 c4 has mean TTFT 57.22s and P95 TTFT 94.88s.

This is expected because these measurements were collected before the DeepSeek4 multi-slot fix, so the stable server used `-np 1`.

MXFP4_MOE improves the measured serving numbers without changing the serving architecture:

- 128/64 c1 output throughput improves from 6.82 to 6.89 tok/s.
- 128/64 c4 output throughput improves from 6.66 to 6.97 tok/s.
- 1024/128 c1 output throughput improves from 4.42 to 4.54 tok/s.
- 4096/64 c1 output throughput improves from 1.17 to 1.19 tok/s.
- TPOT improves in every matched case.
- In the 1024/1 prefill stress case, c32/n100 reaches 76.44 total tok/s, compared with 72.47 total tok/s for c1/n10.
- After the multi-slot fix, `-np 4` with cache-off benchmark settings reaches 86.09 total tok/s on the 1024/1 c1 prefill run.
- Raising benchmark concurrency from c1 to c4 on this `-np 4` setup keeps all requests successful but reduces aggregate throughput from 86.09 to 81.90 total tok/s and raises mean TTFT from 11.91s to 46.79s.

The improvement is modest, but it is consistent and comes with a much smaller model file.

## Current Recommendation

For a public technical blog, present this as a feasibility, reproducibility, and tuning result:

```text
8 x W7900D can run DeepSeek-V4-Flash locally with bati.cpp ROCm.
The original Q8_0 GGUF path is the conservative baseline.
The current measured performance winner is MXFP4_MOE requantized from Q8_0.
```

Do not position it as a high-throughput serving result yet.

The practical next step is:

1. Run task-level quality evaluation on MXFP4_MOE versus Q8_0.
2. Compare native Q4_K_M quality against MXFP4_MOE and decide whether its slower speed buys better answers.
3. Tune DeepSeek4 `-np > 1` beyond correctness, especially slot scheduling, KV behavior, and ROCm graph shape.
4. Revisit a stable vLLM ROCm DeepSeek V4 FP8 / MXFP4 MoE backend.
5. If a smaller stable model fits in fewer cards, test process-level sharding, for example two 4-GPU server instances.

Until quality evaluation says otherwise, publish MXFP4_MOE as the performance path and Q8_0 as the conservative baseline.
