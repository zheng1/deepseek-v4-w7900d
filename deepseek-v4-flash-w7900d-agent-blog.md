# 把 DeepSeek-V4-Flash 跑上 8 张 W7900D：一次让 Codex 接管机器的实验

> 机器：8 x AMD Radeon PRO W7900D 48GB  
> 显存：384GB  
> 最终路线：bati.cpp / llama.cpp ROCm + GGUF + layer split  
> 当前推荐模型：DeepSeek-V4-Flash MXFP4_MOE  
> 服务接口：OpenAI-compatible `/v1/completions`

我最近拿到一台比较少见的机器：8 张 AMD Radeon PRO W7900D，每张 48GB，合计 384GB 显存。

这机器看起来很适合本地大模型。问题是，显存够不等于事情简单。

如果是 8 张 MI300X，可以先照着 vLLM 的 AMD recipe 往下走。如果是 CUDA，也大概率有更多现成答案。但 W7900D 是 RDNA3 工作站卡，ROCm 支持是有的，生态又没有 datacenter 卡那么顺。你很快会遇到一堆看似普通、实际很花时间的问题：

- vLLM 对 DeepSeek V4 的 ROCm 支持到哪一步了？
- SGLang 能不能直接用？
- Ollama 页面上有模型，实际是不是能跑？
- llama.cpp 主线、分支、社区 fork 到底差在哪？
- 8 张 PCIe 卡应该 layer split 还是 tensor split？
- Q2、Q3、Q4、Q8、MXFP4 哪个才是真正适合这台机器的点？

这些问题单独看都不难，合在一起就很烦。烦的地方不是命令多，而是每条路都像是“差一点就行”，然后你半夜三点发现它差的那一点叫 ROCm kernel、KV cache、GGUF layout 或者上下文分片。

所以我干了一件很偷懒的事：我把机器交给 Codex，让它自己试。

## 最后的结果

先说结论。

这台机器可以跑 DeepSeek-V4-Flash。当前我会把推荐路线定成：

```text
DeepSeek-V4-Flash
  -> GGUF
  -> bati.cpp / llama.cpp ROCm-HIP
  -> layer split
  -> llama-server OpenAI-compatible API
```

最终更推荐的模型文件是：

```text
DeepSeek-V4-Flash-MXFP4_MOE-requant-from-Q8_0.gguf
```

启动脚本是：

```bash
/root/deepseek-v4-w7900d/scripts/run_server_mxfp4_moe.sh
```

服务起来后就是普通的 OpenAI-compatible endpoint：

```bash
curl --noproxy '*' http://127.0.0.1:8080/health
```

返回：

```json
{"status":"ok"}
```

它不是全世界最快的 DeepSeek V4 部署，也不是最漂亮的官方路线。但它是这台 8 卡 W7900D 上当前最实用的路线：能跑，能压测，能接 agent，出了问题还能改。

## 我没有一开始就知道该怎么跑

最开始我给 Codex 的指令很粗暴：我要睡觉了，你先研究。一条路不通就搜索，再换路，直到跑起来。

这类任务很适合暴露 agent 的边界。

Codex 在本机执行上很强。它能查显卡、装依赖、编译、跑 server、读日志、改 C++，还会在 benchmark 结果不合理的时候继续追。

但 Codex 的外部检索不是一直可靠。DeepSeek V4 这种刚出来、生态还在变化的模型，信息散在 ModelScope、Hugging Face、GitHub issue、ROCm 文档、fork 分支里。只靠它自己搜，容易漏掉关键线索。

于是我又接了 Hermes，让它连 GPT-5.5 做外部调研。Hermes 给出的判断更像一个架构师：W7900D 不是 Instinct，vLLM 官方 Pro recipe 偏 MI300X/MI325X，DeepSeek V4 的 ROCm quantization 支持还在补，社区 GGUF + llama.cpp layer split 反而更适合 PCIe 工作站。

这时候分工就清楚了：

| Agent | 适合做什么 | 实际作用 |
| --- | --- | --- |
| Hermes / GPT-5.5 | 外部资料梳理、路线判断 | 把方向从 vLLM/Pro 拉回 V4-Flash + GGUF |
| Codex | 本机执行、编译、改代码、压测 | 真正把服务跑起来，把 benchmark 跑完 |
| Pi | 验证本地模型能不能接 agent 工作流 | 通过 OpenAI tools 调本地模型，反过来审稿 |

