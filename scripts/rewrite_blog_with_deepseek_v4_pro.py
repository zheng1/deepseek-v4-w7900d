#!/usr/bin/env python3
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path("/root/deepseek-v4-w7900d")
OUT_MD = ROOT / "deepseek-v4-flash-w7900d-codex-story-blog-deepseek-v4-pro.md"


SOURCE_FILES = [
    ("current-main-blog", ROOT / "deepseek-v4-flash-w7900d-codex-story-blog.md"),
    ("pi-rewrite-version", ROOT / "deepseek-v4-flash-w7900d-codex-story-blog-pi-rewrite.md"),
    ("vllm-benchmark-report", ROOT / "deepseek-v4-flash-w7900d-vllm-benchmark.md"),
    ("optimization-round1", ROOT / "deepseek-v4-flash-w7900d-optimization-round1.md"),
    ("lowbit-round2", ROOT / "deepseek-v4-flash-w7900d-lowbit-round2.md"),
    ("llamacpp-rocm-notes", ROOT / "deepseek-v4-flash-w7900d-llamacpp-rocm.md"),
    ("agent-retrospective", ROOT / "deepseek-v4-flash-w7900d-agent-retrospective.md"),
]


RESULT_FILES = [
    ROOT / "results/vllm-bench-mxfp4-moe-np4-c16384-prefill-cacheoff/random-i1024-o1-n8-c1.json",
    ROOT / "results/vllm-bench-mxfp4-moe-np4-c16384-prefill-cacheoff/random-i1024-o1-n12-c2.json",
    ROOT / "results/vllm-bench-mxfp4-moe-np4-c16384-prefill-cacheoff/random-i1024-o1-n16-c4.json",
    ROOT / "results/vllm-bench-mxfp4-moe-np4-c16384-prefill-b2048-ub512-ctxcp0/random-i1024-o1-n8-c1.json",
    ROOT / "results/vllm-bench-mxfp4-moe-c131072-prefill-c1-10/random-i1024-o1-n10-c1.json",
    ROOT / "results/vllm-bench-mxfp4-moe-c131072-prefill-c32-100/random-i1024-o1-n100-c32.json",
]


def read_text(path):
    if not path.exists():
        return f"[missing: {path}]"
    return path.read_text(encoding="utf-8", errors="replace")


def summarize_json(path):
    if not path.exists():
        return {"file": str(path), "missing": True}
    data = json.loads(path.read_text(encoding="utf-8"))
    keys = [
        "completed",
        "total_input_tokens",
        "total_output_tokens",
        "request_throughput",
        "total_token_throughput",
        "mean_ttft_ms",
        "median_ttft_ms",
        "p95_ttft_ms",
        "mean_tpot_ms",
        "p95_tpot_ms",
        "mean_e2el_ms",
        "p95_e2el_ms",
    ]
    return {"file": str(path), **{key: data.get(key) for key in keys}}


def build_context():
    result_summary = [summarize_json(path) for path in RESULT_FILES]
    file_sections = []
    for name, path in SOURCE_FILES:
        file_sections.append(
            f"\n\n# SOURCE: {name}\nPATH: {path}\n\n"
            f"{read_text(path)}"
        )

    fixed_facts = {
        "hardware": "8 x AMD Radeon PRO W7900D, 48GB each, 384GB total VRAM, RDNA3/gfx1100, PCIe workstation style interconnect.",
        "recommended_stack": "DeepSeek-V4-Flash GGUF on bati.cpp/llama.cpp ROCm, layer split across 8 GPUs.",
        "current_model": "/data/models/deepseek-v4-gguf/DeepSeek-V4-Flash-MXFP4_MOE-requant-from-Q8_0.gguf",
        "current_server": "-sm layer -ngl 99 -c 16384 -b 512 -ub 256 -fa on -fit off --no-op-offload --no-warmup -np 4 --cache-ram 0 --no-cache-idle-slots --no-cache-prompt --slot-prompt-similarity 0",
        "benchmark_tool": "vLLM is used only as benchmark client via vllm bench serve against /v1/completions. It is not the inference backend.",
        "multi_slot_fix": "DeepSeek4 multi-slot crashed because non-unified KV exposed a stream dimension such as [512,1,512,2] while code reshaped as [512,1,512]. Local bati.cpp fix auto-enables unified KV when DeepSeek4 n_seq_max > 1.",
        "best_prefill_current": "1024 input / 1 output, -np4 cache off, c1/n8: 86.09 total tok/s, mean TTFT 11.91s, p95 TTFT 12.94s.",
        "np4_concurrency_result": "c2/n12: 84.91 total tok/s, mean TTFT 23.52s. c4/n16: 81.90 total tok/s, mean TTFT 46.79s, p95 82.56s. No failures in this clean run.",
        "negative_tuning": "-b 2048 -ub 512 --ctx-checkpoints 0 regressed c1 prefill to 46.85 total tok/s.",
        "legacy_prefill": "old 128K context -np1 prefill: c1/n10 72.47 total tok/s, c32/n100 76.44 total tok/s but mean TTFT 361.47s at c32.",
        "chart_refs": [
            "assets/chart-llama-bench.svg",
            "assets/chart-serving-output.svg",
            "assets/chart-serving-ttft.svg",
            "assets/chart-serving-c4.svg",
            "assets/chart-prefill-c32.svg",
            "assets/chart-prefill-np4.svg",
        ],
    }

    return "\n".join(
        [
            "# CONTEXT PACKAGE FOR BLOG REWRITE",
            "",
            "## Fixed facts, do not alter numbers or claims",
            json.dumps(fixed_facts, ensure_ascii=False, indent=2),
            "",
            "## Latest benchmark JSON summaries",
            json.dumps(result_summary, ensure_ascii=False, indent=2),
            "",
            "## Source documents",
            "\n".join(file_sections),
        ]
    )


