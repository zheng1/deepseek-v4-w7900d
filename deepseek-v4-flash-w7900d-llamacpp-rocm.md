# 8x AMD Radeon PRO W7900D 上跑通 DeepSeek-V4-Flash

> 环境日期：2026-05-08  
> 机器：8 x AMD Radeon PRO W7900D 48GB，合计约 384GB VRAM  
> 原始跑通路线：DeepSeek-V4-Flash safetensors -> 本地 Q8_0 GGUF -> bati.cpp/ROCm -> llama-server  
> 2026-05-09 优化更新：当前性能最优路线是从 Q8_0 GGUF 重量化得到的 MXFP4_MOE GGUF

## 结论

这台 8 卡 W7900D 工作站可以跑 DeepSeek-V4-Flash。当前最稳的路线不是 vLLM、SGLang 或 Ollama，而是：

```bash
DeepSeek-V4-Flash 官方权重
  -> bati.cpp convert_hf_to_gguf.py 转 Q8_0 GGUF
  -> bati.cpp ROCm/HIP 后端
  -> split-mode layer
  -> llama-server OpenAI/llama.cpp compatible API
```

进一步 benchmark 后，当前性能最好的服务模型不是 Q8_0，而是：

```bash
/data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-MXFP4_MOE-requant-from-Q8_0.gguf
```

它把 MoE expert 张量压到 MXFP4，其余大量张量仍保持 Q8_0。这个方案在 `llama-bench` 和 `vllm bench serve` 两种口径下都比 Q8_0 略快，同时模型体积明显更小。Q8_0 仍然保留为保守质量基线。

最终服务已在本机启动：

```bash
http://127.0.0.1:8080
```

健康检查：

```bash
curl --noproxy '*' http://127.0.0.1:8080/health
```

注意这里用了 `--noproxy '*'`。这台机器环境里 curl 会受代理变量影响，不加这个参数时，`/completion` 这类 POST 路由可能被代理返回 404。

## 硬件和软件

| 项目 | 值 |
|---|---|
| OS | Ubuntu 24.04.3 LTS |
| Kernel | 6.8.0-79-generic |
| CPU | 2 x AMD EPYC 9334 32-Core Processor |
| RAM | 约 1TiB |
| GPU | 8 x AMD Radeon PRO W7900D |
| GPU arch | gfx1100 |
| VRAM | 49136MiB x 8，合计 393088MiB |
| ROCm | 7.0.2 / HIP 7.0.51831 |
| 推理框架 | bati.cpp commit `c7b64fe06`, build 8933 |
| 模型 | DeepSeek-V4-Flash MXFP4_MOE GGUF；Q8_0 GGUF 保留为质量基线 |
| GGUF 大小 | MXFP4_MOE 文件 145G；Q8_0 文件 282G |
| 参数规模 | 284.33B total, 13B active MoE |

参考资料：

- BatiAI DeepSeek-V4-Flash GGUF：`https://huggingface.co/batiai/DeepSeek-V4-Flash-GGUF`。model card 写明当前是 early access，需要 `bati.cpp`，主线 llama.cpp 和 Ollama 兼容仍在等待合并；同时列出了 Q3/Q4/Q5/Q6/Q8 量化大小。
- antirez/llama.cpp DeepSeek V4 build 文档：`https://github.com/antirez/llama.cpp-deepseek-v4-flash/blob/main/docs/build.md`。该文档给出了 HIP/ROCm 构建方式，并说明 RDNA3/CDNA 上可用 `GGML_HIP_ROCWMMA_FATTN=ON` 改善 Flash Attention。
- 官方 DeepSeek-V4-Flash 权重来自 ModelScope：`https://modelscope.cn/models/deepseek-ai/DeepSeek-V4-Flash`。

## 为什么没有继续用 vLLM、SGLang、Ollama

这台机器是 8 张 PCIe 工作站卡，不是 MI300X/MI325X 这种 Instinct 服务器节点。DeepSeek V4 的新结构和混合精度权重对推理框架要求很高，vLLM/ROCm 的支持还处于快速变化阶段。

