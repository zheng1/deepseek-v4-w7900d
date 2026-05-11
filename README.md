# DeepSeek V4 Flash on 8 x AMD W7900D

这个仓库记录了一次比较完整的本地大模型部署实验：在一台 **8 x AMD Radeon PRO W7900D 48GB** 的 AMD 工作站上，把 **DeepSeek-V4-Flash** 跑起来、压测、调优，并把过程整理成技术博客和网页。

这件事最开始不是一个规整的 benchmark 项目，而是一个真实的工程问题：机器有了，显存也够，但我不想手工把 vLLM、SGLang、Ollama、llama.cpp、ROCm、多卡切分、不同量化方案全部试一遍。于是我把任务交给 Codex 长时间执行，中间再把 Hermes/GPT-5.5 的外部调研结论喂给它，让它继续在机器上编译、改代码、跑服务和压测。

## 当前结论

在这台机器上，当前最合适的路线是：

```text
DeepSeek-V4-Flash
  -> GGUF
  -> bati.cpp / llama.cpp ROCm-HIP
  -> layer split 多卡切分
  -> llama-server OpenAI-compatible API
```

最推荐的服务方案是：

```text
DeepSeek-V4-Flash-MXFP4_MOE-requant-from-Q8_0.gguf
8 x W7900D
ROCm / HIP
split mode = layer
llama-server / OpenAI-compatible /v1/completions
```

不建议把这台机器的首发路线放在官方 V4-Pro + vLLM ROCm 上。显存总量看起来够，但 W7900D 是 PCIe 工作站卡，不是 MI300X/MI325X 这类 Instinct 训练/推理卡；现阶段 DeepSeek V4 在 vLLM/ROCm 上更偏适配路线，不如 GGUF + llama.cpp/bati.cpp 稳。

## 主要内容

- [主博客 Markdown：把 DeepSeek-V4-Flash 跑上 8 张 W7900D](./deepseek-v4-flash-w7900d-agent-blog.md)
- [早期博客草稿：DeepSeek-V4-Flash W7900D Codex Story](./deepseek-v4-flash-w7900d-codex-story-blog-deepseek-v4-pro.md)
- [网页版本入口](./docs/index.html)
- [llama.cpp / ROCm 部署记录](./deepseek-v4-flash-w7900d-llamacpp-rocm.md)
- [vLLM benchmark 记录](./deepseek-v4-flash-w7900d-vllm-benchmark.md)
- [第一轮优化记录](./deepseek-v4-flash-w7900d-optimization-round1.md)
- [低比特量化实验记录](./deepseek-v4-flash-w7900d-lowbit-round2.md)
- [agent 操作复盘](./deepseek-v4-flash-w7900d-agent-retrospective.md)

## 性能摘要

这批结果主要使用 vLLM/SGLang 风格的 OpenAI benchmark 压测脚本，对 `llama-server` 的 OpenAI-compatible endpoint 做请求压测。

典型 prefill 测试：

```text
input = 1024 tokens
output = 1 token
concurrency = 32
num_prompts = 100
ctx = 131072
```

实验过程中验证了：

- `Q8_0` 能跑，但显存压力和吞吐都不理想。
- `Q4_K_M` 质量更稳，但不一定是这套服务路径下最快。
- `Q3_K_M` / `Q2_K` 可作为更轻的对照组。
- `MXFP4_MOE` 是当前综合表现最好的方案。
- `layer split` 比 `tensor split` 更适合这台 8 卡 PCIe 工作站。
- 多 slot / 并发压测会暴露 DeepSeek V4 的 KV cache 路径问题，需要 unified KV 相关修复。

图表在网页里是 inline SVG，也单独保存在：

```text
docs/assets/
site/assets/
```

## 启动方式

本机实验用的服务脚本：

```bash
./scripts/run_server_mxfp4_moe.sh
```

健康检查：

```bash
curl --noproxy '*' http://127.0.0.1:8080/health
```

benchmark 脚本：

```bash
./scripts/run_vllm_bench_openai.sh
```

注意：这些脚本里的模型路径和 ROCm 环境变量是按这台机器写的，迁移到其他机器时需要改模型路径、GPU 可见设备和 batch/context 参数。

## 相关 PR

这次实验过程中产生了两个上游 PR：

- bati.cpp: <https://github.com/batiai/bati.cpp/pull/1>
  - 修 DeepSeek V4 multi-slot 并发下的 KV cache 问题。
  - 让 DeepSeek V4 路径使用 unified KV，避免多 slot 压测崩溃。

- ds4: <https://github.com/antirez/ds4/pull/69>
  - 修 Linux CPU build/runtime 边界。
  - 让 Linux 下可以编译、inspect、tokenize，并明确非 Metal server 不可用。
  - 补下载脚本和文档，避免把 `.aria2` 半成品误判成完整模型。

## 仓库结构

```text
.
├── deepseek-v4-flash-w7900d-*.md   # 分阶段技术记录和博客草稿
├── docs/                           # GitHub Pages 静态网页
├── site/                           # 原始网页输出
├── scripts/                        # 启动、压测、渲染脚本
├── results/                        # benchmark 和服务日志摘要
└── patches/                        # 本地修改补丁记录
```

## 说明

这个仓库不是通用安装包，也不包含模型权重。它更像是一份工程现场记录：包括尝试过的路线、踩过的坑、最后采用的方案、benchmark 数据和后续优化方向。
