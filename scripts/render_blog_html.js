#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

const [inputPath, outputPath] = process.argv.slice(2);

if (!inputPath || !outputPath) {
  console.error("usage: render_blog_html.js input.md output.html");
  process.exit(2);
}

const markdown = fs.readFileSync(inputPath, "utf8");

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function inline(value) {
  let text = escapeHtml(value);
  text = text.replace(/`([^`]+)`/g, "<code>$1</code>");
  text = text.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  return text;
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("'", "&#39;");
}

function mimeTypeFor(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === ".svg") return "image/svg+xml";
  if (ext === ".png") return "image/png";
  if (ext === ".jpg" || ext === ".jpeg") return "image/jpeg";
  if (ext === ".webp") return "image/webp";
  if (ext === ".gif") return "image/gif";
  return "application/octet-stream";
}

function inlineImageSrc(src) {
  if (/^(?:https?:)?\/\//.test(src) || src.startsWith("data:")) {
    return src;
  }

  const candidates = [
    path.resolve(path.dirname(outputPath), src),
    path.resolve(path.dirname(inputPath), src),
  ];
  const filePath = candidates.find((candidate) => fs.existsSync(candidate));
  if (!filePath) {
    return src;
  }

  const data = fs.readFileSync(filePath);
  return `data:${mimeTypeFor(filePath)};base64,${data.toString("base64")}`;
}

function trimPipe(line) {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "");
}

function parseTable(lines, start) {
  const rows = [];
  let i = start;
  while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
    rows.push(trimPipe(lines[i]).split("|").map((cell) => cell.trim()));
    i += 1;
  }
  const header = rows[0] || [];
  const body = rows.slice(2);
  const html = [
    "<div class=\"table-wrap\"><table>",
    "<thead><tr>",
    ...header.map((cell) => `<th>${inline(cell)}</th>`),
    "</tr></thead>",
    "<tbody>",
    ...body.flatMap((row) => [
      "<tr>",
      ...row.map((cell) => `<td>${inline(cell)}</td>`),
      "</tr>",
    ]),
    "</tbody></table></div>",
  ].join("");
  return { html, next: i };
}

function formatNumber(value, digits = 2) {
  return value.toFixed(digits).replace(/\.?0+$/, "");
}

function renderBarChart({ title, subtitle, rows, unit, digits = 2 }) {
  const max = Math.max(...rows.map((row) => row.value));
  const bars = rows.map((row) => {
    const width = Math.max(2, (row.value / max) * 100);
    const label = escapeHtml(row.label);
    const value = `${formatNumber(row.value, digits)}${unit}`;
    return [
      `<div class="bar-row" style="--bar: ${row.color};">`,
      `<div class="bar-label"><span class="legend-dot"></span><span>${label}</span></div>`,
      `<div class="bar-track" aria-hidden="true"><div class="bar-fill" style="width: ${width.toFixed(2)}%;"></div></div>`,
      `<div class="bar-value">${value}</div>`,
      "</div>",
    ].join("");
  }).join("");

  return [
    "<section class=\"chart-panel\">",
    `<h3>${escapeHtml(title)}</h3>`,
    `<p>${escapeHtml(subtitle)}</p>`,
    `<div class="bar-chart" role="img" aria-label="${escapeHtml(title)}">`,
    bars,
    "</div>",
    "</section>",
  ].join("");
}

function renderPerformanceCharts() {
  const colors = {
    mxfp4: "#0d6f68",
    q8: "#284e7a",
    q2: "#b1841f",
    q3: "#6f5b2e",
    q4: "#ad4f2f",
  };
  const llamaPrefill = [
    { label: "MXFP4_MOE", value: 118.04, color: colors.mxfp4 },
    { label: "Q8_0", value: 115.66, color: colors.q8 },
    { label: "Q2_K", value: 102.69, color: colors.q2 },
    { label: "Q3_K_M", value: 95.18, color: colors.q3 },
    { label: "native Q4_K_M", value: 94.49, color: colors.q4 },
  ];
  const llamaDecode = [
    { label: "MXFP4_MOE", value: 9.52, color: colors.mxfp4 },
    { label: "Q8_0", value: 9.22, color: colors.q8 },
    { label: "Q2_K", value: 9.12, color: colors.q2 },
    { label: "Q3_K_M", value: 8.98, color: colors.q3 },
    { label: "native Q4_K_M", value: 8.76, color: colors.q4 },
  ];
  const serving128 = [
    { label: "MXFP4_MOE", value: 6.89, color: colors.mxfp4 },
    { label: "Q8_0", value: 6.82, color: colors.q8 },
    { label: "Q2_K", value: 6.67, color: colors.q2 },
    { label: "Q3_K_M", value: 6.47, color: colors.q3 },
    { label: "native Q4_K_M", value: 6.36, color: colors.q4 },
  ];
  const serving1024 = [
    { label: "MXFP4_MOE", value: 4.54, color: colors.mxfp4 },
    { label: "Q8_0", value: 4.42, color: colors.q8 },
    { label: "Q3_K_M", value: 4.09, color: colors.q3 },
    { label: "native Q4_K_M", value: 3.91, color: colors.q4 },
  ];
  const serving4096 = [
    { label: "MXFP4_MOE", value: 1.19, color: colors.mxfp4 },
    { label: "Q8_0", value: 1.17, color: colors.q8 },
    { label: "native Q4_K_M", value: 0.97, color: colors.q4 },
  ];
  const ttft128 = [
    { label: "Q8_0", value: 1.67, color: colors.q8 },
    { label: "MXFP4_MOE", value: 1.77, color: colors.mxfp4 },
    { label: "Q3_K_M", value: 2.04, color: colors.q3 },
    { label: "native Q4_K_M", value: 2.04, color: colors.q4 },
    { label: "Q2_K", value: 2.06, color: colors.q2 },
  ];
  const ttft1024 = [
    { label: "MXFP4_MOE", value: 12.65, color: colors.mxfp4 },
    { label: "Q8_0", value: 12.82, color: colors.q8 },
    { label: "Q3_K_M", value: 15.12, color: colors.q3 },
    { label: "native Q4_K_M", value: 15.83, color: colors.q4 },
  ];
  const ttft4096 = [
    { label: "MXFP4_MOE", value: 45.34, color: colors.mxfp4 },
    { label: "Q8_0", value: 46.14, color: colors.q8 },
    { label: "native Q4_K_M", value: 56.98, color: colors.q4 },
  ];

  return [
    "<div class=\"perf-charts\">",
    "<p class=\"chart-note\">先看图会直观很多：绿色的 MXFP4_MOE 基本一路领先，红色的 native Q4_K_M 虽然稳定，但这台机器上并没有跑出更高吞吐。</p>",
    "<div class=\"chart-grid two\">",
    renderBarChart({ title: "llama-bench Prefill", subtitle: "p512，越高越好，单位 tok/s", rows: llamaPrefill, unit: " tok/s" }),
    renderBarChart({ title: "llama-bench Decode", subtitle: "n64，越高越好，单位 tok/s", rows: llamaDecode, unit: " tok/s" }),
    "</div>",
    "<h3 class=\"chart-section-title\">Serving 输出吞吐</h3>",
    "<div class=\"chart-grid three\">",
    renderBarChart({ title: "128 / 64，c1", subtitle: "短请求单并发，越高越好", rows: serving128, unit: " tok/s" }),
    renderBarChart({ title: "1024 / 128，c1", subtitle: "长一点 prompt，越高越好", rows: serving1024, unit: " tok/s" }),
    renderBarChart({ title: "4096 / 64，c1", subtitle: "4K prompt，越高越好", rows: serving4096, unit: " tok/s" }),
    "</div>",
    "<h3 class=\"chart-section-title\">TTFT 延迟</h3>",
    "<p class=\"chart-note\">这一组是 Mean TTFT，越短越好。并发场景下的高 TTFT 主要来自 <code>-np 1</code> 单 slot 排队。</p>",
    "<div class=\"chart-grid three\">",
    renderBarChart({ title: "128 / 64，c1", subtitle: "短请求首 token 延迟，越低越好", rows: ttft128, unit: "s" }),
    renderBarChart({ title: "1024 / 128，c1", subtitle: "1024 token prompt 首 token 延迟，越低越好", rows: ttft1024, unit: "s" }),
    renderBarChart({ title: "4096 / 64，c1", subtitle: "4K prompt 首 token 延迟，越低越好", rows: ttft4096, unit: "s" }),
    "</div>",
    "</div>",
  ].join("");
}

function renderBlocks(source) {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const html = [];
  const toc = [];
  const slugCounts = new Map();

  function slugFor(title) {
    const base = title
      .toLowerCase()
      .replace(/`/g, "")
      .replace(/[^\p{L}\p{N}]+/gu, "-")
      .replace(/^-+|-+$/g, "") || "section";
    const count = (slugCounts.get(base) || 0) + 1;
    slugCounts.set(base, count);
    return count === 1 ? base : `${base}-${count}`;
  }

  function collectParagraph(start) {
    const parts = [];
    let i = start;
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !/^#{1,6}\s+/.test(lines[i]) &&
      !/^```/.test(lines[i]) &&
      !/^<!--\s*charts:[\w-]+\s*-->$/.test(lines[i].trim()) &&
      !/^\s*[-*]\s+/.test(lines[i]) &&
      !/^\s*\d+\.\s+/.test(lines[i]) &&
      !/^\s*>/.test(lines[i]) &&
      !(/^\s*\|.*\|\s*$/.test(lines[i]) && i + 1 < lines.length && /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(lines[i + 1]))
    ) {
      parts.push(lines[i].trim());
      i += 1;
    }
    return { text: parts.join(" "), next: i };
  }

  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    if (trimmed === "") {
      i += 1;
      continue;
    }

    if (trimmed.startsWith("```")) {
      const lang = trimmed.slice(3).trim();
      const code = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        code.push(lines[i]);
        i += 1;
      }
      if (i < lines.length) i += 1;
      html.push(`<pre><code${lang ? ` class="language-${escapeHtml(lang)}"` : ""}>${escapeHtml(code.join("\n"))}</code></pre>`);
      continue;
    }

    if (trimmed === "<!-- charts:performance -->") {
      html.push(renderPerformanceCharts());
      i += 1;
      continue;
    }

    const heading = /^(#{1,6})\s+(.+)$/.exec(trimmed);
    if (heading) {
      const level = heading[1].length;
      const title = heading[2].trim();
      const id = slugFor(title);
      if (level === 2 || level === 3) {
        toc.push({ level, title: title.replace(/`/g, ""), id });
      }
      html.push(`<h${level} id="${id}">${inline(title)}</h${level}>`);
      i += 1;
      continue;
    }

    if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(lines[i + 1])) {
      const table = parseTable(lines, i);
      html.push(table.html);
      i = table.next;
      continue;
    }

    const image = /^!\[([^\]]*)\]\((\S+?)(?:\s+"([^"]+)")?\)$/.exec(trimmed);
    if (image) {
      const alt = image[1] || "";
      const src = inlineImageSrc(image[2]);
      const caption = image[3] || alt;
      html.push([
        "<figure class=\"image-figure\">",
        `<img src="${escapeAttr(src)}" alt="${escapeAttr(alt)}" loading="lazy">`,
        caption ? `<figcaption>${inline(caption)}</figcaption>` : "",
        "</figure>",
      ].join(""));
      i += 1;
      continue;
    }

    if (/^\s*>/.test(line)) {
      const quote = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) {
        quote.push(lines[i].replace(/^\s*>\s?/, ""));
        i += 1;
      }
      html.push(`<blockquote>${quote.map((part) => `<p>${inline(part)}</p>`).join("")}</blockquote>`);
      continue;
    }

    if (/^\s*[-*]\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*]\s+/, ""));
        i += 1;
      }
      html.push(`<ul>${items.map((item) => `<li>${inline(item)}</li>`).join("")}</ul>`);
      continue;
    }

    if (/^\s*\d+\.\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+\.\s+/, ""));
        i += 1;
      }
      html.push(`<ol>${items.map((item) => `<li>${inline(item)}</li>`).join("")}</ol>`);
      continue;
    }

    const para = collectParagraph(i);
    html.push(`<p>${inline(para.text)}</p>`);
    i = para.next;
  }

  return { body: html.join("\n"), toc };
}

const rendered = renderBlocks(markdown);

const tocHtml = rendered.toc
  .filter((item) => item.level === 2)
  .map((item) => `<a href="#${item.id}">${inline(item.title)}</a>`)
  .join("\n");

const page = `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>我让 Codex 自己折腾了 12 小时，最后在 8 张 W7900D 上跑起了 DeepSeek-V4-Flash</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f5ef;
      --paper: #fffefa;
      --ink: #202124;
      --muted: #62665f;
      --line: #d9d5c8;
      --code: #15191c;
      --code-ink: #e8eee9;
      --teal: #0d6f68;
      --rust: #ad4f2f;
      --gold: #b1841f;
      --blue: #284e7a;
    }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 16px/1.72 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    a { color: var(--teal); text-decoration-thickness: 1px; text-underline-offset: 3px; }
    .page-shell { min-height: 100vh; }
    .hero {
      border-bottom: 1px solid var(--line);
      background: #f0efe7;
    }
    .hero-inner {
      max-width: 1180px;
      margin: 0 auto;
      padding: 44px 24px 28px;
      display: grid;
      grid-template-columns: minmax(0, 1fr) 340px;
      gap: 36px;
      align-items: end;
    }
    .eyebrow {
      margin: 0 0 14px;
      color: var(--rust);
      font-weight: 700;
      font-size: 13px;
      letter-spacing: 0;
      text-transform: uppercase;
    }
    .hero h1 {
      margin: 0;
      max-width: 820px;
      font-size: clamp(34px, 5vw, 64px);
      line-height: 1.05;
      letter-spacing: 0;
    }
    .subtitle {
      max-width: 820px;
      margin: 20px 0 0;
      color: var(--muted);
      font-size: 18px;
    }
    .rack {
      border: 1px solid var(--line);
      background: var(--paper);
      border-radius: 8px;
      padding: 14px;
      box-shadow: 0 10px 28px rgba(32, 33, 36, 0.06);
    }
    .rack-title {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
      color: var(--muted);
      font-size: 13px;
    }
    .gpu-grid {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 8px;
    }
    .gpu {
      min-height: 54px;
      border: 1px solid #c9c4b4;
      border-left: 5px solid var(--teal);
      border-radius: 6px;
      padding: 8px;
      background: #fbfaf3;
      font-size: 12px;
      line-height: 1.25;
    }
    .gpu strong { display: block; font-size: 14px; color: var(--ink); }
    .stats {
      max-width: 1180px;
      margin: 0 auto;
      padding: 18px 24px 30px;
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }
    .stat {
      border: 1px solid var(--line);
      background: var(--paper);
      border-radius: 8px;
      padding: 14px 16px;
    }
    .stat span { display: block; color: var(--muted); font-size: 13px; }
    .stat strong { display: block; margin-top: 4px; font-size: 20px; }
    .layout {
      max-width: 1180px;
      margin: 0 auto;
      padding: 34px 24px 64px;
      display: grid;
      grid-template-columns: 250px minmax(0, 1fr);
      gap: 36px;
      align-items: start;
    }
    nav {
      position: sticky;
      top: 18px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      background: rgba(255, 254, 250, 0.92);
    }
    nav h2 {
      margin: 0 0 8px;
      font-size: 14px;
    }
    nav a {
      display: block;
      padding: 7px 0;
      color: var(--muted);
      text-decoration: none;
      border-top: 1px solid #ebe7db;
      font-size: 14px;
      line-height: 1.35;
    }
    nav a:hover { color: var(--teal); }
    article {
      min-width: 0;
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 34px min(5vw, 58px);
      box-shadow: 0 14px 34px rgba(32, 33, 36, 0.06);
    }
    article h1 { display: none; }
    article h2 {
      margin: 44px 0 14px;
      padding-top: 8px;
      font-size: 30px;
      line-height: 1.2;
      letter-spacing: 0;
      border-top: 1px solid var(--line);
    }
    article h2:first-of-type {
      margin-top: 0;
      border-top: 0;
    }
    article h3 {
      margin: 26px 0 10px;
      font-size: 20px;
      line-height: 1.3;
      letter-spacing: 0;
    }
    p { margin: 14px 0; }
    blockquote {
      margin: 18px 0 24px;
      padding: 12px 18px;
      border-left: 4px solid var(--gold);
      background: #f7f1df;
      border-radius: 0 8px 8px 0;
      color: #4e4b42;
    }
    code {
      background: #eeeadf;
      padding: 2px 5px;
      border-radius: 4px;
      font-size: 0.92em;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }
    pre {
      margin: 18px 0;
      padding: 16px;
      overflow: auto;
      background: var(--code);
      color: var(--code-ink);
      border-radius: 8px;
      border: 1px solid #0b0e11;
      line-height: 1.5;
    }
    pre code {
      padding: 0;
      background: transparent;
      color: inherit;
      border-radius: 0;
      font-size: 13px;
    }
    ul, ol { padding-left: 23px; }
    li { margin: 6px 0; }
    .table-wrap {
      margin: 18px 0 24px;
      overflow-x: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      background: #fffdf7;
      min-width: 620px;
    }
    th, td {
      padding: 10px 12px;
      border-bottom: 1px solid #e6e1d4;
      text-align: left;
      vertical-align: top;
    }
    th {
      background: #ebe6d9;
      color: #33342f;
      font-size: 13px;
      white-space: nowrap;
    }
    td:nth-child(n+2), th:nth-child(n+2) { white-space: nowrap; }
    tr:last-child td { border-bottom: 0; }
    .image-figure {
      margin: 24px 0 30px;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fffdf7;
    }
    .image-figure img {
      display: block;
      width: 100%;
      height: auto;
      border-radius: 6px;
    }
    .image-figure figcaption {
      margin-top: 10px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
    }
    @media (max-width: 920px) {
      .hero-inner { grid-template-columns: 1fr; }
      .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .layout { grid-template-columns: 1fr; }
      nav { position: static; }
    }
    @media (max-width: 560px) {
      .hero-inner { padding: 30px 16px 22px; }
      .stats { grid-template-columns: 1fr; padding: 14px 16px 24px; }
      .layout { padding: 24px 14px 44px; }
      article { padding: 24px 16px; }
      article h2 { font-size: 24px; }
      .gpu-grid { grid-template-columns: repeat(2, 1fr); }
    }
  </style>
</head>
<body>
  <div class="page-shell">
    <header class="hero">
      <div class="hero-inner">
        <div>
          <p class="eyebrow">Agent-assisted engineering / ROCm / DeepSeek-V4-Flash</p>
          <h1>我让 Codex 自己折腾了 12 小时，最后在 8 张 W7900D 上跑起了 DeepSeek-V4-Flash</h1>
          <p class="subtitle">从 vLLM、SGLang、Ollama 一路试错，到 bati.cpp ROCm、MXFP4_MOE 和标准 benchmark。这里记录的是一次真实机器上的完整工程闭环。</p>
        </div>
        <aside class="rack" aria-label="hardware summary">
          <div class="rack-title"><strong>8 x W7900D</strong><span>48GB / GPU</span></div>
          <div class="gpu-grid">
            ${Array.from({ length: 8 }, (_, index) => `<div class="gpu"><strong>GPU ${index}</strong>gfx1100<br>48GB</div>`).join("")}
          </div>
        </aside>
      </div>
      <div class="stats">
        <div class="stat"><span>当前路线</span><strong>MXFP4_MOE</strong></div>
        <div class="stat"><span>Prefill p512</span><strong>118 tok/s</strong></div>
        <div class="stat"><span>Decode n64</span><strong>9.5 tok/s</strong></div>
        <div class="stat"><span>Serving 128/64</span><strong>6.9 tok/s</strong></div>
      </div>
    </header>
    <main class="layout">
      <nav>
        <h2>目录</h2>
        ${tocHtml}
      </nav>
      <article>
        ${rendered.body}
      </article>
    </main>
  </div>
</body>
</html>
`;

fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, page);