Ollama 方向也试过，普通模型能跑，但 DeepSeek-V4-Flash 的 GGUF 支持依赖主线 llama.cpp 合并 deepseek4 架构。BatiAI model card 也明确提示：当前 GGUF 需要 bati.cpp，Ollama 要等 mainline 合并后自动跟进。

所以本次目标从“框架优雅”改为“先真实跑通，再围绕可复现路径优化”。这就是选择 bati.cpp 的原因。

## 构建 ROCm 版 bati.cpp

安装 ROCm 7.0.2 后，构建命令如下：

```bash
cd /root/bati.cpp

env HIPCXX="$(hipconfig -l)/clang" \
    HIP_PATH="$(hipconfig -R)" \
    ROCM_PATH="$(hipconfig -R)" \
    cmake -S . -B build-hip -G Ninja \
      -DGGML_HIP=ON \
      -DGGML_HIP_NO_VMM=ON \
      -DGGML_HIP_ROCWMMA_FATTN=ON \
      -DGPU_TARGETS=gfx1100 \
      -DCMAKE_BUILD_TYPE=Release

cmake --build build-hip \
  --target llama-completion llama-server llama-bench llama-gguf-split llama-quantize \
  --config Release -j 32
```

`GGML_HIP_NO_VMM=ON` 对这类 consumer/workstation ROCm 环境更稳。`GPU_TARGETS=gfx1100` 对应 W7900D/RDNA3。

## 权重转换

本机已经有官方 safetensors：

```bash
/data/models/deepseek-ai/DeepSeek-V4-Flash
```

转换环境：

```bash
python -m venv /data/bati-convert-venv
/data/bati-convert-venv/bin/pip install \
  torch==2.6.0+cpu transformers gguf safetensors numpy sentencepiece
```

实际转换命令：

```bash
env LLAMA_CPP_LIBGGML=/root/bati.cpp/build-hip/bin/libggml.so \
  /data/bati-convert-venv/bin/python /root/bati.cpp/convert_hf_to_gguf.py \
  /data/models/deepseek-ai/DeepSeek-V4-Flash \
  --outfile /data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-Q8_0-bati-local.gguf \
  --outtype q8_0 \
  --deepseek4-expert-workers 16
```

转换结果：

```text
n_tensors = 1328
total_size = 302.2G
final file = 282G
```

这里做了一个小兼容补丁：Torch 2.6 CPU wheel 没有 `torch.float8_e8m0fnu`，而 DeepSeek V4 的 metadata 里会出现 `F8_E8M0`。转换脚本里把这两个 dtype fallback 到 `torch.uint8`，转换可以继续，后续 GGUF 写出正常。

## 跑通过程中的三个坑

### 1. `--fit on` 触发调度器断言

bati.cpp 默认 `fit_params = true`，会先估算显存并自动调整参数。在 DeepSeek V4 + 8 GPU layer split 上，这一步触发：

```text
GGML_ASSERT(n_graph_inputs < GGML_SCHED_MAX_SPLIT_INPUTS) failed
```

解决方式：启动时显式加：

```bash
-fit off
```

### 2. layer split 的 graph input 数超过默认上限

关闭 fit 后，真正构造上下文时仍然遇到同一个上限。默认：

```cpp
#define GGML_SCHED_MAX_SPLIT_INPUTS 30
```

本地临时提高到：

```cpp
#define GGML_SCHED_MAX_SPLIT_INPUTS 256
```

这是为了让 DeepSeek V4 的 fused Gated Delta Net 在 8 GPU pipeline/layer split 下完成 graph reserve。改完后，日志显示：

```text
sched_reserve: fused Gated Delta Net (autoregressive) enabled
sched_reserve: fused Gated Delta Net (chunked) enabled
```

### 3. HIP concat 只支持 F32

模型开始生成后，第一版在第二个 token 附近崩溃：

```text
ggml-cuda/concat.cu:165: GGML_ASSERT(src0->type == GGML_TYPE_F32) failed
```

原因是 DeepSeek V4 运行图里会 concat F16/BF16/I16/I8/I32 这类同类型张量，而 HIP/CUDA concat kernel 只有 F32 分支。本地补了一个通用同类型拷贝版本，支持 1/2/4 字节标量类型。补完后，模型可以完整生成：

