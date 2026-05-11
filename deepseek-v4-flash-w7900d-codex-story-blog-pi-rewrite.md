# 我让 Codex、Hermes 和 Pi 一起折腾了 12 小时，最后在 8 张 W7900D 上跑起了 DeepSeek-V4-Flash

> 机器：8 x AMD Radeon PRO W7900D 48GB  
> 运行时：bati.cpp / ROCm  
> 最终服务：OpenAI-compatible `/v1/completions`  
> 当前推荐模型：DeepSeek-V4-Flash MXFP4_MOE GGUF

我最近拿到一台很有意思的机器：8 张 AMD Radeon PRO W7900D，每张 48GB，合计 384GB 显存。

显存看起来很大，问题也很直接：能不能拿它跑 DeepSeek-V4-Flash？

后来故事又往前走了一点：我还把 Pi 接到了这套本地模型上，让它直接通过工具调用去碰这台机器上的模型。于是这次不只是把服务跑起来，而是把它真正接进了工作流。

如果这是一台 8 卡 MI300X，我大概会先翻 vLLM 的 recipe；如果这是 CUDA 机器，故事也许会短很多。但它偏偏是一台 8 张 RDNA3 工作站卡的 PCIe 机器。显存够，互联一般，ROCm 能跑，但很多新模型支持还在路上。

这类活最烦的地方不是“执行命令”，而是你永远不知道下一脚会踩到哪里：

- vLLM 支不支持这个模型？
- SGLang 有没有对应实现？
- Ollama 页面上有模型，真的能跑吗？
- llama.cpp 主线支持到哪一步了？
- ROCm kernel 会不会半路炸？
- 多卡应该 layer split 还是 tensor split？
- 量化越小就一定越快吗？

于是我做了一个很偷懒但很现代的决定：把同一个任务同时丢给两个 agent，看它们会怎么想。

Codex 负责直接上机器干活，Hermes 接 GPT-5.5 负责做更完整的外部调研。刚开始我只是想看看：面对同一个模型、同一台机器，不同 agent 会不会走出完全不同的路线。

后来结果挺明显：Hermes 做资料收集更全面，Codex 在本机执行、编译、改代码、跑 benchmark 这类事情上更靠谱。于是中间我打断了 Codex，把 Hermes 的调研结论喂给它，让它按更靠谱的方向继续执行。

我给 Codex 的要求大意是：我要睡觉了，你先研究。一条路不通就换路，能搜索就搜索，能编译就编译，能 benchmark 就 benchmark，直到跑起来。

然后我真的去睡了。

第二天看结果，它不但跑起来了，还把 vLLM、SGLang、Ollama、bati.cpp、Q8/Q4/Q3/Q2/MXFP4、KV cache、serving benchmark 都过了一遍。更离谱的是，这篇文章的大部分素材也是它从自己的操作记录里整理出来的。

后面我又补了一步：把 Pi 也接到这套本地模型上，让另一个 coding agent 能通过 OpenAI tools 调用本地工具。到这一步，它就不只是“模型服务能回字”，而是真的开始进入日常工作流了。

## 先剧透结论

这台 8 x W7900D 可以跑 DeepSeek-V4-Flash。

但当前最合适的路线不是 vLLM、SGLang，也不是 Ollama，而是：

```text
DeepSeek-V4-Flash 官方权重
  -> 本地转换 GGUF
  -> bati.cpp ROCm/HIP
  -> layer split 多卡切分
  -> llama-server 提供 OpenAI-compatible API
```

当前性能最好的模型是：

```text
/data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-MXFP4_MOE-requant-from-Q8_0.gguf
```

启动脚本：

```bash
/root/deepseek-v4-w7900d/scripts/run_server_mxfp4_moe.sh
```

服务地址：

```text
http://127.0.0.1:8080
```

健康检查：

```bash
curl --noproxy '*' http://127.0.0.1:8080/health
```

返回：

```json
{"status":"ok"}
```

## 机器配置

| 项目 | 配置 |
|---|---|
| GPU | 8 x AMD Radeon PRO W7900D |
| 单卡显存 | 48GB |
| 总显存 | 384GB 级别 |
| GPU 架构 | gfx1100 |
| CPU | AMD EPYC 9334 |
| 系统 | Ubuntu 24.04 |
| ROCm | 7.0.2 |
| 推理运行时 | bati.cpp ROCm build |
| 多卡策略 | layer split |
| 服务方式 | llama-server |

这台机器的问题不在“模型装不装得下”。384GB 显存摆在那里，DeepSeek-V4-Flash 的低精度版本肯定有机会。

真正的问题是：这 8 张卡是 PCIe 工作站卡，不是专门为大模型推理准备的 Instinct 服务器节点。显存很能打，互联不算豪华。跑这种新模型，路线要选得很现实。

