#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

const outDir = process.argv[2] || "/root/deepseek-v4-w7900d/site/assets";

const colors = {
  bg: "#fffdf7",
  paper: "#fffefa",
  ink: "#202124",
  muted: "#62665f",
  line: "#d9d5c8",
  grid: "#ebe6d9",
  mxfp4: "#0d6f68",
  q8: "#284e7a",
  q2: "#b1841f",
  q3: "#6f5b2e",
  q4: "#ad4f2f",
};

function esc(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function fmt(value, digits = 2) {
  return value.toFixed(digits).replace(/\.?0+$/, "");
}

function modelColor(model) {
  if (model === "MXFP4_MOE") return colors.mxfp4;
  if (model === "Q8_0") return colors.q8;
  if (model === "Q2_K") return colors.q2;
  if (model === "Q3_K_M") return colors.q3;
  return colors.q4;
}

function renderPanel({ x, y, width, title, subtitle, rows, unit, digits = 2, lowerIsBetter = false }) {
  const labelW = 170;
  const valueW = 108;
  const gap = 16;
  const barX = x + labelW + gap;
  const barW = width - labelW - valueW - gap * 2;
  const rowH = 44;
  const max = Math.max(...rows.map((row) => row.value));
  const chartY = y + 86;
  const panelH = 108 + rows.length * rowH;
  const axis = [0.25, 0.5, 0.75, 1];

  const grid = axis.map((ratio) => {
    const gx = barX + barW * ratio;
    return `<line x1="${gx}" y1="${chartY - 10}" x2="${gx}" y2="${chartY + rows.length * rowH - 10}" stroke="${colors.grid}" stroke-width="1"/>`;
  }).join("");

  const body = rows.map((row, index) => {
    const rowY = chartY + index * rowH;
    const barWValue = Math.max(8, (row.value / max) * barW);
    const color = row.color || modelColor(row.label);
    const value = `${fmt(row.value, digits)}${unit}`;
    return `
      <g>
        <circle cx="${x + 8}" cy="${rowY + 14}" r="5" fill="${color}"/>
        <text x="${x + 20}" y="${rowY + 19}" font-size="17" fill="${colors.ink}">${esc(row.label)}</text>
        <rect x="${barX}" y="${rowY}" width="${barW}" height="26" rx="5" fill="#f0ecdf"/>
        <rect x="${barX}" y="${rowY}" width="${barWValue}" height="26" rx="5" fill="${color}"/>
        <text x="${barX + barW + 16}" y="${rowY + 19}" font-size="17" font-weight="700" fill="${colors.ink}">${esc(value)}</text>
      </g>`;
  }).join("");

  return `
    <g transform="translate(0,0)">
      <rect x="${x - 24}" y="${y}" width="${width + 48}" height="${panelH}" rx="12" fill="${colors.paper}" stroke="${colors.line}"/>
      <text x="${x}" y="${y + 34}" font-size="25" font-weight="800" fill="${colors.ink}">${esc(title)}</text>
      <text x="${x}" y="${y + 62}" font-size="16" fill="${colors.muted}">${esc(subtitle)}${lowerIsBetter ? "，越短越好" : "，越高越好"}</text>
      ${grid}
      ${body}
    </g>`;
}

function renderChart({ file, title, subtitle, panels, width = 1200 }) {
  const panelWidth = width - 140;
  const panelGap = 28;
  let y = 120;
  const renderedPanels = panels.map((panel) => {
    const panelSvg = renderPanel({ ...panel, x: 70, y, width: panelWidth });
    y += 108 + panel.rows.length * 44 + panelGap;
    return panelSvg;
  }).join("");
  const height = y + 36;

  const svg = `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(title)}">
  <rect width="100%" height="100%" fill="${colors.bg}"/>
  <text x="60" y="58" font-size="34" font-weight="850" fill="${colors.ink}">${esc(title)}</text>
  <text x="60" y="88" font-size="17" fill="${colors.muted}">${esc(subtitle)}</text>
  ${renderedPanels}
</svg>
`;

  fs.writeFileSync(path.join(outDir, file), svg);
}

fs.mkdirSync(outDir, { recursive: true });

const llamaPrefill = [
  { label: "MXFP4_MOE", value: 118.04 },
  { label: "Q8_0", value: 115.66 },
  { label: "Q2_K", value: 102.69 },
  { label: "Q3_K_M", value: 95.18 },
  { label: "native Q4_K_M", value: 94.49 },
];
const llamaDecode = [
  { label: "MXFP4_MOE", value: 9.52 },
  { label: "Q8_0", value: 9.22 },
  { label: "Q2_K", value: 9.12 },
  { label: "Q3_K_M", value: 8.98 },
  { label: "native Q4_K_M", value: 8.76 },
];
const out128 = [
  { label: "MXFP4_MOE", value: 6.89 },
  { label: "Q8_0", value: 6.82 },
  { label: "Q2_K", value: 6.67 },
  { label: "Q3_K_M", value: 6.47 },
  { label: "native Q4_K_M", value: 6.36 },
];
const out1024 = [
  { label: "MXFP4_MOE", value: 4.54 },
  { label: "Q8_0", value: 4.42 },
  { label: "Q3_K_M", value: 4.09 },
  { label: "native Q4_K_M", value: 3.91 },
];
const out4096 = [
  { label: "MXFP4_MOE", value: 1.19 },
  { label: "Q8_0", value: 1.17 },
  { label: "native Q4_K_M", value: 0.97 },
];
const ttft128 = [
  { label: "Q8_0", value: 1.67 },
  { label: "MXFP4_MOE", value: 1.77 },
  { label: "Q3_K_M", value: 2.04 },
  { label: "native Q4_K_M", value: 2.04 },
  { label: "Q2_K", value: 2.06 },
];
const ttft1024 = [
  { label: "MXFP4_MOE", value: 12.65 },
  { label: "Q8_0", value: 12.82 },
  { label: "Q3_K_M", value: 15.12 },
  { label: "native Q4_K_M", value: 15.83 },
];
const ttft4096 = [
  { label: "MXFP4_MOE", value: 45.34 },
  { label: "Q8_0", value: 46.14 },
  { label: "native Q4_K_M", value: 56.98 },
];
const c4Output = [
  { label: "MXFP4_MOE", value: 6.97 },
  { label: "Q8_0", value: 6.66 },
  { label: "native Q4_K_M", value: 6.40 },
];
const c4Ttft = [
  { label: "MXFP4_MOE", value: 25.79 },
  { label: "Q8_0", value: 26.98 },
  { label: "native Q4_K_M", value: 28.14 },
];
const prefillServingThroughput = [
  { label: "c32 / n100", value: 76.44, color: colors.mxfp4 },
  { label: "c1 / n10", value: 72.47, color: colors.q8 },
];
const prefillServingTtft = [
  { label: "c1 / n10", value: 14.14, color: colors.q8 },
  { label: "c32 / n100", value: 361.47, color: colors.mxfp4 },
];
const prefillNp4Throughput = [
  { label: "c1 / n8", value: 86.09, color: colors.mxfp4 },
  { label: "c2 / n12", value: 84.91, color: colors.q8 },
  { label: "c4 / n16", value: 81.90, color: colors.q4 },
  { label: "b2048 c1", value: 46.85, color: colors.gold },
];
const prefillNp4Ttft = [
  { label: "c1 / n8", value: 11.91, color: colors.mxfp4 },
  { label: "c2 / n12", value: 23.52, color: colors.q8 },
  { label: "c4 / n16", value: 46.79, color: colors.q4 },
  { label: "b2048 c1", value: 21.88, color: colors.gold },
];

renderChart({
  file: "chart-llama-bench.svg",
  title: "llama-bench：prefill 和 decode",
  subtitle: "统一参数：layer split / batch 512 / ubatch 256 / f16 KV cache",
  panels: [
    { title: "Prefill p512", subtitle: "一次吃 512 token prompt", rows: llamaPrefill, unit: " tok/s" },
    { title: "Decode n64", subtitle: "连续生成 64 token", rows: llamaDecode, unit: " tok/s" },
  ],
});

renderChart({
  file: "chart-serving-output.svg",
  title: "vLLM benchmark client：输出吞吐",
  subtitle: "vLLM 只做压测客户端，后端是 bati.cpp/llama-server",
  panels: [
    { title: "128 input / 64 output，c1", subtitle: "短请求单并发", rows: out128, unit: " tok/s" },
    { title: "1024 input / 128 output，c1", subtitle: "中等 prompt 单并发", rows: out1024, unit: " tok/s" },
    { title: "4096 input / 64 output，c1", subtitle: "4K prompt 单并发", rows: out4096, unit: " tok/s" },
  ],
});

renderChart({
  file: "chart-serving-ttft.svg",
  title: "vLLM benchmark client：Mean TTFT",
  subtitle: "首 token 延迟，主要反映 prefill 和排队时间",
  panels: [
    { title: "128 input / 64 output，c1", subtitle: "短请求单并发", rows: ttft128, unit: "s", lowerIsBetter: true },
    { title: "1024 input / 128 output，c1", subtitle: "中等 prompt 单并发", rows: ttft1024, unit: "s", lowerIsBetter: true },
    { title: "4096 input / 64 output，c1", subtitle: "4K prompt 单并发", rows: ttft4096, unit: "s", lowerIsBetter: true },
  ],
});

renderChart({
  file: "chart-serving-c4.svg",
  title: "并发 4：早期单 slot 基线",
  subtitle: "这些是修 multi-slot 之前的 -np 1 数据，主要用来说明排队代价",
  panels: [
    { title: "128 input / 64 output，c4：输出吞吐", subtitle: "并发 4 时的 output throughput", rows: c4Output, unit: " tok/s" },
    { title: "128 input / 64 output，c4：Mean TTFT", subtitle: "排队后首 token 延迟会明显抬高", rows: c4Ttft, unit: "s", lowerIsBetter: true },
  ],
});

renderChart({
  file: "chart-prefill-c32.svg",
  title: "Prefill 压测：1024 input / 1 output",
  subtitle: "ctx 128K，vLLM bench serve；后端 -np 1，所以并发主要压出队列和持续吞吐",
  panels: [
    { title: "Total token throughput", subtitle: "总 token 吞吐，基本就是 prefill 吞吐", rows: prefillServingThroughput, unit: " tok/s" },
    { title: "Mean TTFT", subtitle: "首 token 延迟，并发 32 时主要是排队时间", rows: prefillServingTtft, unit: "s", lowerIsBetter: true },
  ],
});

renderChart({
  file: "chart-prefill-np4.svg",
  title: "Prefill 压测：修复后的 -np 4",
  subtitle: "1024 input / 1 output，ctx 16K，cache off；并发能稳定跑，但吞吐没有线性增长",
  panels: [
    { title: "Total token throughput", subtitle: "总 token 吞吐，基本就是 prefill 吞吐", rows: prefillNp4Throughput, unit: " tok/s" },
    { title: "Mean TTFT", subtitle: "首 token 延迟；c4 更高，b2048 是退化参数", rows: prefillNp4Ttft, unit: "s", lowerIsBetter: true },
  ],
});

console.log(`wrote charts to ${outDir}`);
