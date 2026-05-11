# 三个多小时跑通 DeepSeek-V4-Flash：8x W7900D 的工程复盘

> 草稿时间：2026-05-08  
> 复盘对象：Codex session、命令记录、模型转换日志、运行日志和 benchmark 产物  
> 主要时间窗口：2026-05-08 15:40-18:54 UTC  
> 机器：8 x AMD Radeon PRO W7900D 48GB，合计约 384GB VRAM

这篇不是一篇普通的部署教程。上一篇技术稿已经把“怎么启动、怎么 benchmark、当前性能是多少”写出来了；这篇更像是工程复盘：在用户睡觉的几个小时里，一个目标从“能不能用 vLLM 或 SGLang 跑 DeepSeek V4”不断变成“找一条能真实跑通的路线”，中间我具体做了什么、为什么这么做、哪里失败了，以及最后为什么收敛到 `DeepSeek-V4-Flash + bati.cpp/ROCm + GGUF + layer split`。

先给结论：

1. 这台 8x W7900D 机器确实跑通了 DeepSeek-V4-Flash。
2. 当前跑通的不是 vLLM、SGLang 或 Ollama，而是 bati.cpp 的 ROCm/HIP 后端。
3. 实际运行的是本地转换出来的 Q8_0 GGUF，文件约 282GB。
4. 最终服务已通过 `llama-server` 在 `127.0.0.1:8080` 提供接口。
5. 当前最好的一组可复现参数是 `split-mode=layer`、`-b 512`、`-ub 256`、`-fa on`、`-fit off`、`--no-op-offload`。
6. 这个结果依赖三个本地补丁：转换脚本 dtype fallback、调度器 split input 上限、HIP concat kernel 类型支持。

## 我读了哪些记录

这次复盘不是凭印象写的。我读了几类本机记录：

- Codex 用户消息历史：`/root/.codex/history.jsonl`
- Codex session JSONL：`/root/.codex/sessions/2026/05/07/rollout-2026-05-07T16-35-40-019e034b-7fea-7a92-9e1e-5edfa088f678.jsonl`
- Codex TUI 日志：`/root/.codex/log/codex-tui.log`
- 项目产物目录：`/root/deepseek-v4-w7900d`
- GGUF 转换目录：`/data/models/deepseek-v4-gguf`
- bati.cpp 本地 diff：`/root/bati.cpp`

其中 session 记录给出了完整命令序列，文件 mtime 给出了产物落盘时间，日志文件给出了失败原因和最终运行结果。下面的时间线以 2026-05-08 UTC 的产物和命令时间为准。

## 用户目标怎么变化

最开始的问题很开放：这台机器是 AMD，显卡正常吗，能不能跑 DeepSeek V4，用 vLLM 还是 SGLang？

后面目标变化了几次：

1. 先让我自己做决策，下载模型并不断尝试，直到能运行。
2. 接着要求做比较全面的 benchmark，写一篇对外技术博客。
3. 中间希望优先考虑标准 vLLM benchmark，并质疑为什么不直接用 vLLM。
4. 又要求放弃 vLLM/SGLang，转向 Ollama。
5. 再后来给了 antirez 的 DeepSeek V4 llama.cpp fork build 文档，让我评估能否跑通。
6. 最后给了一份外部调研结论，核心建议是 `DeepSeek-V4-Flash + llama.cpp/ROCm + GGUF + layer split`。

我的处理原则是：每次用户改变优先级，我都先验证这条路是不是有足够事实支撑。如果当前路线缺少 DeepSeek V4 支持、无法下载、或无法在 W7900D/ROCm 上稳定跑，就把失败证据留下，然后换路线。

## 为什么没有坚持 vLLM

vLLM 是更标准的服务框架，用户也明确问过“为什么不直接用 vLLM 来 run”。所以我没有直接放弃它，而是查了最新镜像和文档，并试了 ROCm 容器。

但这台机器不是 MI300X/MI325X 这类 Instinct 节点，而是 8 张 RDNA3 工作站卡。DeepSeek V4 又是非常新的结构，带新的权重量化、MoE、Gated Delta Net 等路径。vLLM/ROCm 对 DeepSeek V4 的支持在当时还处于快速变化中，官方更明确面向 Instinct 8 卡系统。

工程判断上，vLLM 继续折腾有两个问题：