## 第一回合：vLLM 看起来最正统，但没走通

vLLM 是我最想优先跑通的路线。原因很简单：它标准、好服务化、benchmark 也方便和别人对比。

Codex 查了 vLLM 的 ROCm 镜像，也试了官方版本和 nightly。问题很快就暴露了：DeepSeek V4 的模型结构太新，权重里带 `deepseek_v4_fp8`、MXFP4 MoE 等路径，而 ROCm backend 还没完整覆盖这套组合。

其中一个关键错误是：

```text
No MXFP4 MoE backend supports the deployment configuration.
```

这句话基本可以翻译成：命令没写错，但后端还没准备好。

所以 vLLM 没被完全丢掉，而是换了个位置：不负责推理，只负责 benchmark。后面所有 `vllm bench serve` 的结果，都是 vLLM 作为压测客户端去打 bati.cpp 的 `/v1/completions` 接口。

这点很重要。文章里所有 vLLM benchmark 数字，不代表 vLLM 在这台机器上跑 DeepSeek-V4-Flash；真正跑模型的是 bati.cpp。

## 第二回合：SGLang 和 Ollama 也各有卡点

SGLang 也试过。ROCm 容器能起来，GPU 也能看到，但当时没有一条明确的 DeepSeek V4 模型实现路径。继续往下做，很可能不是调参数，而是补框架。

Ollama 也试过。Ollama 的体验确实简单，普通模型能跑。但 DeepSeek-V4-Flash 当时依赖 llama.cpp 的 deepseek4 架构支持，而这部分还没完整进入主线。Ollama 页面上有东西，不等于这台机器上马上能拉起来跑。

所以这两条线都被放进“以后主线成熟再看”的篮子里。

工程里有些路看起来很优雅，但今晚不一定能到家。

## 第三回合：最后收敛到 bati.cpp

真正让事情收敛的是 bati.cpp。

它已经包含 DeepSeek V4 相关支持，社区 GGUF 也指向这条路线。Codex 最后选择它，不是因为它名字最响，而是因为它最有机会在这台机器上当天跑通。

构建命令大致如下：

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

几个参数比较关键：

- `GGML_HIP=ON`：启用 ROCm/HIP。
- `GGML_HIP_NO_VMM=ON`：对这种工作站 ROCm 环境更稳。
- `GGML_HIP_ROCWMMA_FATTN=ON`：启用 RDNA3 上相关 Flash Attention 路径。
- `GPU_TARGETS=gfx1100`：W7900D 对应的目标架构。

## 模型从哪里来

我希望尽量用 ModelScope。原因也朴素：大文件下载，快一点就是快很多。这个官方 safetensors 不是我提前手动准备好的，而是 Codex 在执行过程中从 ModelScope 下载/整理到本机的：

```text
/data/models/deepseek-ai/DeepSeek-V4-Flash
```

然后 Codex 把它转换成 Q8_0 GGUF：

```bash
env LLAMA_CPP_LIBGGML=/root/bati.cpp/build-hip/bin/libggml.so \
  /data/bati-convert-venv/bin/python /root/bati.cpp/convert_hf_to_gguf.py \
  /data/models/deepseek-ai/DeepSeek-V4-Flash \
  --outfile /data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-Q8_0-bati-local.gguf \
  --outtype q8_0 \
  --deepseek4-expert-workers 16
```

这个 Q8_0 文件约 282GB，是最保守的质量基线。

后面又从这个 Q8_0 GGUF 重量化出 MXFP4_MOE：

```bash
/root/bati.cpp/build-hip/bin/llama-quantize --allow-requantize \
  /data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-Q8_0-bati-local.gguf \
  /data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-MXFP4_MOE-requant-from-Q8_0.gguf \
  MXFP4_MOE 64
```

MXFP4_MOE 的结果：

```text
model size  = 288244.36 MiB
quant size  = 147892.36 MiB
文件大小     = 145G
```

这里的 `MXFP4_MOE` 不是全模型 FP4。它主要压 MoE expert 张量，attention、embedding、indexer 等大量张量仍保留 Q8_0。这一点后面很关键：它不是最小的，但它是目前最快的。

## 几个坑，踩完就老实了

### float8 dtype 卡转换

DeepSeek V4 权重 metadata 里出现了 `F8_E8M0` / `F8_E8M0FNU`。Torch CPU wheel 对这些 dtype 支持不完整，转换脚本一开始会失败。

Codex 在 `convert_hf_to_gguf.py` 里做了 fallback，把相关 scale tensor 当作 raw `uint8` 处理，转换才继续跑完。

### `-fit` 自动估算显存不靠谱