```text
运行成功
```

## 最终启动命令

性能优先版本：

```bash
/root/deepseek-v4-w7900d/scripts/run_server_mxfp4_moe.sh
```

等价展开：

```bash
MODEL=/data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-MXFP4_MOE-requant-from-Q8_0.gguf \
CTX_SIZE=16384 \
PARALLEL=1 \
BATCH_SIZE=512 \
UBATCH_SIZE=256 \
/root/deepseek-v4-w7900d/scripts/run_server.sh
```

保守 Q8_0 基线仍然可用：

我把启动封装成了：

```bash
/root/deepseek-v4-w7900d/scripts/run_server.sh
```

关键参数：

```bash
llama-server \
  -m /data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-Q8_0-bati-local.gguf \
  -sm layer \
  -ngl 99 \
  -c 16384 \
  -b 512 \
  -ub 256 \
  -fa on \
  -fit off \
  --no-op-offload \
  --no-warmup \
  -np 1 \
  --host 0.0.0.0 \
  --port 8080
```

后台启动：

```bash
setsid bash -c 'exec env CTX_SIZE=16384 PARALLEL=1 BATCH_SIZE=512 UBATCH_SIZE=256 /root/deepseek-v4-w7900d/scripts/run_server.sh' \
  > /root/deepseek-v4-w7900d/results/llama-server-q8.log 2>&1 < /dev/null &
```

测试请求：

```bash
/root/deepseek-v4-w7900d/scripts/make_prompt.py \
  '只输出这四个字：运行成功' \
  --mode chat \
  --out /root/deepseek-v4-w7900d/results/prompt-chat.txt

PROMPT=$(jq -Rs . /root/deepseek-v4-w7900d/results/prompt-chat.txt)

curl --noproxy '*' http://127.0.0.1:8080/completion \
  -H 'Content-Type: application/json' \
  -d "{\"prompt\":$PROMPT,\"n_predict\":16,\"temperature\":0,\"cache_prompt\":false}"
```

返回：

```json
{
  "content": "运行成功",
  "tokens_predicted": 3,
  "tokens_evaluated": 17
}
```

## 显存占用

16K context、`-b 512 -ub 256`、layer split 下，server 的内存分布约为：

| GPU | model MiB | context MiB | compute MiB | free MiB |
|---:|---:|---:|---:|---:|
| 0 | 40056 | 15 | 2167 | 6522 |
| 1 | 33400 | 20 | 1705 | 13634 |
| 2 | 40071 | 21 | 1996 | 6672 |
| 3 | 33385 | 15 | 1669 | 13690 |
| 4 | 40071 | 21 | 1996 | 6672 |
| 5 | 33400 | 20 | 1705 | 13634 |
| 6 | 40071 | 21 | 1996 | 6672 |
| 7 | 27250 | 14 | 1452 | 20044 |

能看出 layer split 的层分布并不均匀，GPU0/2/4/6 比较紧，GPU7 很松。这也是后续优化的重点。

## Benchmark

benchmark 使用 `llama-bench` 和 `vllm bench serve` 两种口径。服务端都是 bati.cpp/llama-server，vLLM 只作为标准 benchmark client。

### 当前性能最优：MXFP4_MOE

`MXFP4_MOE` 是从 Q8_0 GGUF 本地重量化得到的 MoE expert FP4 版本：

```text
/data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-MXFP4_MOE-requant-from-Q8_0.gguf
```

`llama-bench`，8 卡全开，`-sm layer -ngl 99 -nopo 1 -b 512 -ub 256 -fa 1`：

| 测试 | tok/s |
|---|---:|
| prompt 512 | 118.04 |
| decode 64 | 9.52 |

`vllm bench serve`，OpenAI-compatible `/v1/completions`：

| 场景 | Output tok/s | Total tok/s | Mean TTFT | Mean TPOT | Mean E2E |
|---|---:|---:|---:|---:|---:|
| 128 in / 64 out / n8 / c1 | 6.89 | 20.66 | 1771 ms | 119.4 ms | 9294 ms |
| 128 in / 64 out / n16 / c4 | 6.97 | 20.91 | 25790 ms | 119.1 ms | 33290 ms |
| 1024 in / 128 out / n4 / c1 | 4.54 | 40.90 | 12650 ms | 122.2 ms | 28166 ms |
| 4096 in / 64 out / n2 / c1 | 1.19 | 77.64 | 45339 ms | 130.8 ms | 53579 ms |

