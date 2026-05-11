# 把 DeepSeek-V4-Flash 跑上 8 张 W7900D：一次让 Codex 接管机器的实验

> 机器：8 x AMD Radeon PRO W7900D 48GB
> 显存：384GB
> 最后留下来的路线：bati.cpp / llama.cpp ROCm + GGUF + layer split
> 推荐模型：DeepSeek-V4-Flash MXFP4_MOE
> 服务接口：OpenAI-compatible `/v1/completions`

我最近拿到一台挺少见的机器：8 张 AMD Radeon PRO W7900D，每张 48GB。

384GB 显存摆在那儿，第一反应当然是：这不跑个 DeepSeek-V4-Flash 说不过去。

然后问题就来了。显存够，和能舒服地跑起来，中间差了很多小时的脏活。

如果这是 8 张 MI300X，我大概率先照着 vLLM 的 AMD recipe 抄作业。如果是 CUDA 机器，社区答案也会多很多。但 W7900D 是 RDNA3 工作站卡，ROCm 能用，生态没有 Instinct 那么顺。很多问题看起来只差一小步：

- vLLM 到底支不支持 DeepSeek V4 的 ROCm 路径？
- SGLang 有没有更省事？
- Ollama 页面上写了 DeepSeek-V4-Flash，拉下来是不是就完事？
- llama.cpp 主线、社区分支、bati.cpp fork，谁能跑，谁只是看起来能跑？
- 8 张 PCIe 卡到底该 layer split，还是 tensor split？
- Q2、Q3、Q4、Q8、MXFP4，哪个不是纸面最美，而是真的适合这台机器？

这些问题单独看都不吓人。合在一起就烦了。

烦点不在命令多，而在每条路都像是“快通了”。你再追半小时，发现缺的是 ROCm kernel。再追一小时，发现是 KV cache。再追两小时，发现这个 GGUF layout 根本不是那个 runner 要的 layout。

所以我干了一件偷懒但有效的事：把机器交给 Codex，让它自己试。

## 结论先放这

这台机器可以跑 DeepSeek-V4-Flash。

我现在会这样跑：

```text
DeepSeek-V4-Flash
  -> GGUF
  -> bati.cpp / llama.cpp ROCm-HIP
  -> layer split
  -> llama-server OpenAI-compatible API
```

最后留下来的模型文件是：

```text
DeepSeek-V4-Flash-MXFP4_MOE-requant-from-Q8_0.gguf
```

启动脚本：

```bash
/root/deepseek-v4-w7900d/scripts/run_server_mxfp4_moe.sh
```

健康检查：

```bash
curl --noproxy '*' http://127.0.0.1:8080/health
```

返回：

```json
{"status":"ok"}
```

这不是“官方推荐最佳实践”。也不是那种拿来就能复制到任何机器上的教程。它更像这台具体机器上的工程答案：能跑，能压测，能接 agent，坏了还能继续改。

## 我一开始也不知道答案

我给 Codex 的第一条有效指令很粗暴：我要去睡觉了，你先研究。一条路不通就搜，再换路，直到跑起来。

这个任务很适合看 agent 的长处和短处。

Codex 在本机执行上很强。查显卡、装依赖、编译、读日志、改 C++、起 server、跑 benchmark，这些它能一直做下去。它不嫌烦。

但它自己搜资料时不总靠谱。DeepSeek V4 这种刚出来的新模型，信息散在 ModelScope、Hugging Face、GitHub issue、ROCm 文档和各种 fork 里。只让一个 agent 闷头搜，很容易在一条不该走的路上越走越远。

所以我又开了 Hermes，让它接 GPT-5.5 做外部调研。Hermes 的判断更像“先别急着敲命令，我们看看这台机器到底像什么”：W7900D 不是 Instinct，vLLM 的 DeepSeek V4 Pro recipe 更偏 MI300X/MI325X，DeepSeek V4 的 ROCm quantization 支持还在补。对这台 PCIe 工作站来说，V4-Flash + GGUF + layer split 更现实。

分工到这里就清楚了：