- 风险不在启动参数，而在模型结构和 ROCm kernel 覆盖。
- 即使某个镜像能拉起来，也可能进入很深的适配问题，无法保证睡觉期间稳定收敛。

所以 vLLM 被我降级成“后续优化方向”，而不是首条跑通路线。

## 为什么 SGLang 也没成为主线

SGLang 的 ROCm 镜像我也检查过，容器能识别 8 张 GPU，torch/HIP 环境也能起来。但是镜像内没有明确的 `deepseek_v4` 模型实现路径，搜索到的主要还是 DeepSeek V2/V3、function call parser、OCR/VL 等相关文件。

这意味着继续尝试 SGLang 很可能也会卡在模型结构支持上，而不是普通部署问题。对“睡觉期间无人值守跑通”的目标来说，这不是最稳路线。

## 为什么 Ollama 没有解决 DeepSeek V4

用户后来要求放弃 vLLM/SGLang，转向 Ollama，并给了 Ollama 的 DeepSeek-V4-Flash 页面。Ollama 的优势是简单，但它底层依赖 llama.cpp 的 GGUF loader 和模型架构支持。DeepSeek V4 当时还没有完全进入主线 llama.cpp/Ollama 路径，社区 GGUF 明确需要专门分支或 bati.cpp。

我也按用户要求试了 `ollama launch hermes --model qwen3.6` 这类路径，证明 Ollama 本身和普通模型能工作。但这只能说明 Ollama 服务栈可用，不能说明 DeepSeek-V4-Flash 可用。

因此 Ollama 被保留为“主线合并后的简化部署方向”，但不是这次跑通 DeepSeek V4 的核心方案。

## 真正收敛的路线

真正让工作收敛的是 antirez 的文档和用户贴出的外部调研结论。它们都指向同一个方向：

```text
DeepSeek-V4-Flash
  -> GGUF
  -> llama.cpp compatible runtime
  -> ROCm/HIP
  -> 多卡 layer split
```

我随后检查了 antirez fork、本地已有模型、BatiAI 的 DeepSeek-V4-Flash GGUF 信息和 bati.cpp。最后没有直接用 stock llama.cpp，而是切到 bati.cpp，原因很直接：

- DeepSeek V4 的 GGUF 和运行时支持还在 early access。
- BatiAI 的 model card 明确指向 bati.cpp。
- bati.cpp 里有 DeepSeek V4 相关转换和运行支持。
- 这台机器已有官方 safetensors，绕过远程 GGUF 下载会更可控。

换句话说，我最后不是在“选最漂亮的框架”，而是在“选最有机会当天跑通的代码路径”。

## 时间线

### 15:40-15:48：检查 antirez fork 和 ROCm 构建

我先读了 `/root/llama.cpp-deepseek-v4-flash` 的 README、CMake、examples/tools 结构，并尝试用 ROCm 构建。

第一轮 CMake 发现缺少 HIP BLAS 相关包，于是安装：

```bash
apt-get install -y hipblas hipblas-dev
```

随后构建 `llama-cli`、`llama-server`、`llama-bench`。这一步的目标不是马上跑 V4，而是确认 ROCm toolchain、gfx1100 目标和 llama.cpp 类项目的构建链路是通的。

### 15:48-16:00：尝试远程 GGUF 下载，但迅速判断网络不可控

我先查了 antirez 的 Hugging Face repo 文件列表，并尝试下载一个 IQ2XXS GGUF。尝试过：

- `curl -C -`
- `aria2c`
- `huggingface-cli`
- `hf download`
- `hf_transfer`
- 代理和直连对比
- `hf-mirror.com`

结果是下载不稳定，进度太慢，且远程文件很大。继续走远程 GGUF 下载，可能几个小时都只是在等网络。

这里的关键判断是：机器本地已经有官方 ModelScope safetensors，路径是：

```text
/data/models/deepseek-ai/DeepSeek-V4-Flash
```

所以我停止了远程 GGUF 下载，把方向改成本地转换。这个决策后面证明是正确的：后续主要时间花在可控的 CPU 转换和运行时调试上，而不是不可控的网络下载。

### 16:01-16:07：切到 bati.cpp，建立转换环境

我检查了 `/root/bati.cpp`，确认它包含 DeepSeek V4 相关代码，并用 ROCm 参数构建：