这个组合很像一个很小的工程团队。一个人查资料，一个人上机器，一个人模拟下游用户。区别是它们都不是人。

## 先把不合适的路排掉

第一批尝试不是最优解，而是排除法。

vLLM 是最自然的第一反应，因为它有标准 benchmark，也容易和别的厂商结果对比。但 DeepSeek V4 在 ROCm 上的支持当时还不够省心，尤其是这台机器不是 MI300X 这种官方 recipe 里反复出现的硬件。V4-Pro 的官方形态也明显不是给 8 x 48GB W7900D 准备的。

SGLang 也试了，但路线没有比 vLLM 更稳。

Ollama 页面上有 DeepSeek-V4-Flash，看起来很诱人。实际问题是，Ollama 对这种超大模型、多卡、ROCm、特殊量化和长上下文的组合不够透明。它适合“我就想本地拉个模型试试”，不适合这次这种要写 benchmark、要解释性能、要能持续调优的场景。

ds4 是另一个有意思的项目。它是 antirez 写的 DeepSeek V4 Flash 专用引擎，思路很激进，尤其是针对 Mac / Metal 做了很多专门优化。但这台机器是 AMD ROCm，不是 Apple Metal。最后我给 ds4 做了一个 Linux CPU build/runtime 边界修复 PR，让它在 Linux 上能编译、inspect、tokenize，并且把非 Metal server 的失败方式说清楚。但它不是这台 AMD 机器的生产路线。

真正跑起来的是 bati.cpp / llama.cpp ROCm 这条线。

## 为什么是 layer split

8 张 W7900D 的总显存很大，384GB。但多卡不只看总显存，还要看互联。

这不是 NVLink 机器，也不是 MI300X 那种专门为大模型推理准备的系统。W7900D 是 PCIe 工作站卡。tensor split 会更依赖卡间通信，理论上能降低部分延迟，但在这台机器上更容易把互联和 kernel 支持的问题放大。

layer split 更朴素：把模型层切到不同 GPU 上，按层往前跑。它不一定优雅，但对 PCIe 多卡更友好，也更容易稳定。

最后服务参数大致是这个方向：

```bash
HIP_VISIBLE_DEVICES=0,1,2,3,4,5,6,7 \
ROCR_VISIBLE_DEVICES=0,1,2,3,4,5,6,7 \
GGML_HIP_NO_VMM=1 \
./build-hip/bin/llama-server \
  -m /data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-MXFP4_MOE-requant-from-Q8_0.gguf \
  -sm layer \
  -ngl 99 \
  -c 16384 \
  -b 512 \
  -ub 256 \
  -fa on \
  --host 0.0.0.0 \
  --port 8080
```

这里有几个参数后来反复影响结果：

- `-sm layer`：多卡 layer split。
- `-c`：上下文长度，先从 16K 稳住，再测 64K、128K、1M。
- `-b` / `-ub`：batch 和 micro-batch，太激进会不稳，太保守吞吐上不去。
- `-np`：server slot 数，并发压测必须看这个。
- `GGML_HIP_NO_VMM=1`：consumer/workstation ROCm 场景下更现实。

## Benchmark 不能只测一个请求

最开始我做 prefill 测试时，用过很小的请求数。这个结果看起来不差，但没有把机器压满。

后来重新按更接近标准 benchmark 的方式测：

```text
input = 1024
output = 1
num_prompts = 100
concurrency = 32
```

这个设置更像在测 prefill 吞吐。`output=1` 基本把 decode 影响压到最低，`concurrency=32` 则能看出服务端排队、slot、batch 和 KV cache 的真实情况。

这时一个很实际的问题出现了：多 slot 会触发 DeepSeek V4 的 KV cache 路径问题。单请求能跑，不代表并发能跑。于是我又去改 bati.cpp，让 DeepSeek V4 多 slot 走 unified KV，最后提交了 PR：

```text
https://github.com/batiai/bati.cpp/pull/1
```

这个 PR 不是什么华丽优化，但很关键。没有它，多并发 benchmark 很容易变成“先崩了再说”。

## 数字

先看 llama-bench。统一参数是 layer split、batch 512、ubatch 256、f16 KV cache。

![llama-bench prefill 和 decode](assets/chart-llama-bench.svg)

核心结果：