| 角色 | 它更擅长什么 | 这次实际做了什么 |
| --- | --- | --- |
| Hermes / GPT-5.5 | 外部资料、路线判断 | 把方向从 vLLM/Pro 拉回 V4-Flash + GGUF |
| Codex | 本机执行、编译、改代码、压测 | 把服务跑起来，把 benchmark 跑完 |
| Pi | 模拟下游 agent 使用 | 通过 OpenAI tools 接本地模型，顺手审稿 |

有点像一个很小的工程小组。一个人查资料，一个人上机器，一个人当用户。只是这三位都不是人。

## 先排掉几条看起来很香的路

vLLM 是我最想用的。它有标准 benchmark，拿出去也好和别人对比。

问题是，这台机器不是 vLLM AMD recipe 里最舒服的硬件。DeepSeek V4 在 ROCm 上的支持也还在变。V4-Pro 官方形态更夸张，明显不是给 8 x 48GB W7900D 这种配置准备的。

SGLang 也试了。没有比 vLLM 更稳。

Ollama 页面上有 DeepSeek-V4-Flash。这个最容易让人心动，因为命令看起来最短。但对这次实验来说，Ollama 太黑盒了。我要的是能解释性能、能改参数、能查日志、能跑多卡 benchmark 的服务，不是“能聊两句就行”。

ds4 也很有意思。antirez 写了一个 DeepSeek V4 Flash 专用引擎，主要面向 Mac / Metal，设计很硬核。但这台机器是 AMD ROCm，不是 Metal。最后我给 ds4 提了一个 Linux PR，让它至少能在 Linux 上编译、inspect、tokenize，并把非 Metal server 的失败说清楚。它不是这台机器的生产路线。

跑通的是 bati.cpp / llama.cpp ROCm。

## 为什么不是 tensor split

8 张 W7900D 看起来很豪华。384GB 显存也确实够大。

但多卡推理不是把显存加起来就完事。互联很要命。

这台机器是 PCIe 工作站卡，不是 NVLink，也不是 MI300X 那类为大模型推理准备的系统。tensor split 会吃更多卡间通信，在这套硬件上容易把互联问题放大。

layer split 粗糙一点：按层切，GPU 0 跑一段，GPU 1 跑一段，继续往后传。它不优雅，但稳定，尤其适合这种“显存够、互联一般”的机器。

最后服务参数大致长这样：

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

几个参数后来反复调：

- `-sm layer`：多卡按层切。
- `-c`：上下文长度，先稳住 16K，再测 64K、128K、1M。
- `-b` / `-ub`：batch 和 micro-batch。太小喂不饱，太大容易炸。
- `-np`：server slot 数。要测并发，这个绕不开。
- `GGML_HIP_NO_VMM=1`：这类 consumer/workstation ROCm 环境下更稳。

## benchmark 不能只跑一个请求

我一开始也犯了一个很常见的错：用很少的请求测 prefill。

这样能快速知道服务活着没，但测不出机器上限。更糟的是，它会给你一种“性能还行”的错觉。

后来改成更像标准压测的方式：

```text
input = 1024
output = 1
num_prompts = 100
concurrency = 32
```

`output=1` 是为了尽量把 decode 的影响拿掉。`concurrency=32` 是为了看 server 在多请求下怎么排队、怎么分 slot、怎么处理 KV cache。

这一步直接把问题打出来了：DeepSeek V4 的 multi-slot 路径会触发 KV cache 问题。单请求能跑，不代表并发能跑。

于是我改了 bati.cpp，让 DeepSeek V4 多 slot 走 unified KV，并提了 PR：

```text
https://github.com/batiai/bati.cpp/pull/1
```

这不是那种看起来很酷的优化。它的价值很朴素：没有它，多并发压测会先崩，后面就没法谈性能。

## 数字

先看 llama-bench。统一参数是 layer split、batch 512、ubatch 256、f16 KV cache。

![llama-bench prefill 和 decode](assets/chart-llama-bench.svg)