```bash
env HIPCXX="$(hipconfig -l)/clang" \
    HIP_PATH="$(hipconfig -R)" \
    ROCM_PATH="$(hipconfig -R)" \
    cmake -S . -B build-hip -G Ninja \
      -DGGML_HIP=ON \
      -DGGML_HIP_NO_VMM=ON \
      -DGGML_HIP_ROCWMMA_FATTN=ON \
      -DGPU_TARGETS=gfx1100 \
      -DCMAKE_BUILD_TYPE=Release
```

这里的几个参数都有原因：

- `GGML_HIP=ON`：启用 ROCm/HIP 后端。
- `GGML_HIP_NO_VMM=ON`：consumer/workstation ROCm 环境更稳。
- `GGML_HIP_ROCWMMA_FATTN=ON`：RDNA3 上启用相关 Flash Attention 路径。
- `GPU_TARGETS=gfx1100`：W7900D 对应的 GPU target。

随后创建了 `/data/bati-convert-venv`，安装转换依赖。

### 16:08-16:13：先做 1 层 smoke GGUF

我没有直接启动完整 282GB 级别转换，而是先做一个 1 层 smoke：

```bash
convert_hf_to_gguf.py \
  /data/models/deepseek-ai/DeepSeek-V4-Flash \
  --outfile /data/models/deepseek-v4-gguf/smoke-1layer-q8_0.gguf \
  --outtype q8_0 \
  --deepseek4-max-layers 1 \
  --deepseek4-expert-workers 8
```

这个步骤验证两件事：

- 转换脚本能识别 DeepSeek V4 的结构。
- 生成的 GGUF 至少能被当前 runtime load。

这里遇到第一个代码兼容问题：Torch CPU wheel 没有 `torch.float8_e8m0fnu`，但 safetensors metadata 中会出现 `F8_E8M0` / `F8_E8M0FNU`。我补了一个转换脚本 fallback，把这两个 dtype 映射到 `torch.uint8`。

补丁位置：

```text
/root/bati.cpp/convert_hf_to_gguf.py
```

本质上，这不是改变模型数学含义，而是让转换脚本能把该 dtype 的底层字节读出来并继续写 GGUF。

### 16:14-17:40：完整 Q8_0 GGUF 转换

smoke test 能写出 GGUF 之后，我启动完整转换：

```bash
env LLAMA_CPP_LIBGGML=/root/bati.cpp/build-hip/bin/libggml.so \
  /data/bati-convert-venv/bin/python /root/bati.cpp/convert_hf_to_gguf.py \
  /data/models/deepseek-ai/DeepSeek-V4-Flash \
  --outfile /data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-Q8_0-bati-local.gguf \
  --outtype q8_0 \
  --deepseek4-expert-workers 16
```

这一步从 16:14 左右跑到 17:40 左右。中间我持续检查：

- 转换日志 tail
- 进程 CPU/RSS
- `/data` 磁盘空间
- 输出 GGUF 文件增长
- 系统内存余量

最终产物：

```text
/data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-Q8_0-bati-local.gguf
size: 282G
total_size in log: 302.2G
n_tensors: 1328
```

为什么先转 Q8_0，而不是直接 Q4_K_M？原因是这次目标是先跑通。Q8_0 最接近转换脚本当前主路径，变量少；等 runtime 跑通后，再做 Q4/Q3 才更合理。否则如果 Q4 失败，很难区分是量化问题、转换问题，还是运行时问题。

### 17:41-17:57：第一次完整运行失败，定位到调度器和 CLI 入口

完整 GGUF 出来后，我用脚本构造 prompt：

```text
只输出这四个字：运行成功
```

然后用 `llama-cli` / `llama-completion` 做最小生成测试。这里先遇到两个问题：

1. `llama-cli` 对这个模型的对话模式支持不合适，需要换到 `llama-completion` 并显式 `-no-cnv`。
2. 默认 `fit_params` 会触发调度器断言：

```text
GGML_ASSERT(n_graph_inputs < GGML_SCHED_MAX_SPLIT_INPUTS) failed
```

我读了 bati.cpp 的参数解析和 `ggml-backend.cpp`，判断这个断言先出现在自动 fit 阶段，所以在运行参数里加了：

```bash
-fit off
```

但关闭 fit 之后，真正构造上下文时仍然遇到同类上限。这说明问题不只是参数估算阶段，而是 DeepSeek V4 在 8 GPU layer split 下实际 graph input 数确实超过默认阈值。

### 17:57-18:05：调高 scheduler split input 上限