def call_deepseek(api_key, context):
    system = (
        "你是一位中文技术博客作者兼审稿编辑。你的任务是把一篇真实工程实验文章改写得更像中文技术圈里自然好读的博客："
        "专业、可信、口语化、有节奏，允许轻微幽默，但不要油腻、不要营销腔、不要把“接地气”这件事直接写出来。"
        "你必须严格保留技术事实、benchmark 数字、模型/命令/文件路径、失败路径和结论边界。"
        "不确定的原因只能写成猜测或可能原因，不能写成定论。"
    )
    user = (
        "请基于下面尽可能完整的上下文，输出一篇新的完整 Markdown 博客正文。\n\n"
        "写作要求：\n"
        "1. 标题和结构可以重写，但故事线要保留：用户拿到 8 张 W7900D，想把 DeepSeek-V4-Flash 跑起来，不想自己手工试；"
        "一开始把任务同时交给 Codex 和 Hermes，Hermes 调研更全面，用户把 Hermes 的判断喂给 Codex，Codex 负责在机器上执行、修 bug、跑 benchmark、写文章；"
        "后来还尝试了 Claude Code 和 Pi，把本地模型接入 agent 工作流。\n"
        "2. 语言更像自然中文博客，不要像报告，也不要每段都用“我们发现/我们认为”。\n"
        "3. 保留所有关键 benchmark 表格和图表引用。图表引用用 Markdown 图片语法，路径保持 assets/xxx.svg。\n"
        "4. 量化原理要讲清楚：Q8_0、Q2/Q3/Q4_K、MXFP4_MOE 大概是什么，为什么小模型不一定更快，为什么当前 MXFP4_MOE 可能更优。"
        "这里可以写推测，但要明确是推测。\n"
        "5. vLLM/SGLang/Ollama/llama.cpp/bati.cpp 的取舍要说人话，尤其说明 vLLM 在文中只是 benchmark client，不是推理 backend。\n"
        "6. 不要编造新数据；不要把 DeepSeek-V4-Pro 官方 API 和本机 DeepSeek-V4-Flash 推理混为一谈。\n"
        "7. 输出只要 Markdown 正文，不要解释你做了什么，不要用代码块包住整篇文章。\n\n"
        f"{context}"
    )

    payload = {
        "model": "deepseek-v4-pro",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.72,
        "top_p": 0.9,
        "max_tokens": 48000,
        "thinking": {"type": "disabled"},
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=1800) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DeepSeek API HTTP {exc.code}: {detail}") from exc


def main():
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        api_key = sys.stdin.readline().strip()
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY is required")

    context = build_context()
    print(f"context_chars={len(context)}", file=sys.stderr)
    start = time.time()
    response = call_deepseek(api_key, context)
    elapsed = time.time() - start
    message = response["choices"][0]["message"]
    content = message.get("content", "").strip()
    if not content:
        raise SystemExit(f"empty content from API: {json.dumps(response, ensure_ascii=False)[:2000]}")
    if content.startswith("```"):
        content = content.removeprefix("```markdown").removeprefix("```").strip()
        if content.endswith("```"):
            content = content[:-3].strip()

    OUT_MD.write_text(content + "\n", encoding="utf-8")
    usage = response.get("usage", {})
    print(f"wrote={OUT_MD}", file=sys.stderr)
    print(f"elapsed_sec={elapsed:.1f}", file=sys.stderr)
    print(f"usage={json.dumps(usage, ensure_ascii=False)}", file=sys.stderr)


if __name__ == "__main__":
    main()