| 模型 | Prefill p512 | Decode n64 |
| --- | ---: | ---: |
| MXFP4_MOE | 118.04 tok/s | 9.52 tok/s |
| Q8_0 | 115.66 tok/s | 9.22 tok/s |
| Q2_K | 102.69 tok/s | 9.12 tok/s |
| Q3_K_M | 95.18 tok/s | 8.98 tok/s |
| native Q4_K_M | 94.49 tok/s | 8.76 tok/s |

再看 serving benchmark。这里 vLLM 只是压测客户端，后端还是 bati.cpp / llama-server。

![serving 输出吞吐](assets/chart-serving-output.svg)

| 场景 | MXFP4_MOE | Q8_0 | native Q4_K_M |
| --- | ---: | ---: | ---: |
| 128 input / 64 output | 6.89 tok/s | 6.82 tok/s | 6.36 tok/s |
| 1024 input / 128 output | 4.54 tok/s | 4.42 tok/s | 3.91 tok/s |
| 4096 input / 64 output | 1.19 tok/s | 1.17 tok/s | 0.97 tok/s |

TTFT 也得看。尤其是并发场景，平均 TTFT 里混着 prefill 时间和排队时间，不能只当模型速度看。

![serving TTFT](assets/chart-serving-ttft.svg)

prefill 专项测试里，`ctx=131072`、`input=1024`、`output=1`。单并发和 32 并发看的是两件事：

![prefill c32](assets/chart-prefill-c32.svg)

| 场景 | 请求数 | 并发 | 总吞吐 |
| --- | ---: | ---: | ---: |
| c1 / n10 | 10 | 1 | 72.47 tok/s |
| c32 / n100 | 100 | 32 | 76.44 tok/s |

并发 32 没有把吞吐打到很夸张，说明瓶颈不是“请求太少没喂饱”这么简单。但这个测试有价值，因为它证明了服务在多请求排队下能活下来。

说实话，这比一个漂亮的单请求数字更有用。

## 为什么 MXFP4_MOE 赢了

我原本以为 native Q4_K_M 会是甜点位。结果不是。

Q8_0 稳，但太重。Q2_K 小，但不一定快。native Q4_K_M 看着平衡，实际在这台机器上没跑赢 MXFP4_MOE。

原因大概率在 DeepSeek V4 Flash 的 MoE 结构。

MoE 模型的大量参数在 routed experts 里，但每个 token 只激活一部分专家。MXFP4_MOE 不是把全模型粗暴压低精度，而是重点处理 experts，同时保留一些对数值更敏感的投影、路由和输出部分。

这正好对上了这台机器的瓶颈：

- 权重读取压力降下来了。
- routed experts 占空间大，压它们更划算。
- 路由和输出保留更高精度，少一点奇怪的数值问题。
- layer split 下，每张卡负责一段层，低比特 experts 能减轻每段的带宽压力。

所以这次不是“低比特一定更快”。更准确地说，是 MXFP4_MOE 刚好贴着 DeepSeek V4 Flash 的结构切了一刀。

## 长上下文别一口气开到 1M

DeepSeek V4 号称 1M context。这台机器也确实试过 64K、128K 和 1M。

但我不会把 1M 当默认配置。

长上下文会把很多问题一起放大：KV cache、slot 数、batch、显存碎片、cache 策略、多卡协作。16K 稳，不代表 128K 稳。128K 能跑，也不代表 1M 适合日常服务。

比较稳的顺序是：

```text
16K -> 64K -> 128K -> 1M
```

每一步都用同一组 benchmark 去测：

```text
input = 1024
output = 1
concurrency = 1 / 4 / 32
num_prompts = 10 / 100
```

直接喊“支持 1M”没什么意思。能不能在 1M 下稳定服务，才是另一回事。

## 模型能聊天，不等于能接 agent

服务跑起来以后，我又试了 agent 工作流。

Claude Code 当时没顺利走通 Anthropic 接口。于是我换 Pi，因为 Pi 可以走 OpenAI tools，和 llama-server 的 OpenAI-compatible API 更贴。

我写了一个小 proxy，把本地模型接到 Pi REPL。这样 Pi 可以通过工具读写文件、审稿、改文章。它不是很优雅，但能说明问题。