默认值是：

```cpp
#define GGML_SCHED_MAX_SPLIT_INPUTS 30
```

本地临时改成：

```cpp
#define GGML_SCHED_MAX_SPLIT_INPUTS 256
```

补丁位置：

```text
/root/bati.cpp/ggml/src/ggml-backend.cpp
```

这是一个工程性补丁，不是最终上游形态。它的作用是让 DeepSeek V4 的复杂图在 8 卡 split 时能完成 `sched_reserve`。

改完重新构建后，日志开始出现：

```text
sched_reserve: fused Gated Delta Net (autoregressive) enabled
sched_reserve: fused Gated Delta Net (chunked) enabled
```

这说明模型已经越过了前一个阻塞点，进入真实计算阶段。

### 18:05-18:14：HIP concat kernel 只支持 F32，补通用类型分支

模型开始生成后，又在第二个 token 左右崩溃：

```text
/root/bati.cpp/ggml/src/ggml-cuda/concat.cu:165:
GGML_ASSERT(src0->type == GGML_TYPE_F32) failed
```

这个失败很关键。它不是显存不足，也不是 GPU 不可用，而是 HIP/CUDA concat kernel 的类型支持太窄。DeepSeek V4 的运行图里会 concat F16/BF16/I16/I8/I32 等同类型 tensor，但当时 concat kernel 只有 F32 分支。

我先尝试了 `--no-op-offload`、`--no-warmup`，确认问题仍然复现。也就是说这不是 warmup 或 op offload 触发的偶然路径，而是实际图里会走到的算子。

随后我修改：

```text
/root/bati.cpp/ggml/src/ggml-cuda/concat.cu
```

把原来只接受 F32 的 concat 扩展成按类型 dispatch，并为 1/2/4 字节标量类型实现同类型拷贝 kernel。支持范围包括：

```text
F32, I32, F16, BF16, I16, I8
```

重编译后，最小生成测试成功输出：

```text
运行成功
```

对应日志：

```text
/root/deepseek-v4-w7900d/results/cli-q8-4096-concat-patched.log
```

这一步是整个过程的关键拐点：从“模型能 load 但不能推理”变成“模型能真实生成 token”。

### 18:15-18:38：跑 llama-bench 并做参数调优

用户明确问过“用 vLLM 的 benchmark 跑了吗？那个比较标准”。后来虽然放弃 vLLM/SGLang，但 benchmark 仍然需要尽量标准化。所以我用 bati.cpp 自带的 `llama-bench` 跑了多组对比。

基线：

```bash
llama-bench \
  -m /data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-Q8_0-bati-local.gguf \
  -sm layer \
  -ngl 99 \
  -fa 1 \
  -nopo 1 \
  -p 64,256,512,1024 \
  -n 16,64 \
  -b 256 \
  -ub 128 \
  -r 3 \
  -o jsonl
```

主要结果：

| 配置 | 指标 |
|---|---:|
| `-b 256 -ub 128 -fa on`, prompt 64 | 94.556 tok/s |
| `-b 256 -ub 128 -fa on`, prompt 256 | 81.274 tok/s |
| `-b 256 -ub 128 -fa on`, prompt 512 | 77.357 tok/s |
| `-b 256 -ub 128 -fa on`, prompt 1024 | 73.244 tok/s |
| `-b 256 -ub 128 -fa on`, decode 16 | 9.136 tok/s |
| `-b 256 -ub 128 -fa on`, decode 64 | 9.137 tok/s |

然后我调大 batch/ubatch：

| 配置 | 指标 |
|---|---:|
| `-b 512 -ub 256 -fa on`, prompt 512 | 115.658 tok/s |
| `-b 512 -ub 256 -fa on`, decode 64 | 9.223 tok/s |

这说明 prefill 明显受益于更大的 batch/ubatch，而 decode 主要受模型结构、pipeline 和单 token 路径影响。

我也试了关 Flash Attention：

| 配置 | 指标 |
|---|---:|
| `-b 512 -ub 256 -fa off`, prompt 512 | 118.504 tok/s |
| `-b 512 -ub 256 -fa off`, decode 64 | 8.871 tok/s |

`fa off` 的 prompt 512 略高，但 decode 更低。考虑到服务场景里 decode 更关键，最终保留 `-fa on`。

还试了两个失败方向：