bati.cpp 默认会做 fit/显存估算，但 DeepSeek V4 + 8 GPU layer split 下触发 scheduler 断言。

最后启动时显式关掉：

```bash
-fit off
```

### graph split input 上限不够

DeepSeek V4 的图在 8 GPU layer split 下 graph input 比默认上限更多。默认上限是 30，不够。

Codex 把：

```cpp
GGML_SCHED_MAX_SPLIT_INPUTS
```

从 30 提到 256，后面 graph reserve 才能过。

### ROCm concat kernel 类型不够

运行时还遇到 HIP concat kernel 只支持部分类型的问题。DeepSeek V4 图里会 concat F16/BF16/I16/I8/I32 等同类型张量，原实现不够。

Codex 给 concat kernel 补了同类型拷贝支持，模型才真正生成成功。

### `-np > 1` 的坑：最后是 KV cache 模式

llama-server 的多 slot 模式本来是提升并发的方向。一开始我试 `-np 2` / `-np 4`，服务会在图构建阶段崩，堆栈落在 `llm_build_deepseek4 -> ggml_reshape_3d`。

后来继续追日志，发现不是 context 大小的问题，而是 DeepSeek4 这条实现遇到非 unified KV cache 时，把带 stream 维度的 cache tensor 当成单 stream tensor 去 reshape。典型现场是源 tensor 类似 `[512, 1, 512, 2]`，代码却按 `[512, 1, 512]` 处理，少了最后那个 slot/stream 维度。

修法没有硬改 attention 形状，而是在 DeepSeek4 `n_seq_max > 1` 时自动开启 unified KV cache。这样用户忘了手动加 `--kv-unified` 也不会直接炸。

修完后我重新测了两组：

| 配置 | 结果 |
|---|---|
| `-np 2 -c 32768 -b 512 -ub 256` | `/health` 通过，2 路并发 completion 通过 |
| `-np 4 -c 16384 -b 512 -ub 256` | `/health` 通过，4 个 slot 都实际跑请求 |

所以现在的结论要改一下：`-np > 1` 不是不能碰，而是 DeepSeek4 multi-slot 必须走 unified KV。崩溃已经在本地 bati.cpp 里兜住了，后面的问题从“能不能启动”变成了“并发下到底有多少收益”。

修完以后我补了一轮 `vllm bench serve`，继续用 `1024 input / 1 output` 看 prefill。服务端是 `-np 4 -c 16384 -b 512 -ub 256`，并且关掉 prompt cache，避免随机 prompt benchmark 把缓存清理时间混进去。

| 场景 | 请求数 | 并发 | Failed | Total tok/s | Mean TTFT | P95 TTFT |
|---|---:|---:|---:|---:|---:|---:|
| 1024/1 | 8 | 1 | 0 | 86.09 | 11.91s | 12.94s |
| 1024/1 | 12 | 2 | 0 | 84.91 | 23.52s | 29.02s |
| 1024/1 | 16 | 4 | 0 | 81.90 | 46.79s | 82.56s |

这就很符合这台机器的性格：并发请求现在能稳定进来，但总吞吐没有因为并发翻倍。多 slot 解决的是可用性和排队形态，不是自动把 layer split 的 8 卡流水变成线性加速器。

我还试了 `-b 2048 -ub 512 --ctx-checkpoints 0`，单并发 prefill 反而掉到 46.85 tok/s。这个坑也值得写出来：参数名字看着很大，不代表显卡就会更高兴。

## 低精度实验：越小不一定越快

Codex 一共试了几条低精度路线：

| 路线 | 结果 |
|---|---|
| Q2_K | 能跑，省显存，但不提速 |
| Q3_K_M | 能跑，省显存，但比 Q8 慢 |
| 本地 Q4_K_M requant | 能产出文件，短测能跑，长 benchmark 不稳定 |
| MXFP4_MOE | 能跑，稳定，当前性能最好 |
| native Q4_K_M | 能跑，稳定，但性能不如 MXFP4_MOE，也没有比 Q3_K_M 快 |

先把这些名字翻成人话。

`Q8_0` 基本就是保守基线：权重大多按 8 bit 存，精度损失小，文件也最大。它的好处是稳，坏处是显存和磁盘都吃得多。

`Q2_K`、`Q3_K_M`、`Q4_K_M` 属于 llama.cpp/GGUF 里的 K-quants。它们不是简单地把每个数粗暴截成 2/3/4 bit，而是按 block 分组保存量化值、scale、min/修正项等信息。推理时 kernel 要把这些低 bit 权重按 block 解包、反量化，再参与矩阵计算。`K_M` 里的 `M` 可以粗略理解成 medium 配方：不是所有张量都用同一种 bit width，而是按张量重要程度混合不同精度。