| 模型 | Prefill p512 | Decode n64 |
| --- | ---: | ---: |
| MXFP4_MOE | 118.04 tok/s | 9.52 tok/s |
| Q8_0 | 115.66 tok/s | 9.22 tok/s |
| Q2_K | 102.69 tok/s | 9.12 tok/s |
| Q3_K_M | 95.18 tok/s | 8.98 tok/s |
| native Q4_K_M | 94.49 tok/s | 8.76 tok/s |

再看 serving benchmark。这里 vLLM 只是 benchmark client，真正的后端还是 bati.cpp / llama-server。

![serving 输出吞吐](assets/chart-serving-output.svg)

短请求下差距不大，但 MXFP4_MOE 基本都在前面：

| 场景 | MXFP4_MOE | Q8_0 | native Q4_K_M |
| --- | ---: | ---: | ---: |
| 128 input / 64 output | 6.89 tok/s | 6.82 tok/s | 6.36 tok/s |
| 1024 input / 128 output | 4.54 tok/s | 4.42 tok/s | 3.91 tok/s |
| 4096 input / 64 output | 1.19 tok/s | 1.17 tok/s | 0.97 tok/s |

TTFT 也要看。尤其是并发场景，平均 TTFT 不是单纯模型速度，还包括 slot 排队。

![serving TTFT](assets/chart-serving-ttft.svg)

prefill 专项测试里，`ctx=131072`、`input=1024`、`output=1` 时，单并发和 32 并发看到的是两种不同问题：

![prefill c32](assets/chart-prefill-c32.svg)

| 场景 | 请求数 | 并发 | 总吞吐 |
| --- | ---: | ---: | ---: |
| c1 / n10 | 10 | 1 | 72.47 tok/s |
| c32 / n100 | 100 | 32 | 76.44 tok/s |

吞吐没有因为并发 32 暴涨，说明瓶颈不是简单“请求太少没喂饱”。但 c32 能验证 server 在多请求排队下的稳定性，这个比单请求漂亮数字更重要。

## 为什么 MXFP4_MOE 反而更好

直觉上，Q4 应该比更低精度更稳，Q8 应该比 Q4 更慢但质量更好。但这次性能不是按“位数越高越慢、位数越低越快”简单排序。

关键在 DeepSeek V4 Flash 的结构。它是 MoE 模型，大量参数在 routed experts 里，不是每个 token 都激活全部专家。MXFP4_MOE 的思路是重点压 MoE experts，同时保留对质量和执行路径更敏感的部分。它不是把所有东西粗暴打到同一个低精度。

这有几个可能原因：

1. 更少的权重带宽压力。W7900D 的算力不是唯一瓶颈，权重搬运和多卡分层也很重要。
2. MoE experts 占空间大，但每 token 只走一部分，针对这部分做低比特更划算。
3. 一些投影、路由、输出层保留较高精度，减少质量损失，也减少奇怪的数值问题。
4. layer split 下，单卡负责一段层，低比特专家能降低每层权重读取压力。

所以 MXFP4_MOE 的优势不是“4 bit 魔法”，而是它更贴 DeepSeek V4 Flash 的结构。

## 长上下文：能开，不代表该一上来开

DeepSeek V4 号称 1M context。这台机器也确实尝试过 64K、128K 和 1M。

但我的结论比较保守：生产配置不要一上来就 1M。

长上下文主要吃 KV cache，也会把 server slot、batch、显存碎片、cache 策略和 PCIe 多卡协作的问题全部放大。16K 能稳，不代表 128K 能稳；128K 能跑，也不代表 1M 就适合日常服务。

更合理的顺序是：

```text
16K -> 64K -> 128K -> 1M
```

每一步都用同样的 benchmark 方式测：

```text
input = 1024
output = 1
concurrency = 1 / 4 / 32
num_prompts = 10 / 100
```

这比直接宣布“支持 1M”诚实得多。

## 让 agent 真的用上这个模型

服务跑起来还不够。我还想知道它能不能进入日常 agent 工作流。

Claude Code 当时没能顺利走通 Anthropic 接口，我又试了 Pi。Pi 可以走 OpenAI tools，这和 llama-server 的 OpenAI-compatible API 更贴。于是我写了一个很小的 proxy，把本地模型接到 Pi REPL，让它能通过工具读写文件、审稿、改文章。

这个验证很重要。因为很多模型“能聊天”和“能当 coding agent 用”是两件事。

对 agent 来说，真正麻烦的是：

