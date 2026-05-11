# bati.cpp local patchset

This directory captures the local bati.cpp changes required to run DeepSeek-V4-Flash Q8_0 on the 8x W7900D ROCm host.

## Patch

- `bati-deepseek-v4-w7900d-local-fixes.patch`

## Contents

1. `convert_hf_to_gguf.py`

   Adds `F8_E8M0` / `F8_E8M0FNU` fallback handling for the Torch CPU wheel used during local conversion. Without this, the DeepSeek V4 safetensors metadata can stop conversion before GGUF writing.

2. `ggml/src/ggml-backend.cpp`

   Raises `GGML_SCHED_MAX_SPLIT_INPUTS` from `30` to `256`. DeepSeek V4 with 8 GPU layer split exceeded the default scheduler input cap during `sched_reserve`.

3. `ggml/src/ggml-cuda/concat.cu`

   Extends the HIP/CUDA concat path beyond F32. The DeepSeek V4 graph hit concat on same-type F16/BF16/I16/I8/I32 tensors; the original kernel asserted on non-F32.

## Validation

Commands used after these changes:

```bash
git -C /root/bati.cpp diff --check -- \
  convert_hf_to_gguf.py \
  ggml/src/ggml-backend.cpp \
  ggml/src/ggml-cuda/concat.cu

cmake --build /root/bati.cpp/build-hip \
  --target llama-completion llama-server llama-bench \
  --config Release -j 32

env MODEL=/data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-Q8_0-bati-local.gguf \
  CTX_SIZE=4096 N_PREDICT=16 \
  /root/deepseek-v4-w7900d/scripts/run_cli.sh
```

Known result:

```text
运行成功
```

The patch is intentionally recorded as a local engineering patchset, not an upstream-ready PR. The concat change needs a smaller upstream review shape, and the scheduler limit should ideally become architecture-aware rather than a global constant bump.