这里有个坑：文件小，不等于算得快。低 bit 权重省了带宽，但也带来了 unpack/dequant 的开销。如果这条 ROCm kernel 路径对某种量化格式优化不够，或者解包之后的数据流让图执行更碎，最后就可能出现“更小但更慢”。

`native Q4_K_M` 和本地从 Q8_0 再 requant 出来的 Q4_K_M 也不完全是一回事。前者是社区直接发布的 GGUF 分片，元数据和张量布局更完整；后者是本地二次量化出来的。实际结果也符合这个判断：native Q4_K_M 稳定，requant Q4_K_M 短测能跑但长 benchmark 不稳。

`MXFP4_MOE` 更特殊。它不是把整个模型都变成 FP4，而是主要压 MoE expert 权重，attention、embedding、indexer、路由相关张量仍保留更高精度。这一点对 DeepSeek-V4-Flash 很关键，因为它是 MoE 模型，expert 权重占了很大一块体积，但每个 token 实际只会激活一小部分 expert。

这个结果挺反直觉。Q2 文件最小，但不是最快。Q3 比 Q8 小很多，也没有更快。

原因大概是：这条 ROCm 路径的瓶颈不只是静态权重大小。MoE 路由、图执行、多卡 pipeline、kernel 支持、张量类型组合，都在影响速度。

MXFP4_MOE 反而最合适，因为它没有把所有东西都粗暴压低，而是主要压 MoE expert 权重，保留了不少 Q8 张量。它像一个比较懂分寸的折中方案。

为什么它会赢，我现在更愿意把它看成几个因素叠加，而不是单一原因：

1. DeepSeek V4 的 MoE expert 权重很大，MXFP4_MOE 正好压在最占地方的部分，收益集中。
2. 非 expert 部分保留更高精度，避免 attention、路由、indexer 这些结构走更激进的低 bit 路径。
3. 当前 ROCm/RDNA3 上，K-quants 的解包和反量化未必比读更大的 Q8/MXFP4 混合权重更便宜。
4. 8 张 W7900D 是 PCIe 多卡，layer split 下 pipeline、graph split、host/device 调度也会吃时间；低 bit 模型如果让图更碎，不一定能换来吞吐。
5. MXFP4_MOE 显存占用比 Q8 低很多，但又没有像 Q2/Q3 那样把所有计算都推向更重的低 bit 解包路径，所以它刚好踩在一个更舒服的位置。

这还不是 profiler 级定论，更像是从 benchmark、日志和模型结构反推出来的工程判断。要把原因钉死，后面还得继续看 kernel timeline、各层耗时和 PCIe/VRAM 带宽。

## 最终服务命令

性能优先版本：

```bash
/root/deepseek-v4-w7900d/scripts/run_server_mxfp4_moe.sh
```

展开后大致是：

```bash
MODEL=/data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-MXFP4_MOE-requant-from-Q8_0.gguf \
CTX_SIZE=16384 \
PARALLEL=1 \
BATCH_SIZE=512 \
UBATCH_SIZE=256 \
/root/deepseek-v4-w7900d/scripts/run_server.sh
```

核心参数：

