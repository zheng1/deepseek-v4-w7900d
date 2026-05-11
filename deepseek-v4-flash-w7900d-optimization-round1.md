# DeepSeek-V4-Flash on 8x W7900D: Optimization Round 1

Date: 2026-05-08

Hardware:

- GPU: 8 x AMD Radeon PRO W7900D, 48 GB each, 384 GB total VRAM
- Host ROCm: 7.0.2
- Stable runtime: bati.cpp / llama.cpp ROCm build
- Stable model: `/data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-Q8_0-bati-local.gguf`
- Stable serving command: `/root/deepseek-v4-w7900d/scripts/run_server.sh`

This round covered the five optimization directions left from the first deployment pass:

1. lower-bit GGUF, especially Q4_K_M and Q3_K_M
2. local patchset cleanup
3. split strategy: layer, row, tensor split
4. server-side concurrency
5. vLLM ROCm re-check

## Executive Summary

| Direction | Result | Decision |
| --- | --- | --- |
| Q4_K_M / Q3_K_M | Native download was too slow for an overnight full test. Local requantization from Q8_0 produced Q4/Q3 artifacts, but Q4_K_M crashed in longer benchmark paths. | Do not publish local requantized Q4/Q3 as a performance win. Keep Q8_0 as stable baseline. Test native BatiAI Q4/Q3 later. |
| Patchset | Local bati.cpp changes were isolated and exported. `git diff --check` passed. | Keep the patchset as the reproducibility anchor for the blog. |
| Row / tensor split | `row` fails on a ROCm split-buffer reshape; manual tensor split fails model load. | Keep `-sm layer` as the only stable split mode on this W7900D box. |
| Server concurrency | Initial `-np 2` and `-np 4` attempts crashed during DeepSeek4 graph setup. Root cause was non-unified KV cache exposing a stream dimension that DeepSeek4 reshaped as single-stream. | Patched locally: DeepSeek4 multi-slot now auto-enables unified KV cache. `-np 2` and `-np 4` smoke tests pass; rerun full serving benchmarks next. |
| vLLM ROCm | v0.20.1 rejects DeepSeek V4 FP8 quantization on ROCm. Nightly gets further but fails because no MXFP4 MoE backend supports this deployment configuration. | vLLM is still not a practical route for this 8 x W7900D machine today. Revisit when ROCm DeepSeek V4 MoE backend support lands. |

The stable recommendation remains:

```bash
MODEL=/data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-Q8_0-bati-local.gguf \
CTX_SIZE=16384 \
PARALLEL=1 \
BATCH_SIZE=512 \
UBATCH_SIZE=256 \
/root/deepseek-v4-w7900d/scripts/run_server.sh
```

## 1. Q4_K_M / Q3_K_M

### What was tried

The initial idea was to move from Q8_0 to Q4_K_M or Q3_K_M because the machine has enough aggregate VRAM but limited PCIe interconnect. A smaller model should reduce transfer pressure and leave more memory for KV cache.

Three routes were evaluated:

- direct conversion from Hugging Face safetensors
- downloading native split GGUF from BatiAI
- local requantization from the working Q8_0 GGUF

Direct conversion was blocked because the current conversion entrypoint only exposes:

```text
f32, f16, bf16, q8_0, iq2_xxs, iq2_xs, q2_k, tq1_0, tq2_0, auto
```

It does not directly emit Q4_K_M or Q3_K_M for this path.

Native BatiAI GGUF files do exist, including Q4_K_M and Q3_K_M split files, but the observed download rate was only around 3.6 to 3.7 MB/s in this environment. That makes a clean Q4/Q3 native download too slow for a short optimization pass.

Local requantization was then tested:

- Q4_K_M smoke quantization from a one-layer model succeeded.
- Q3_K_M smoke quantization from a one-layer model succeeded.
- Full Q4_K_M requantization from Q8_0 also completed.

Full Q4_K_M output:

```text
model size  = 288244.36 MiB (8.50 BPW)
quant size  = 163947.41 MiB (4.84 BPW)
quantize time = 700320.94 ms
```

Output artifact:

```text
/data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-Q4_K_M-requant-from-Q8_0.gguf
```

### Benchmark behavior

A short CLI run with the requantized Q4_K_M model did complete:

```text
prompt eval: 8.60 tok/s
decode eval: 3.88 tok/s
```

This is worse than the stable Q8_0 CLI baseline from the patched path:

```text
prompt eval: 8.15 tok/s
decode eval: 4.16 tok/s
```

More importantly, the Q4_K_M benchmark path is not stable. A prompt-only benchmark at a larger prompt length hit:

```text
/root/bati.cpp/src/models/deepseek4.cpp:1153:
GGML_ASSERT(n_comp_visible <= n_comp_cache) failed
```