- `split-mode=row`：失败，日志里出现 `ROCm0_Split cannot run RESHAPE` 相关错误。
- 手工 `--tensor-split`：加载失败。

这两个失败很有价值：它们说明目前最稳的多卡方式还是 layer split。row/tensor split 是后续优化方向，不该作为首发配置。

### 18:39-18:51：启动 server，并处理 curl 代理干扰

我把最终参数封装到：

```text
/root/deepseek-v4-w7900d/scripts/run_server.sh
```

启动参数核心是：

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

第一次验证接口时有一个小插曲：本机环境的代理变量会影响 curl 请求，导致对 localhost 的 POST 路径返回异常 404。最终用：

```bash
curl --noproxy '*'
```

绕开代理后，`/health` 和 `/completion` 都正常。

服务端测试返回：

```json
{
  "content": "运行成功",
  "tokens_predicted": 3,
  "tokens_evaluated": 17
}
```

当前后台 server 通过 `setsid` 拉起，日志在：

```text
/root/deepseek-v4-w7900d/results/llama-server-q8.log
```

### 18:52-18:54：整理 benchmark 表和第一篇技术博客

最后我从所有 `jsonl` benchmark 里抽取字段，汇总性能数据，然后写了第一篇部署技术稿：

```text
/root/deepseek-v4-w7900d/deepseek-v4-flash-w7900d-llamacpp-rocm.md
```

那篇文章更偏“怎么跑起来”和“当前性能是多少”。本文则补充“这几个小时为什么这么做”。

## 三个多小时主要花在哪里

从记录看，这三个多小时不是一直在写命令。主要消耗分成四类。

第一类是等待大任务完成。完整 Q8_0 GGUF 转换从 16:14 到 17:40，产物 282GB，期间需要持续监控磁盘、内存和进程状态。这类时间不可避免，但不是空等，因为同时可以准备 prompt 脚本、server 脚本、硬件环境记录。

第二类是路线验证。vLLM、SGLang、Ollama、antirez fork、bati.cpp 都不是凭偏好选择的，而是根据“是否支持 DeepSeek V4、是否适配 ROCm、是否能在 W7900D 上今天跑通”来筛选。

第三类是运行时故障定位。最关键的两个失败不是部署错误，而是 bati.cpp/ggml 在 DeepSeek V4 + ROCm + 8 卡 layer split 下的代码路径没覆盖完整：scheduler split input 上限和 HIP concat 类型支持。

第四类是 benchmark 和服务化。跑通 CLI 不等于能对外服务，所以还需要 `llama-bench`、参数对比、server 后台启动、API 测试、代理问题排查和结果整理。

## 当时的工程判断

### 判断一：先跑通，不先追求框架最优雅

vLLM 是工程上更主流的选择，但这次机器是 8x W7900D，不是官方 recipe 常见的 Instinct 节点。DeepSeek V4 又足够新。继续卡在 vLLM/SGLang 适配上，可能很久都没有一个可验证结果。

所以我把目标改成：

```text
先得到一个真实生成 token 的 DeepSeek-V4-Flash，再讨论框架和性能。
```

### 判断二：本地转换比远程下载更可控

远程 GGUF 文件大，Hugging Face 下载路径不稳定；本地已有 ModelScope safetensors。转换虽然耗时，但可监控、可重试、可定位。对无人值守任务来说，可控性比理论上的下载速度更重要。

### 判断三：用 Q8_0 降低变量

用户原本调研里推荐 Q4_K_M 或 Q3_K_M。但我最后先做 Q8_0，因为 Q8_0 更适合第一轮打通转换和 runtime。

如果第一轮就用 Q4_K_M，失败时会多一个变量：到底是量化格式问题，还是模型结构支持问题？先 Q8_0 能把问题聚焦到 loader、scheduler、kernel 和多卡 split。

### 判断四：layer split 是 PCIe 多卡上的保守选择

8 张 W7900D 是 PCIe 工作站卡，互联条件和 MI300X 服务器不同。DeepSeek V4 的模型很大，layer split 更符合“先装下、先跑通”的目标。

row split 和手工 tensor split 后面都试了，确实不如 layer split 稳。

### 判断五：补丁只在证据足够时打

我没有一上来就改 bati.cpp。每个补丁都有可复现的错误：

- dtype fallback：转换脚本遇到 `F8_E8M0`。
- scheduler 上限：日志显示 `GGML_SCHED_MAX_SPLIT_INPUTS` 断言。
- concat 类型：日志显示 `concat.cu` 只接受 F32，但运行图需要其他类型。