```bash
llama-server \
  -m /data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-MXFP4_MOE-requant-from-Q8_0.gguf \
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

## 性能账本

### llama-bench

统一参数：

```text
split_mode = layer
n_gpu_layers = 99
flash_attn = true
batch = 512
ubatch = 256
cache_k/cache_v = f16
no_op_offload = 1
```

| 模型 | 模型大小 | Prefill | Decode |
|---|---:|---:|---:|
| MXFP4_MOE | 155.08GB | 118.04 tok/s, p512 | 9.52 tok/s, n64 |
| Q8_0 | 302.25GB | 115.66 tok/s, p512 | 9.22 tok/s, n64 |
| Q2_K | 105.52GB | 102.69 tok/s, p512 | 9.12 tok/s, n64 |
| Q3_K_M | 135.40GB | 95.18 tok/s, p512 | 8.98 tok/s, n64 |
| native Q4_K_M | 171.91GB | 94.49 tok/s, p512 | 8.76 tok/s, n64 |

### vLLM benchmark client

再次提醒：vLLM 只是 benchmark client，推理 backend 是 bati.cpp/llama-server。

### 性能对比图

下面几张是静态 SVG 图片，不依赖网页脚本。绿色是当前推荐的 MXFP4_MOE，红色是后来补测的 native Q4_K_M。

![llama-bench prefill 和 decode 性能对比](assets/chart-llama-bench.svg "llama-bench：prefill 和 decode，MXFP4_MOE 在两项里都领先")

![vLLM benchmark client 输出吞吐对比](assets/chart-serving-output.svg "vLLM benchmark client：不同 prompt 长度下的输出吞吐，后端是 bati.cpp/llama-server")

![vLLM benchmark client Mean TTFT 对比](assets/chart-serving-ttft.svg "vLLM benchmark client：Mean TTFT，越短越好")

![并发 4 输出吞吐和 TTFT 对比](assets/chart-serving-c4.svg "并发 4：修复前 -np 1 单 slot 会让请求主要排队执行")

![修复 multi-slot 后的 -np 4 prefill 压测](assets/chart-prefill-np4.svg "修复 multi-slot 后：-np 4 能稳定并发，但总吞吐没有线性增长")

短请求：

```text
input = 128 tokens
output = 64 tokens
num_prompts = 8
concurrency = 1
```

| 模型 | Output tok/s | Total tok/s | Mean TTFT | Mean TPOT | Mean E2E |
|---|---:|---:|---:|---:|---:|
| MXFP4_MOE | 6.89 | 20.66 | 1.77s | 119ms | 9.29s |
| Q8_0 | 6.82 | 20.46 | 1.67s | 122ms | 9.38s |
| Q2_K | 6.67 | 20.01 | 2.06s | 120ms | 9.60s |
| Q3_K_M | 6.47 | 19.43 | 2.04s | 125ms | 9.88s |
| native Q4_K_M | 6.36 | 19.09 | 2.04s | 127ms | 10.06s |

长一点的 prefill：

```text
input = 1024 tokens
output = 128 tokens
num_prompts = 4
concurrency = 1
```

| 模型 | Output tok/s | Total tok/s | Mean TTFT | Mean TPOT | Mean E2E |
|---|---:|---:|---:|---:|---:|
| MXFP4_MOE | 4.54 | 40.90 | 12.65s | 122ms | 28.17s |
| Q8_0 | 4.42 | 39.77 | 12.82s | 127ms | 28.97s |
| Q3_K_M | 4.09 | 36.77 | 15.12s | 128ms | 31.33s |
| native Q4_K_M | 3.91 | 35.15 | 15.83s | 133ms | 32.77s |

并发 4：

```text
input = 128 tokens
output = 64 tokens
num_prompts = 16
concurrency = 4
```

| 模型 | Output tok/s | Total tok/s | Mean TTFT | Mean TPOT | Mean E2E |
|---|---:|---:|---:|---:|---:|
| MXFP4_MOE | 6.97 | 20.91 | 25.79s | 119ms | 33.29s |
| Q8_0 | 6.66 | 19.98 | 26.98s | 125ms | 34.86s |
| native Q4_K_M | 6.40 | 19.21 | 28.14s | 128ms | 36.22s |

1024/128 并发 4：

```text
input = 1024 tokens
output = 128 tokens
num_prompts = 8
concurrency = 4
```

这一组是 native Q4_K_M 补测时额外跑的，用来观察长一点 prompt 遇到排队时的样子。前面的老结果没有同口径 matched case，所以这里先只放 native Q4_K_M：

| 模型 | Output tok/s | Total tok/s | Mean TTFT | Mean TPOT | Mean E2E |
|---|---:|---:|---:|---:|---:|
| native Q4_K_M | 4.93 | 44.33 | 63.50s | 132ms | 80.26s |

4K prompt：

```text
input = 4096 tokens
output = 64 tokens
num_prompts = 2
concurrency = 1
```

| 模型 | Output tok/s | Total tok/s | Mean TTFT | Mean TPOT | Mean E2E |
|---|---:|---:|---:|---:|---:|
| MXFP4_MOE | 1.19 | 77.64 | 45.34s | 131ms | 53.58s |
| Q8_0 | 1.17 | 75.85 | 46.14s | 138ms | 54.85s |
| native Q4_K_M | 0.97 | 62.86 | 56.98s | 146ms | 66.18s |

## 怎么看这些数字

这不是一个“高并发推理服务已经毕业”的结果。它更像是一个很扎实的落地基线。

MXFP4_MOE 的提升不是一眼起飞，但它在多个场景里都赢：

- `llama-bench` decode 从 9.22 tok/s 到 9.52 tok/s。
- 128/64 单并发输出吞吐从 6.82 tok/s 到 6.89 tok/s。
- 1024/128 单并发输出吞吐从 4.42 tok/s 到 4.54 tok/s。
- 4096/64 长 prompt 场景从 1.17 tok/s 到 1.19 tok/s。
- TPOT 在几组 matched case 里都更低。

如果只追求质量保守，Q8_0 仍然是基线。如果追求当前性能，MXFP4_MOE 是更好的选择。

native Q4_K_M 下载完成后也补测了，结果很明确：能跑，稳定，但不是这台机器上的性能路线。

- `llama-bench` p512 prefill 只有 94.49 tok/s，低于 MXFP4_MOE 的 118.04 tok/s。
- decode n64 是 8.76 tok/s，也低于 MXFP4_MOE 的 9.52 tok/s。
- 128/64 单并发 output tok/s 是 6.36，比 Q3_K_M 的 6.47 还低一点。
- 4096/64 长 prompt 是 0.97 output tok/s，明显低于 MXFP4_MOE 的 1.19。

所以这轮最反直觉的结论没有变：小一点、Q4 一点，不等于更快。这个模型在 ROCm + layer split + 当前 DeepSeek4 kernel 路径下，瓶颈明显不只在模型文件大小。

## Codex 到底干了哪些活

把最后命令贴出来很简单，但这会掩盖真正费劲的部分。

Codex 在后台做了这些事：

1. 检查 8 张 W7900D 是否被 ROCm 正常识别。
2. 检查 vLLM、SGLang、Ollama 的可行性。
3. 查 DeepSeek V4 在 llama.cpp/bati.cpp 里的支持状态。
4. 构建 ROCm 版 bati.cpp。
5. 用 ModelScope 官方 safetensors 做本地 GGUF 转换。
6. 遇到转换 dtype 问题后改转换脚本。
7. 遇到 graph scheduler 上限后改后端参数。
8. 遇到 ROCm concat 类型问题后补 kernel 支持。
9. 跑通 CLI smoke test。
10. 起 llama-server，暴露 OpenAI-compatible endpoint。
11. 用 `llama-bench` 测 prefill 和 decode。
12. 用 `vllm bench serve` 测服务端指标。
13. 测 Q8、Q2、Q3、Q4 requant、native Q4、MXFP4_MOE、KV cache quantization。
14. 记录失败路线和日志。
15. 把实验结果整理成报告和这篇文章。
16. 研究 antirez/ds4 的 DSML 工具协议，把 Pi 的 OpenAI tools 请求桥接到本地 DeepSeek-V4-Flash。
17. 用 Pi 调本地模型和 `ls` 工具做端到端验证，并让它再过了一遍新增章节的表达。

这不是“让 AI 写一段部署教程”。这是把一个真实工程任务交给 agent，让它在真实机器上试错。

## Hermes / GPT-5.5 扮演的角色

这里不是“Codex 先做完，Hermes 后来补充”这么简单。

一开始我是有意把同一个任务交给 Codex 和 Hermes，想看看两个 agent 面对同一个问题会怎么拆。后来发现，Hermes 做调研时考虑得更全面，比如会把 W7900D/ROCm 支持、vLLM 官方 recipe 的目标硬件、DeepSeek V4 ROCm backend 状态、社区 GGUF 量化版本、llama.cpp 多卡 split 策略这些信息放在一起看。

相比之下，Codex 自己检索资料时容易漏上下文，但它非常适合在真实机器上执行：编译、改源码、跑命令、看日志、复现错误、继续换路。

所以中间我打断了 Codex，把 Hermes 的调研逻辑交给它。后面的路线收敛，基本就是这个组合的结果：

这个组合挺顺手：

```text
Hermes / GPT-5.5：查资料、找方向、把坑提前圈出来
Codex：在机器上执行、改代码、跑命令、测 benchmark
```

人负责判断方向，研究 agent 负责补资料，执行 agent 负责在机器上干活。这个分工比单独让一个 agent 从头到尾硬冲要顺很多。

这可能是以后很多复杂工程任务的常见形态。

## native Q4_K_M 补测结果

native Q4_K_M 这条线后来也补完了。

本地 Q4_K_M requantized from Q8_0 能生成文件，但长 benchmark 不稳定，所以暂时不作为推荐方案。

社区 native Q4_K_M 确实更靠谱。ModelScope 没找到对应 GGUF 镜像，所以这组是从 Hugging Face 的 BatiAI GGUF 拉下来的。下载过程不算优雅，中间遇到过 signed URL 过期和最后几个 range 卡住，最后靠 aria2 断点续传、刷新连接把四个分片补齐：

```text
dir = /data/models/deepseek-v4-native-gguf/batiai-q4km
size = 160.10 GiB / 171.91 GB
```

smoke test 用的是：

```bash
MODEL=/data/models/deepseek-v4-native-gguf/batiai-q4km/deepseek-ai-DeepSeek-V4-Flash-Q4_K_M-00001-of-00004.gguf \
CTX_SIZE=4096 \
N_PREDICT=16 \
/root/deepseek-v4-w7900d/scripts/run_cli.sh
```

结果是能完整加载，`44/44` 层全部 offload 到 GPU，也能正常生成。

标准 `llama-bench`：

```bash
MODEL=/data/models/deepseek-v4-native-gguf/batiai-q4km/deepseek-ai-DeepSeek-V4-Flash-Q4_K_M-00001-of-00004.gguf \
LABEL=native-q4km-batiai \
/root/deepseek-v4-w7900d/scripts/bench_gguf_standard.sh
```

结果是：

```text
prefill p512 = 94.49 tok/s
decode  n64  = 8.76 tok/s
```

再用 `vllm bench serve` 打 OpenAI-compatible endpoint，128/64 单并发是 6.36 output tok/s，1024/128 单并发是 3.91 output tok/s，4096/64 单并发是 0.97 output tok/s。

结论就一句：native Q4_K_M 能跑，而且比本地 requant Q4_K_M 稳，但它不是当前最优性能路线。

## 现在推荐怎么跑

性能优先：

```bash
/root/deepseek-v4-w7900d/scripts/run_server_mxfp4_moe.sh
```

质量保守：

```bash
MODEL=/data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-Q8_0-bati-local.gguf \
CTX_SIZE=16384 \
PARALLEL=1 \
BATCH_SIZE=512 \
UBATCH_SIZE=256 \
/root/deepseek-v4-w7900d/scripts/run_server.sh
```

当前定位：

| 方案 | 定位 |
|---|---|
| MXFP4_MOE | 当前性能路线 |
| Q8_0 | 保守质量基线 |
| Q2_K | 省显存/省磁盘，不是性能路线 |
| Q3_K_M | 省显存，但性能不如 Q8 |
| native Q4_K_M | 能跑且稳定，但当前性能不如 MXFP4_MOE/Q8 |

## 顺手把 Pi 也接进来了

跑通服务之后，我又顺手干了一件更像“日常使用”的事：把 Pi 接到本地模型上。

原因很简单。我不想只有服务端自己在跑，还想让另一个 coding agent 直接用这台机器上的 DeepSeek-V4-Flash 做工具调用，看看它能不能真正融进工作流。

这一步一开始没那么顺。Pi 走的是标准的 OpenAI tools 格式，但 DeepSeek-V4-Flash 在 llama-server 上对 `tool_calls` 的输出不太稳定。我去翻了翻 antirez/ds4 的实现，发现它没有硬等 OpenAI 的工具调用，而是自己定义了一层 DSML：先把工具 schema 写进 prompt，再把模型吐出来的 DSML 块转回 OpenAI 格式。

于是我照着这个思路写了一个 `pi_openai_tool_proxy.py`：

- 把 OpenAI `tools` 转成 DSML prompt
- 把历史里的 assistant/tool 消息转回 DSML
- 把模型输出的 DSML 再翻成标准 `tool_calls`

最后我用 Pi 真跑了一次本地 `ls` 工具，结果是通的。也就是说，这台机器现在不只是能跑服务，还能让 agent 直接把本地模型当工具来用。

我最后用的 Pi 启动方式大致是：

```bash
env -u http_proxy -u https_proxy -u all_proxy \
  NO_PROXY=127.0.0.1,localhost \
  PI_OFFLINE=1 \
  pi --offline \
  --provider local-llama-tools \
  --model DeepSeek-V4-Flash-MXFP4_MOE-requant-from-Q8_0.gguf \
  --tools read,ls,grep,find,bash