### Decision

The local Q4_K_M requantized model is not a safe optimization result. It may be useful for debugging, but it should not be presented as the production path.

Next useful Q4/Q3 work:

- download native BatiAI Q4_K_M and Q3_K_M split GGUF files when bandwidth is available
- compare native Q4_K_M against Q8_0 with the same `llama-bench` matrix
- only publish Q4/Q3 numbers if the native files survive CLI, server, and longer prompt benchmarks

## 2. Patchset Cleanup

The local bati.cpp changes were exported to:

```text
/root/deepseek-v4-w7900d/patches/bati-deepseek-v4-w7900d-local-fixes.patch
```

Patch README:

```text
/root/deepseek-v4-w7900d/patches/README.md
```

The patchset contains three local fixes:

- `convert_hf_to_gguf.py`: handle `F8_E8M0` / `F8_E8M0FNU` by treating the scale tensor as raw `uint8`
- `ggml/src/ggml-backend.cpp`: raise `GGML_SCHED_MAX_SPLIT_INPUTS` from 30 to 256 for the DeepSeek4 graph on multi-GPU ROCm
- `ggml/src/ggml-cuda/concat.cu`: allow ROCm concat for the extra integer and half/bfloat16 tensor types seen in this model path

Validation:

```text
git diff --check
```

passed cleanly.

### Decision

This patchset should be the reproducibility anchor in the deployment blog. It makes the working Q8_0 path explainable and repeatable without hiding local source edits.

## 3. Split Strategy

### Layer split

Layer split remains the stable mode:

```bash
-sm layer -ngl 99
```

This fits the hardware shape: eight 48 GB workstation cards connected over PCIe, not a tightly coupled Instinct node.

### Row split

Minimal row split testing failed:

```text
pre-allocated tensor (blk.0.attn_output_a.weight (reshaped))
in a buffer (ROCm0_Split) that cannot run the operation (RESHAPE)
```

### Tensor split

Manual equal split also failed model load:

```text
main: error: failed to load model
```

### Decision

Do not use row split or tensor split for this model on this ROCm W7900D stack yet. The blog should describe layer split as a deliberate choice, not just the first thing that happened to work.

## 4. Server Concurrency

### Multi-slot server

The stable server runs with:

```bash
-np 1 -c 16384
```

Initial attempts to use llama.cpp server slots with `-np 2` or `-np 4` crashed during DeepSeek4 graph setup.

For `-np 4 -c 4096`:

```text
n_ctx_seq = 1024
GGML_ASSERT(ggml_nelements(a) == ne0*ne1*ne2) failed
```

For `-np 2 -c 4096`:

```text
n_ctx_seq = 2048
GGML_ASSERT(ggml_nelements(a) == ne0*ne1*ne2) failed
```

For `-np 2 -c 8192`:

```text
n_ctx_seq = 4096
GGML_ASSERT(ggml_nelements(a) == ne0*ne1*ne2) failed
```

So this is not only a too-small-context issue. The crash was later traced to non-unified KV cache in DeepSeek4 multi-slot mode: `mctx_swa->get_k()` can return a cache view with a stream dimension, while the DeepSeek4 graph path reshaped it as if it were single-stream.

Local fix:

```text
DeepSeek4 + n_seq_max > 1 + kv_unified=false
=> automatically enable kv_unified
```

Post-fix validation:

| Config | Result |
| --- | --- |
| `-np 2 -c 32768 -b 512 -ub 256` | `/health` passed; 2 concurrent completion requests passed |
| `-np 4 -c 16384 -b 512 -ub 256` | `/health` passed; 4 slots launched and completed requests |

Logs:

```text
/root/deepseek-v4-w7900d/results/llama-server-mxfp4-moe-np2-c32768-auto-kvu-fix.log
/root/deepseek-v4-w7900d/results/llama-server-mxfp4-moe-np4-c16384-auto-kvu-fix.log
```

### External concurrent requests against `-np 1`

A small OpenAI-compatible `/v1/completions` concurrency benchmark was added:

```text
/root/deepseek-v4-w7900d/scripts/bench_server_concurrency.py
```

Results against the stable Q8_0 `-np 1` server:

| Client concurrency | Requests | Failed | Request/s | Predicted tok/s | Avg latency | P95 latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 4 | 0 | 0.786 | 2.36 | 1.27 s | 2.61 s |
| 2 | 4 | 0 | 1.261 | 3.78 | 1.39 s | 1.59 s |
| 4 | 4 | 0 | 1.264 | 3.79 | 1.98 s | 3.16 s |