- tool call 格式是否稳定；
- 上下文长了之后是否还能跟住任务；
- 本地代理会不会被系统代理环境变量坑到；
- streaming、超时、max_tokens、错误恢复是不是能接受；
- 生成慢的时候，REPL 体验是不是还能忍。

这一步的结论是：可以用，但还需要工程包装。模型服务只是底座，agent 体验还要靠 proxy、工具协议、超时和上下文裁剪一起撑。

## 顺手给上游提了两个 PR

这次不是只在本地堆脚本，也有一些可以回馈上游的改动。

第一个是 bati.cpp：

```text
https://github.com/batiai/bati.cpp/pull/1
```

修的是 DeepSeek V4 multi-slot 并发下的 KV cache 问题。没有这个修复，多并发 prefill benchmark 很难稳定跑完。

第二个是 ds4：

```text
https://github.com/antirez/ds4/pull/69
```

ds4 是 Metal-first 的项目，不适合这台 AMD 机器做生产推理。但它的 Linux build 边界可以更清楚。我做的事情是：

- Linux 下能编译；
- 非 Metal 默认 CPU backend；
- `--inspect` 和 tokenizer 诊断能跑；
- `ds4-server` 在非 Metal 下明确报错；
- 下载脚本支持把 GGUF 放到 `/data`，并避免把 `.aria2` 半成品当完整模型。

这类 PR 不会改变世界，但会让下一个人少浪费几个小时。

## 这次实验给我的经验

第一，agent 很适合做这种“多路线试错”的活。

人类最烦的是重复试：换镜像、换参数、编译、跑日志、找错误、再换一个参数。Codex 对这类事情很有耐心。只要你给它足够权限和明确目标，它可以连续干很久。

第二，agent 也会走偏。

尤其是新模型、新框架、新硬件交叉的时候，外部信息经常不完整。让一个 agent 只靠自己搜索，很容易在错误路线里越走越深。Hermes/GPT-5.5 那种外部调研角色很有价值，它帮我把方向校准到“W7900D + GGUF + layer split”。

第三，benchmark 要像工程测试，不要像截图。

只测一个请求，容易得到好看的数字。真正有用的是固定参数、保存日志、保存 JSON、记录失败、重复运行，并且把 benchmark client 和 server 配置都写清楚。

第四，低比特不是越低越快。

这次最好的点不是 Q2，也不是 native Q4，而是 MXFP4_MOE。原因很可能是它刚好贴合 DeepSeek V4 Flash 的 MoE 结构和这台机器的带宽/互联特性。

第五，上下文窗口要逐级开。

1M context 是能力上限，不是默认配置。先让 16K 稳，再上 64K、128K，最后再谈 1M，这样才不会把性能问题、稳定性问题和显存问题搅成一团。

## 如果现在重来一遍

我会直接按这个顺序做：

1. 确认 ROCm、GPU 可见性、`rocminfo` 和 `rocm-smi`。
2. 用 ModelScope/HF 准备 DeepSeek-V4-Flash 官方权重。
3. 用 bati.cpp / llama.cpp 路线转 GGUF。
4. 先跑 Q8_0 smoke test，确认模型结构和服务链路。
5. 转 MXFP4_MOE，作为主力方案。
6. 用 layer split 启 `llama-server`。
7. 用 vLLM benchmark client 测 OpenAI endpoint。
8. 先测 16K，再测 64K、128K。
9. 开 `-np` 和并发压测，修 multi-slot/KV 问题。
10. 最后接 Pi/Claude Code 这类 agent，看能不能进入真实工作流。

这比一上来追 vLLM Pro recipe、1M context、最高并发要稳得多。

## 结尾

这次实验最有意思的地方不是“DeepSeek-V4-Flash 能不能跑”，而是工作方式变了。

以前这种活要么自己熬夜试，要么等社区有人写完整教程。现在可以把机器交给 agent，让它去撞墙、读日志、换路线、写脚本、跑 benchmark、甚至整理文章。

但这不是“人不用懂了”。正好相反，人要更清楚地知道怎么拆任务、怎么判断路线、什么时候打断 agent、哪些数字可信、哪些结果只是偶然跑通。

这台 8 x W7900D 最后跑起来了。Codex 干了很多脏活，Hermes 帮忙把方向拉正，Pi 验证了本地模型能进入 agent 工作流。

剩下的事情就比较传统了：继续调 kernel，继续优化 KV cache，继续测更长上下文，继续把本地服务变成真正稳定的基础设施。

也就是说，故事刚从“能跑”进入“好用”。