### Q8_0 基线：`-b 256 -ub 128 -fa 1`

| 测试 | tok/s |
|---|---:|
| prompt 64 | 94.56 |
| prompt 256 | 81.27 |
| prompt 512 | 77.36 |
| prompt 1024 | 73.24 |
| decode 16 | 9.14 |
| decode 64 | 9.14 |

### 调优：`-b 512 -ub 256 -fa 1`

| 测试 | tok/s |
|---|---:|
| prompt 512 | 115.66 |
| decode 64 | 9.22 |

### 对照：`-b 512 -ub 256 -fa 0`

| 测试 | tok/s |
|---|---:|
| prompt 512 | 118.50 |
| decode 64 | 8.87 |

结论：

1. `ubatch=256` 对 prefill 改善明显，p512 从 77.36 tok/s 提到 115.66 tok/s。
2. Flash Attention 对 p512 prefill 没有明显优势，关闭后略高；但 decode 从 9.22 降到 8.87 tok/s。
3. server 保留 `-fa on`，因为在线服务更关心 decode，且差距虽小但稳定。
4. `row` split 在这版代码上不稳定，初始化时报：

```text
pre-allocated tensor (blk.0.attn_output_a.weight (reshaped)) in a buffer (ROCm0_Split) that cannot run the operation (RESHAPE)
```

因此当前生产候选仍然是 `layer` split。

## 当前瓶颈

### Decode 速度低

MXFP4_MOE 的 `llama-bench` decode 约 9.5 tok/s，vLLM benchmark client 看到的在线输出吞吐约 6.9 tok/s。对于 284B 总参数、13B active MoE 的模型，在 8 张 PCIe W7900D 上这已经是可用路线，但离高吞吐服务还有距离。

主要瓶颈可能来自：

- PCIe 多卡 pipeline 的同步和跨卡数据移动。
- 即使用 MXFP4_MOE，PCIe 多卡 pipeline 仍然会限制在线吞吐。
- DeepSeek V4 的 HCA/CSA/fused Gated Delta Net 路径仍是 early access 实现。
- 当前为稳定关闭了部分 op offload。

### 初始化慢

初次 load 主要慢在大文件 mmap/权重搬运。调好 `-b 512 -ub 256` 后，`sched_reserve` 本身已经从数分钟降到约 3.5 秒，但整体 server 仍需要几分钟加载 282G GGUF。

## 后续优化方向

### 1. 补质量评估和 native Q4_K_M 对照

当前性能最优是本地 MXFP4_MOE 重量化版本。它压缩了 MoE expert 权重，benchmark 比 Q8_0 略好，但还需要补一轮任务级质量评估。

native Q4_K_M 社区 GGUF 仍在下载。下载完成后要用同一套 smoke、`llama-bench` 和 `vllm bench serve` 矩阵对照，确认它是否能超过 MXFP4_MOE。

### 2. 把本地补丁整理成可维护 patch

当前有三个本地改动：

- `convert_hf_to_gguf.py`：`F8_E8M0` fallback 到 `torch.uint8`。
- `ggml-backend.cpp`：`GGML_SCHED_MAX_SPLIT_INPUTS 30 -> 256`。
- `ggml-cuda/concat.cu`：HIP/CUDA concat 支持非 F32 同类型张量。

这些应该整理成独立 patch，并尽量向 bati.cpp 或上游反馈。

### 3. 继续调 layer split

当前显存不均衡很明显。手动 `--tensor-split` 尝试未成功加载，但这不代表方向不成立。更稳的做法是：

- 先记录每层大小。
- 根据层大小做离散 layer placement。
- 避免 GPU0/2/4/6 逼近 90% 以上。
- 给 GPU7 多放一些层。

### 4. 扩展 benchmark

当前 benchmark 覆盖了 p64/p256/p512/p1024 和 decode 16/64。后续建议扩展：