```

这里还有个很小但很烦的坑：机器上有全局 `http_proxy=127.0.0.1:1080`，所以本地 `127.0.0.1` 请求要么设 `NO_PROXY`，要么直接把 proxy 环境变量 unset 掉。不然看起来像是 Pi 或代理坏了，其实只是本地请求被绕去另一个代理了。

这个步骤对我很重要。因为“能跑起来”只是第一层，“能被接进工作流”才是真的能用。

## 后续还值得折腾什么

这件事还没到终点。

后面最值得做的是：

1. 给 MXFP4_MOE 和 Q8_0 做任务级质量评估。
2. 给 native Q4_K_M 做质量评估，看看慢一点是否换来更稳的输出质量。
3. 继续调 DeepSeek4 `-np 2` / `-np 4` 的 slot 调度、KV 行为和 ROCm 图执行效率。
4. 继续观察 vLLM ROCm DeepSeek V4 / MXFP4 MoE backend。
5. 如果低精度模型能稳定塞进更少 GPU，测试两个 4 卡实例这种进程级分片。
6. 做 32K、64K context 的长上下文 benchmark。
7. 把 Pi/DSML 工具桥的 streaming、parallel tool calls 和更多工具场景补完整。

尤其是 `-np > 1`。启动崩溃已经修掉，同口径 benchmark 也补了第一轮；下一步不是证明“能不能跑”，而是让 multi-slot 下的 TTFT、吞吐、KV cache 占用和长上下文稳定性真正好看起来。

## 复现实验文件

| 文件 | 说明 |
|---|---|
| `/root/deepseek-v4-w7900d/scripts/run_server_mxfp4_moe.sh` | 当前性能优先启动脚本 |
| `/root/deepseek-v4-w7900d/scripts/run_server.sh` | 通用 llama-server 启动脚本 |
| `/root/deepseek-v4-w7900d/scripts/bench_gguf_standard.sh` | 标准 `llama-bench` 包装脚本 |
| `/root/deepseek-v4-w7900d/scripts/generate_perf_charts.js` | 静态性能对比图生成脚本 |
| `/root/deepseek-v4-w7900d/scripts/pi_openai_tool_proxy.py` | Pi OpenAI tools 到 DSML 的本地代理 |
| `/root/deepseek-v4-w7900d/logs/pi_openai_tool_proxy.log` | Pi 工具桥端到端验证日志 |
| `/root/.pi/agent/models.json` | Pi 本地模型 provider 配置 |
| `/data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-MXFP4_MOE-requant-from-Q8_0.gguf` | 当前性能最优 GGUF |
| `/data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-Q8_0-bati-local.gguf` | Q8_0 保守质量基线 |
| `/data/models/deepseek-v4-native-gguf/batiai-q4km/deepseek-ai-DeepSeek-V4-Flash-Q4_K_M-00001-of-00004.gguf` | native Q4_K_M split GGUF 入口文件 |
| `/root/deepseek-v4-w7900d/results/bench/llama-bench-native-q4km-batiai-sm-layer-fa1-p512-n64-b512-ub256-r2.jsonl` | native Q4_K_M `llama-bench` 原始结果 |
| `/root/deepseek-v4-w7900d/results/vllm-bench-mxfp4-moe/*.json` | MXFP4_MOE serving benchmark 原始结果 |
| `/root/deepseek-v4-w7900d/results/vllm-bench-native-q4km/*.json` | native Q4_K_M serving benchmark 原始结果 |
| `/root/deepseek-v4-w7900d/site/assets/chart-*.svg` | 本文使用的静态性能图 |
| `/root/deepseek-v4-w7900d/deepseek-v4-flash-w7900d-lowbit-round2.md` | 低精度和 KV cache 实验报告 |
| `/root/deepseek-v4-w7900d/deepseek-v4-flash-w7900d-vllm-benchmark.md` | vLLM benchmark client 报告 |

参考链接：

- ModelScope DeepSeek-V4-Flash：`https://modelscope.cn/models/deepseek-ai/DeepSeek-V4-Flash`
- BatiAI DeepSeek-V4-Flash GGUF：`https://huggingface.co/batiai/DeepSeek-V4-Flash-GGUF`
- antirez llama.cpp DeepSeek V4 build 文档：`https://github.com/antirez/llama.cpp-deepseek-v4-flash/blob/main/docs/build.md`
- antirez/ds4：`https://github.com/antirez/ds4`

## 最后

这次最有意思的地方，不是某个单独的 benchmark 数字，而是工作方式变了。

以前这种活，大概是一个人泡一晚上：查资料、下载、编译、报错、再查、再改、再测。

这次我先把同一个目标丢给 Codex 和 Hermes，看它们会怎么拆。Hermes 的调研更完整，Codex 的本机执行更强，所以中间我把 Hermes 的结论转交给 Codex，让它继续在机器上干活。第二天回来，它已经把服务跑起来、benchmark 跑完、失败路线记好、文章草稿也写好了。

再往后，我又把 Pi 接到这套本地模型上，用同一个 DeepSeek-V4-Flash 做了一次真实工具调用，还让它把本文新增章节的表达润了一遍。这个闭环挺有意思：本地模型先被跑起来，然后又反过来参与整理“它是怎么被跑起来的”。

最后落地路线是：

```text
DeepSeek-V4-Flash
  -> GGUF
  -> bati.cpp ROCm
  -> MXFP4_MOE
  -> layer split
  -> llama-server
```

当前可复现的核心数字：

- `llama-bench` p512 prefill 约 118 tok/s
- `llama-bench` decode n64 约 9.5 tok/s
- `vllm bench serve` 128/64 单并发约 6.9 output tok/s
- `vllm bench serve` 1024/128 单并发约 4.5 output tok/s
- native Q4_K_M 已补测，稳定但更慢：p512 约 94.5 tok/s，128/64 单并发约 6.4 output tok/s

它不是一个华丽的“秒杀一切”结果，但它是一个真实的工程结果。更重要的是，它展示了一种新的做事方式：人定目标，agent 查资料和执行，机器自己在夜里慢慢把坑填上。
