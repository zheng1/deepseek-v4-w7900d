#!/usr/bin/env python3
import argparse
import concurrent.futures
import json
import statistics
import time
from pathlib import Path

import requests


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
    return ordered[idx]


def post_completion(url: str, prompt: str, n_predict: int, timeout: float, request_id: int) -> dict:
    session = requests.Session()
    session.trust_env = False
    payload = {
        "prompt": prompt,
        "n_predict": n_predict,
        "temperature": 0,
        "cache_prompt": False,
    }
    started = time.perf_counter()
    try:
        response = session.post(url, json=payload, timeout=timeout)
        elapsed = time.perf_counter() - started
        try:
            body = response.json()
        except Exception:
            body = {"raw": response.text[:500]}
        return {
            "request_id": request_id,
            "ok": response.ok,
            "status_code": response.status_code,
            "elapsed_s": elapsed,
            "tokens_predicted": int(body.get("tokens_predicted") or body.get("completion_tokens") or 0),
            "tokens_evaluated": int(body.get("tokens_evaluated") or body.get("prompt_tokens") or 0),
            "content_prefix": str(body.get("content", ""))[:80],
            "timings": body.get("timings", {}),
        }
    except Exception as exc:
        elapsed = time.perf_counter() - started
        return {
            "request_id": request_id,
            "ok": False,
            "status_code": 0,
            "elapsed_s": elapsed,
            "tokens_predicted": 0,
            "tokens_evaluated": 0,
            "error": repr(exc),
        }


def run_case(url: str, prompt: str, concurrency: int, requests_total: int, n_predict: int, timeout: float) -> tuple[dict, list[dict]]:
    started = time.perf_counter()
    rows: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [
            pool.submit(post_completion, url, prompt, n_predict, timeout, i)
            for i in range(requests_total)
        ]
        for fut in concurrent.futures.as_completed(futures):
            row = fut.result()
            row["concurrency"] = concurrency
            rows.append(row)
    elapsed = time.perf_counter() - started
    ok_rows = [row for row in rows if row["ok"]]
    latencies = [row["elapsed_s"] for row in ok_rows]
    predicted = sum(row["tokens_predicted"] for row in ok_rows)
    evaluated = sum(row["tokens_evaluated"] for row in ok_rows)
    summary = {
        "concurrency": concurrency,
        "requests_total": requests_total,
        "requests_ok": len(ok_rows),
        "requests_failed": requests_total - len(ok_rows),
        "elapsed_s": elapsed,
        "request_per_s": len(ok_rows) / elapsed if elapsed else 0.0,
        "predicted_tokens": predicted,
        "evaluated_tokens": evaluated,
        "predicted_tok_s": predicted / elapsed if elapsed else 0.0,
        "latency_avg_s": statistics.mean(latencies) if latencies else 0.0,
        "latency_p50_s": percentile(latencies, 0.50),
        "latency_p95_s": percentile(latencies, 0.95),
        "latency_max_s": max(latencies) if latencies else 0.0,
    }
    return summary, sorted(rows, key=lambda row: row["request_id"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark llama-server /completion concurrency.")
    parser.add_argument("--url", default="http://127.0.0.1:8080/completion")
    parser.add_argument("--prompt-file", type=Path, default=Path("/root/deepseek-v4-w7900d/results/prompt-chat.txt"))
    parser.add_argument("--concurrency", default="1,2,4")
    parser.add_argument("--requests", type=int, default=8)
    parser.add_argument("--n-predict", type=int, default=32)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--out-jsonl", type=Path, default=Path("/root/deepseek-v4-w7900d/results/server-concurrency-bench.jsonl"))
    parser.add_argument("--summary-json", type=Path, default=Path("/root/deepseek-v4-w7900d/results/server-concurrency-summary.json"))
    args = parser.parse_args()

    prompt = args.prompt_file.read_text(encoding="utf-8")
    levels = [int(item) for item in args.concurrency.split(",") if item.strip()]
    args.out_jsonl.parent.mkdir(parents=True, exist_ok=True)

    summaries: list[dict] = []
    with args.out_jsonl.open("w", encoding="utf-8") as out:
        for level in levels:
            summary, rows = run_case(args.url, prompt, level, args.requests, args.n_predict, args.timeout)
            summaries.append(summary)
            print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
            for row in rows:
                out.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    args.summary_json.write_text(json.dumps(summaries, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