- context：16K / 32K / 64K。
- batch：512 / 1024。
- ubatch：128 / 256 / 384。
- 并发：`-np 1/2/4`，看吞吐和单请求延迟。
- native Q4_K_M 与 MXFP4_MOE / Q8_0 对比。

### 5. 关注主线 llama.cpp/Ollama 合并进度

等 deepseek4 进入 mainline llama.cpp 后，可以重新评估：

- Ollama 是否可直接拉取 DeepSeek-V4-Flash。
- llama.cpp 官方 server 是否不再需要本地补丁。
- 是否出现更好的 IQ4/IQ3 imatrix 量化。

## 复现实验文件

| 文件 | 说明 |
|---|---|
| `/data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-Q8_0-bati-local.gguf` | 本地 Q8_0 GGUF |
| `/data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-MXFP4_MOE-requant-from-Q8_0.gguf` | 当前性能最优 MXFP4_MOE GGUF |
| `/data/models/deepseek-v4-gguf/logs/convert-q8_0-full.log` | 转换日志 |
| `/root/deepseek-v4-w7900d/scripts/run_server.sh` | server 启动脚本 |
| `/root/deepseek-v4-w7900d/scripts/run_server_mxfp4_moe.sh` | MXFP4_MOE 性能优先启动脚本 |
| `/root/deepseek-v4-w7900d/scripts/run_cli.sh` | 单次 completion 验证脚本 |
| `/root/deepseek-v4-w7900d/results/bench/*.jsonl` | benchmark 原始结果 |
| `/root/deepseek-v4-w7900d/results/bench/*.fail.log` | 失败路线日志，例如 row split |
| `/root/deepseek-v4-w7900d/results/llama-server-mxfp4-moe.log` | 当前 MXFP4_MOE server 日志 |
| `/root/deepseek-v4-w7900d/results/server-completion-test-background.json` | API 验证结果 |

## 优化 Round 1/2 更新

后续五个优化方向已经逐项跑过一轮，完整记录在：

```text
/root/deepseek-v4-w7900d/deepseek-v4-flash-w7900d-optimization-round1.md
```

Round 1 当时的结论是：Q4_K_M 本地 requantize 能产出文件但 bench 不稳定，row/tensor split 仍不可用，`-np > 1` server 会触发 DeepSeek4 图构建断言，vLLM nightly 仍卡在 ROCm 的 MXFP4 MoE backend。当时的生产建议是保持 Q8_0 + bati.cpp ROCm + layer split + `-np 1`；这个建议已经被 Round 2 的 MXFP4_MOE 结果更新。

Round 2 继续测试了 Q2_K、Q3_K_M、KV cache quantization 和 MXFP4_MOE，完整记录在：

```text
/root/deepseek-v4-w7900d/deepseek-v4-flash-w7900d-lowbit-round2.md
```

这一轮的新结论是：MXFP4_MOE 是当前性能最优解；Q2/Q3 只是省显存，不提速；KV cache q8/q4 当前被 ROCm concat type 支持卡住。

vLLM benchmark client 对 Q8_0 serving 压测结果在：

```text
/root/deepseek-v4-w7900d/deepseek-v4-flash-w7900d-vllm-benchmark.md
```

核心结果是：Q8_0 + layer split + `-np 1` 的 128/64 单并发输出吞吐约 6.8 tok/s，1K/128 单并发输出吞吐约 4.4 tok/s。MXFP4_MOE 把这两个场景分别提升到约 6.9 tok/s 和 4.5 tok/s，并降低 TPOT。

## 一句话版本

8 x W7900D 可以跑 DeepSeek-V4-Flash，但不要从 vLLM/Ollama 起步。当前可落地路线是 bati.cpp ROCm + MXFP4_MOE GGUF + layer split；跑通需要少量本地补丁。性能上，vLLM serving benchmark 看到 128/64 单并发输出吞吐约 6.9 tok/s，1K/128 单并发约 4.5 tok/s；底层 `llama-bench` decode 约 9.5 tok/s，p512 prefill 约 118 tok/s。下一阶段最值得做的是 native Q4_K_M 对照、质量评估、修 `-np > 1`、等待 vLLM ROCm backend 成熟。