这也是后续写博客和复现很重要的一点：补丁不是“玄学调参”，而是对具体失败点的最小修复。

## 当前可复现状态

模型：

```text
/data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-Q8_0-bati-local.gguf
```

运行脚本：

```text
/root/deepseek-v4-w7900d/scripts/run_server.sh
/root/deepseek-v4-w7900d/scripts/run_cli.sh
/root/deepseek-v4-w7900d/scripts/make_prompt.py
```

关键日志：

```text
/data/models/deepseek-v4-gguf/logs/convert-q8_0-full.log
/root/deepseek-v4-w7900d/results/cli-q8-4096-concat-patched.log
/root/deepseek-v4-w7900d/results/llama-server-q8.log
/root/deepseek-v4-w7900d/results/server-completion-test-background.json
```

benchmark：

```text
/root/deepseek-v4-w7900d/results/bench/llama-bench-layer-fa-b256-ub128-r3.jsonl
/root/deepseek-v4-w7900d/results/bench/llama-bench-layer-fa-b512-ub256-r2.jsonl
/root/deepseek-v4-w7900d/results/bench/llama-bench-layer-no-fa-b512-ub256-r2.jsonl
```

本地代码补丁：

```text
/root/bati.cpp/convert_hf_to_gguf.py
/root/bati.cpp/ggml/src/ggml-backend.cpp
/root/bati.cpp/ggml/src/ggml-cuda/concat.cu
```

## 后续优化方向

第一，做 Q4_K_M / Q3_K_M。现在 Q8_0 已经证明 runtime 能跑，下一步应该转换或下载 Q4/Q3 GGUF，重新跑同一套 benchmark。预期收益是显存余量更大、加载更快、可能允许更长 context 或更高并发。

第二，整理本地补丁。当前三个补丁能解决问题，但还不是上游质量的最终实现。尤其是 concat kernel 和 scheduler 上限，需要整理成更干净的 patch，最好加上类型检查和更小范围的条件。

第三，重新评估 row/tensor split。当前失败说明它们不是首发路线，但并不代表永远不可用。等 Q4/Q3 跑通后，可以用更低显存压力重新测试 `row`、`tensor-split`、不同 GPU 分配比例和更大的上下文。

第四，补并发 benchmark。当前主要是单请求 `llama-bench` 和 server smoke test。对外博客如果要描述服务能力，还需要补充 OpenAI-compatible endpoint 下的并发请求、TTFT、TPOT、吞吐和长上下文曲线。

第五，再回头看 vLLM。等 vLLM/ROCm 对 DeepSeek V4 的支持稳定后，再做同机对比会更公平。现在直接拿 vLLM 未成熟路径和 bati.cpp early access 路径比，结论容易被适配状态污染。

## 优化 Round 1 更新

上面五个方向已经逐项执行完一轮，实验记录在：

```text
/root/deepseek-v4-w7900d/deepseek-v4-flash-w7900d-optimization-round1.md
```

这一轮没有推翻原结论，反而把边界收得更清楚：本地 Q4_K_M requantize 不稳定，row/tensor split 不能替代 layer split，server 多 slot 目前会崩，vLLM nightly 仍缺可用的 ROCm MXFP4 MoE backend。因此现阶段对外文章应该把 Q8_0 + layer split 作为稳定基线，把 Q4/Q3 native GGUF、`-np > 1` 修复和 vLLM ROCm 后续支持作为优化路线图。

## 总结

这三个多小时真正解决的问题不是“写一个启动命令”，而是把一个不确定性很高的新模型部署任务拆成了几层：

```text
硬件确认
-> 框架路线筛选
-> 下载路径和本地权重选择
-> smoke 转换
-> 完整 GGUF 转换
-> runtime load
-> scheduler 修复
-> HIP kernel 修复
-> CLI 最小生成
-> llama-bench
-> server API
-> 技术文档
```

最后的结论也比较明确：8x W7900D 这类 PCIe 工作站卡可以跑 DeepSeek-V4-Flash，但首发路线要务实。当前最稳的是 bati.cpp/ROCm 的 GGUF 路线，layer split 是正确的起点；vLLM、SGLang、Ollama 都应该等 DeepSeek V4 支持更成熟后，再作为生产化和易用性方向继续推进。