“能聊天”和“能当 coding agent 用”差很多。agent 会逼出另一批问题：

- tool call 格式是不是稳定；
- 上下文长了以后还能不能跟住任务；
- 本地 `127.0.0.1` 请求会不会被代理环境变量坑到；
- streaming、超时、`max_tokens`、错误恢复能不能忍；
- 生成慢的时候，REPL 体验是不是还像个人能用的东西。

这一步的结论是：可以用，但还需要包装。模型服务只是底座，agent 体验要靠 proxy、工具协议、超时和上下文裁剪一起撑。

## 顺手提了两个 PR

这次有两处改动适合回到上游。

第一个是 bati.cpp：

```text
https://github.com/batiai/bati.cpp/pull/1
```

修 DeepSeek V4 multi-slot 并发下的 KV cache 问题。没有它，prefill 并发压测很难稳定跑完。

第二个是 ds4：

```text
https://github.com/antirez/ds4/pull/69
```

ds4 是 Metal-first，不是这台 AMD 机器的生产方案。但它的 Linux 边界可以说清楚。我做了这些：

- Linux 下能编译；
- 非 Metal 默认 CPU backend；
- `--inspect` 和 tokenizer 诊断能跑；
- `ds4-server` 在非 Metal 下明确报错；
- 下载脚本支持把 GGUF 放到 `/data`，并避免把 `.aria2` 半成品当完整模型。

这种 PR 不会改变什么大方向，但能让下一个人少浪费几个小时。

## 这次我会记住的事

agent 很适合做多路线试错。

人最烦的是重复：换参数、编译、跑日志、查错误、再换参数。Codex 不烦。只要目标足够明确，它可以干很久。

但 agent 也会走偏。

新模型、新框架、新硬件搅在一起时，外部资料经常缺半截。只让一个 agent 自己搜，很容易在错误路线上越跑越远。Hermes/GPT-5.5 这次最大的价值，就是把路线校准到了 W7900D + GGUF + layer split。

benchmark 也要像工程测试，别像截图。

一个请求测出来的数字，最多证明服务没死。真正有用的是固定参数、保存日志、保存 JSON、记录失败、重复跑，并且把 benchmark client 和 server 配置都写清楚。

还有，低比特不是越低越快。

这次最舒服的点不是 Q2，也不是 native Q4，而是 MXFP4_MOE。它贴合模型结构，也贴合这台机器的带宽和互联情况。

最后，上下文窗口要一级一级开。1M context 是能力上限，不是默认配置。

## 如果重来一遍

我会直接按这个顺序做：

1. 先确认 ROCm、GPU 可见性、`rocminfo` 和 `rocm-smi`。
2. 准备 DeepSeek-V4-Flash 官方权重。
3. 用 bati.cpp / llama.cpp 路线转 GGUF。
4. 先跑 Q8_0 smoke test，确认模型结构和服务链路。
5. 转 MXFP4_MOE，作为主力方案。
6. 用 layer split 启 `llama-server`。
7. 用 vLLM benchmark client 测 OpenAI endpoint。
8. 先测 16K，再测 64K、128K。
9. 开 `-np` 和并发压测，修 multi-slot/KV 问题。
10. 最后接 Pi/Claude Code 这类 agent，看它能不能进入真实工作流。

这个顺序不浪漫，但省时间。

## 最后

这次最让我有点不适应的地方，不是 DeepSeek-V4-Flash 跑起来了。

而是我真的可以把一台 8 卡机器交给 Codex，让它在那里撞墙、读日志、改代码、跑 benchmark，然后第二天回来收结果。

这不等于人可以不用懂。正好相反，人得更清楚地知道怎么拆任务、什么时候打断、哪些路线该砍掉、哪些数字可信。

这台 8 x W7900D 最后跑起来了。Codex 做了很多脏活，Hermes 把方向拉正，Pi 验证了本地模型能不能进 agent 工作流。

接下来就没那么戏剧化了：继续调 kernel，继续修 KV cache，继续测长上下文，继续把这个服务从“能跑”磨到“好用”。