These are tiny three-token output requests, so the table is a service sanity check rather than a full throughput benchmark. It does show that the server survives concurrent clients, but it also shows that `-np 1` effectively caps usable concurrency by queueing work behind one execution slot.

### Decision

The startup crash is fixed locally. Treat `-np 2` / `-np 4` as the next benchmark target rather than a solved performance win: the smoke tests prove correctness, but not yet optimal throughput or latency.

## 5. vLLM ROCm Re-check

Local ROCm vLLM images tested:

- `vllm/vllm-openai-rocm:v0.20.1`
- `vllm/vllm-openai-rocm:nightly`, reporting `v0.20.2rc1.dev93+g51f22dcfd`

Both images can import the DeepSeek V4 model module. The official safetensors config is recognized as:

```text
model_type = deepseek_v4
architecture = DeepseekV4ForCausalLM
quantization = deepseek_v4_fp8
torch_dtype = bfloat16
```

vLLM v0.20.1 fails early on ROCm:

```text
deepseek_v4_fp8 quantization is currently not supported in rocm
```

Nightly gets further. Without explicit KV cache dtype it fails with:

```text
DeepseekV4 only supports fp8 kv-cache format for now, got auto
```

With:

```bash
--kv-cache-dtype fp8
```

it advances into worker initialization but then fails with:

```text
NotImplementedError: No MXFP4 MoE backend supports the deployment configuration.
```

This was reproduced with tensor parallel size 8 and 4.

### Decision

vLLM is meaningfully closer than it was earlier, but it is still not a practical route for this W7900D machine. The blocker is no longer just argument shape or model import. It is backend support for the DeepSeek V4 FP8 / MXFP4 MoE execution path on this ROCm deployment.

The deployment blog should keep vLLM in the "revisit later" section and name the specific blocker:

```text
No MXFP4 MoE backend supports the deployment configuration.
```

## Current Production Recommendation

Use Q8_0 GGUF with bati.cpp ROCm, layer split, one server slot:

```bash
MODEL=/data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-Q8_0-bati-local.gguf \
CTX_SIZE=16384 \
PARALLEL=1 \
BATCH_SIZE=512 \
UBATCH_SIZE=256 \
/root/deepseek-v4-w7900d/scripts/run_server.sh
```

Why this remains the right baseline:

- it runs end to end on all eight W7900D cards
- it serves an OpenAI-compatible endpoint
- it survives repeated client requests
- it has a small, documented local patchset
- all attempted "faster" routes either failed or were not stable enough to publish

## Next Optimization Queue

The next round should focus on changes with a plausible path to stable improvement:

1. Download native BatiAI Q4_K_M and Q3_K_M GGUF files on a faster link and benchmark them directly.
2. Investigate the DeepSeek4 `n_comp_visible <= n_comp_cache` assertion on local requantized Q4_K_M.
3. Minimize and report the `-np > 1` DeepSeek4 server crash upstream.
4. Re-test vLLM when ROCm DeepSeek V4 FP8 / MXFP4 MoE backend support changes.
5. Build a longer benchmark matrix: prompt lengths 64, 256, 1024, 4096 and decode lengths 16, 64, 256.

## Artifacts

Primary deployment blog:

```text
/root/deepseek-v4-w7900d/deepseek-v4-flash-w7900d-llamacpp-rocm.md
```

Agent retrospective blog:

```text
/root/deepseek-v4-w7900d/deepseek-v4-flash-w7900d-agent-retrospective.md
```

Patchset:

```text
/root/deepseek-v4-w7900d/patches/bati-deepseek-v4-w7900d-local-fixes.patch
```

Q4_K_M requantization log:

```text
/data/models/deepseek-v4-gguf/logs/requant-q4km-full.log
```

Q4_K_M failure log:

```text
/root/deepseek-v4-w7900d/results/bench/llama-bench-q4km-requant-layer-fa-p256-only.fail.log
```

Split strategy failure logs:

```text
/root/deepseek-v4-w7900d/results/bench/llama-bench-q8-row-fa-p64-n16-r1.fail.log
/root/deepseek-v4-w7900d/results/bench/llama-bench-q8-layer-ts-equal-fa-p64-n16-r1.fail.log
```

Server concurrency benchmark:

```text
/root/deepseek-v4-w7900d/scripts/bench_server_concurrency.py
/root/deepseek-v4-w7900d/results/server-concurrency-q8-np1-summary.json
```

vLLM failure logs:

```text
/root/deepseek-v4-w7900d/results/vllm-v0201-deepseek-v4-flash-serve.log
/root/deepseek-v4-w7900d/results/vllm-nightly-deepseek-v4-flash-serve-kvfp8.log
/root/deepseek-v4-w7900d/results/vllm-nightly-deepseek-v4-flash-tp4-kvfp8.log
```
