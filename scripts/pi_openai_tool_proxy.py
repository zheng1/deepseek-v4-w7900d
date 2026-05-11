#!/usr/bin/env python3
"""OpenAI-compatible proxy for Pi -> llama-server with DSML tool-call bridging.

Pi sends standard OpenAI Chat Completions requests with tools. DeepSeek-V4-Flash
does not reliably emit OpenAI `message.tool_calls` through llama-server today, so
this proxy borrows the ds4-server approach:

1. Render OpenAI tool schemas into a textual DSML tool protocol in the system
   prompt and remove `tools` before forwarding to llama-server.
2. Convert assistant/tool history back into DSML so multi-turn tool use remains
   coherent.
3. Parse generated DSML blocks and return normal OpenAI `tool_calls` to Pi.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html import unescape as html_unescape
import http.client
import json
import os
import re
import time
import uuid


UPSTREAM_HOST = os.environ.get("PI_OPENAI_UPSTREAM_HOST", "127.0.0.1")
UPSTREAM_PORT = int(os.environ.get("PI_OPENAI_UPSTREAM_PORT", "8080"))
LISTEN_HOST = os.environ.get("PI_OPENAI_PROXY_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("PI_OPENAI_PROXY_PORT", "18084"))
MAX_TOKENS = int(os.environ.get("PI_OPENAI_PROXY_MAX_TOKENS", "2048"))
STOP = ["<|im_end|>", "<｜end▁of▁sentence｜>", "<｜end of sentence｜>"]
DSML_TOOL_START = "<｜DSML｜tool_calls>"
DSML_TOOL_END = "</｜DSML｜tool_calls>"
DSML_INVOKE_END = "</｜DSML｜invoke>"
DSML_PARAM_END = "</｜DSML｜parameter>"


def strip_model_tokens(text):
    for token in STOP:
        text = text.replace(token, "")
    text = re.sub(r"<\|im_start\|>assistant\s*", "", text)
    text = re.sub(r"<\|im_start\|>user\s*", "", text)
    return text.strip()


def content_to_text(content):
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                elif "content" in item:
                    parts.append(str(item.get("content", "")))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content)


def dsml_attr_escape(value):
    text = "" if value is None else str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def dsml_text_escape(value):
    text = "" if value is None else str(value)
    # Only the closing parameter tag must be protected inside a string value.
    return text.replace(DSML_PARAM_END, "&lt;/｜DSML｜parameter>")


def tool_function_schema(tool):
    if not isinstance(tool, dict):
        return None
    if tool.get("type") == "function" and isinstance(tool.get("function"), dict):
        return tool["function"]
    if "name" in tool:
        return tool
    return None


def render_tools_prompt(tools):
    schemas = []
    for tool in tools or []:
        schema = tool_function_schema(tool)
        if schema:
            schemas.append(json.dumps(schema, ensure_ascii=False, separators=(",", ":")))
    if not schemas:
        return ""

    return (
        "## Tools\n\n"
        "You have access to tools. To call tools, do not use JSON tool_calls, "
        "do not write <|im_start|>tool_call, and do not invent tool names. "
        "Instead, write exactly one DSML tool block in this format:\n\n"
        "<｜DSML｜tool_calls>\n"
        "<｜DSML｜invoke name=\"$TOOL_NAME\">\n"
        "<｜DSML｜parameter name=\"$PARAMETER_NAME\" string=\"true|false\">$PARAMETER_VALUE</｜DSML｜parameter>\n"
        "</｜DSML｜invoke>\n"
        "</｜DSML｜tool_calls>\n\n"
        "For string parameters, set string=\"true\" and put raw text in the parameter body. "
        "For numbers, booleans, arrays, and objects, set string=\"false\" and put valid JSON in the parameter body. "
        "Use the exact tool names and parameter names from these schemas:\n\n"
        + "\n".join(schemas)
        + "\n\nIf a tool is needed, output only the DSML block and no explanation. "
        "If no tool is needed, answer normally."
    )


def render_json_arguments_as_dsml(arguments):
    try:
        parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
    except Exception:
        parsed = {"arguments": arguments}
    if not isinstance(parsed, dict):
        parsed = {"arguments": parsed}

    out = []
    for key, value in parsed.items():
        if isinstance(value, str):
            out.append(
                f'<｜DSML｜parameter name="{dsml_attr_escape(key)}" string="true">'
                f"{dsml_text_escape(value)}{DSML_PARAM_END}"
            )
        else:
            raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            out.append(
                f'<｜DSML｜parameter name="{dsml_attr_escape(key)}" string="false">'
                f"{raw}{DSML_PARAM_END}"
            )
    return "\n".join(out)


def render_tool_calls_as_dsml(tool_calls):
    if not isinstance(tool_calls, list) or not tool_calls:
        return ""
    blocks = [DSML_TOOL_START]
    for call in tool_calls:
        fn = call.get("function", {}) if isinstance(call, dict) else {}
        name = fn.get("name")
        if not name:
            continue
        args = fn.get("arguments", "{}")
        blocks.append(f'<｜DSML｜invoke name="{dsml_attr_escape(name)}">')
        blocks.append(render_json_arguments_as_dsml(args))
        blocks.append(DSML_INVOKE_END)
    blocks.append(DSML_TOOL_END)
    return "\n".join(blocks)


def render_tool_result(content):
    return "<tool_result>" + dsml_text_escape(content_to_text(content)) + "</tool_result>"


def rewrite_messages_for_dsml(messages, tools_prompt):
    rewritten = []
    tools_inserted_at = None

    if tools_prompt:
        for idx, msg in enumerate(messages or []):
            role = msg.get("role") if isinstance(msg, dict) else None
            if role in {"system", "developer"}:
                content = content_to_text(msg.get("content"))
                rewritten.append({"role": "system", "content": content + "\n\n" + tools_prompt})
                tools_inserted_at = idx
                break
        if tools_inserted_at is None:
            rewritten.append({"role": "system", "content": tools_prompt})

    for idx, msg in enumerate(messages or []):
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "user")
        if role in {"system", "developer"}:
            if tools_prompt and idx == tools_inserted_at:
                continue
            if not tools_prompt:
                rewritten.append({"role": "system", "content": content_to_text(msg.get("content"))})
            else:
                rewritten.append({"role": "system", "content": content_to_text(msg.get("content"))})
            continue

        if role == "assistant":
            content = content_to_text(msg.get("content"))
            dsml = render_tool_calls_as_dsml(msg.get("tool_calls"))
            if dsml:
                content = (content + "\n\n" + dsml).strip()
            rewritten.append({"role": "assistant", "content": content})
        elif role in {"tool", "function"}:
            rewritten.append({"role": "user", "content": render_tool_result(msg.get("content"))})
        else:
            rewritten.append({"role": "user", "content": content_to_text(msg.get("content"))})

    return rewritten


def normalize_tool_call(name, args):
    if not isinstance(args, dict):
        args = {}

    aliases = {
        "file_read": "read",
        "read_file": "read",
        "batch_file_read": "read",
        "list_dir": "ls",
        "list_directory": "ls",
    }
    mapped = aliases.get(name, name)

    if mapped == "read":
        if "path" not in args:
            if "file_path" in args:
                args = {"path": args["file_path"]}
            elif "filename" in args:
                args = {"path": args["filename"]}
            elif isinstance(args.get("files"), list) and args["files"]:
                args = {"path": args["files"][0]}
    elif mapped == "ls":
        if "path" not in args:
            if "dir" in args:
                args = {"path": args["dir"]}
            elif "directory" in args:
                args = {"path": args["directory"]}

    return mapped, args


def parse_dsml_tool_calls(text):
    if not text:
        return []

    variants = [
        (DSML_TOOL_START, DSML_TOOL_END, r"<｜DSML｜invoke\b([^>]*)>(.*?)</｜DSML｜invoke>", r"<｜DSML｜parameter\b([^>]*)>(.*?)</｜DSML｜parameter>"),
        ("<DSML｜tool_calls>", "</DSML｜tool_calls>", r"<DSML｜invoke\b([^>]*)>(.*?)</DSML｜invoke>", r"<DSML｜parameter\b([^>]*)>(.*?)</DSML｜parameter>"),
        ("<tool_calls>", "</tool_calls>", r"<invoke\b([^>]*)>(.*?)</invoke>", r"<parameter\b([^>]*)>(.*?)</parameter>"),
    ]

    for start_tag, end_tag, invoke_re, param_re in variants:
        start = text.find(start_tag)
        if start < 0:
            continue
        end = text.find(end_tag, start + len(start_tag))
        if end < 0:
            block = text[start + len(start_tag) :]
        else:
            block = text[start + len(start_tag) : end]

        calls = []
        for invoke in re.finditer(invoke_re, block, flags=re.S):
            attrs = invoke.group(1)
            body = invoke.group(2)
            name = parse_xmlish_attr(attrs, "name")
            if not name:
                continue
            args = {}
            for param in re.finditer(param_re, body, flags=re.S):
                pattrs = param.group(1)
                value = param.group(2)
                pname = parse_xmlish_attr(pattrs, "name")
                is_string = parse_xmlish_attr(pattrs, "string")
                if not pname:
                    continue
                if is_string == "true":
                    args[pname] = html_unescape(value)
                else:
                    raw = value.strip()
                    try:
                        args[pname] = json.loads(raw)
                    except Exception:
                        args[pname] = html_unescape(raw)
            name, args = normalize_tool_call(name, args)
            calls.append((name, args))
        if calls:
            return calls
    return []


def parse_xmlish_attr(attrs, name):
    m = re.search(rf'{re.escape(name)}\s*=\s*"([^"]*)"', attrs or "")
    if not m:
        m = re.search(rf"{re.escape(name)}\s*=\s*'([^']*)'", attrs or "")
    if not m:
        m = re.search(rf"{re.escape(name)}\s*=\s*([^\s>]+)", attrs or "")
    return html_unescape(m.group(1)) if m else None


def parse_tool_calls(text):
    calls = parse_dsml_tool_calls(text)
    if calls:
        return calls
    legacy = parse_deepseek_tool_call(text)
    return [legacy] if legacy else []


def extract_json_object(text, start):
    depth = 0
    in_string = False
    escape = False
    begin = None
    for i in range(start, len(text)):
        ch = text[i]
        if begin is None:
            if ch == "{":
                begin = i
                depth = 1
            continue
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[begin : i + 1]
    return None


def parse_deepseek_tool_call(text):
    if "<|im_start|>tool_call" not in text:
        return None

    after = text.split("<|im_start|>tool_call", 1)[1]

    # Shape 1:
    # <|im_start|>tool_call
    # {"name": "batch_file_read", "arguments": {"files": ["x"]}}
    obj = extract_json_object(after, 0)
    if obj:
        try:
            parsed = json.loads(obj)
            if isinstance(parsed, dict) and "name" in parsed:
                name, args = normalize_tool_call(parsed.get("name"), parsed.get("arguments", {}))
                return name, args
        except Exception:
            pass

    # Shape 2:
    # <|im_start|>tool_call
    # <|im_start|>file_read
    # {"file_path": "x"}
    m = re.search(r"<\|im_start\|>\s*([A-Za-z0-9_\-]+)", after)
    if m:
        name = m.group(1)
        obj = extract_json_object(after, m.end())
    else:
        # Shape 3:
        # <|im_start|>tool_call
        # read_file
        # {"file_path": "x"}
        lines = [line.strip() for line in after.splitlines() if line.strip()]
        if not lines:
            return None
        name = lines[0]
        obj = extract_json_object(after, after.find(name) + len(name))
    args = {}
    if obj:
        try:
            args = json.loads(obj)
        except Exception:
            args = {}
    name, args = normalize_tool_call(name, args)
    return name, args


def openai_response(model, content=None, tool_calls=None, stream=False):
    created = int(time.time())
    cid = "chatcmpl-proxy-" + uuid.uuid4().hex[:12]
    tool_calls = tool_calls or []

    if stream:
        chunks = []
        if tool_calls:
            delta_calls = []
            for i, (name, args) in enumerate(tool_calls):
                delta_calls.append(
                    {
                        "index": i,
                        "id": "call_" + uuid.uuid4().hex[:16],
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": json.dumps(args, ensure_ascii=False, separators=(",", ":")),
                        },
                    }
                )
            chunks.append(
                {
                    "id": cid,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                "tool_calls": delta_calls,
                            },
                            "finish_reason": None,
                        }
                    ],
                }
            )
            finish = "tool_calls"
        else:
            chunks.append(
                {
                    "id": cid,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {"index": 0, "delta": {"role": "assistant", "content": content or ""}, "finish_reason": None}
                    ],
                }
            )
            finish = "stop"
        chunks.append(
            {
                "id": cid,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
            }
        )
        payload = b"".join(
            b"data: " + json.dumps(chunk, ensure_ascii=False).encode("utf-8") + b"\n\n" for chunk in chunks
        )
        return 200, "text/event-stream", payload + b"data: [DONE]\n\n"

    message = {"role": "assistant", "content": content or ""}
    finish_reason = "stop"
    if tool_calls:
        message["content"] = None
        message["tool_calls"] = []
        for name, args in tool_calls:
            message["tool_calls"].append(
                {
                    "id": "call_" + uuid.uuid4().hex[:16],
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(args, ensure_ascii=False, separators=(",", ":")),
                    },
                }
            )
        finish_reason = "tool_calls"
    payload = {
        "id": cid,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
    }
    return 200, "application/json", json.dumps(payload, ensure_ascii=False).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt, *args):
        print("[pi-openai-tool-proxy] " + fmt % args, flush=True)

    def _send(self, status, content_type, payload):
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _forward_raw(self, method, body=None):
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in {"host", "content-length", "connection", "accept-encoding"}
        }
        if body is not None:
            headers["Content-Length"] = str(len(body))
        conn = http.client.HTTPConnection(UPSTREAM_HOST, UPSTREAM_PORT, timeout=900)
        try:
            conn.request(method, self.path, body=body, headers=headers)
            resp = conn.getresponse()
            payload = resp.read()
            content_type = resp.getheader("content-type") or "application/octet-stream"
            self._send(resp.status, content_type, payload)
        finally:
            conn.close()

    def do_GET(self):
        self._forward_raw("GET")

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("content-length", "0") or "0"))
        if self.path.split("?", 1)[0] != "/v1/chat/completions":
            self._forward_raw("POST", raw)
            return

        try:
            data = json.loads(raw or b"{}")
        except Exception as exc:
            self._send(400, "application/json", json.dumps({"error": str(exc)}).encode("utf-8"))
            return

        requested_stream = bool(data.get("stream"))
        model = data.get("model") or "local"

        tools_prompt = render_tools_prompt(data.get("tools") or [])
        data["messages"] = rewrite_messages_for_dsml(data.get("messages") or [], tools_prompt)
        data["stream"] = False
        for unsupported in (
            "tools",
            "tool_choice",
            "parallel_tool_calls",
            "stream_options",
            "store",
            "metadata",
            "reasoning_effort",
        ):
            data.pop(unsupported, None)

        if isinstance(data.get("max_tokens"), int):
            data["max_tokens"] = min(data["max_tokens"], MAX_TOKENS)
        else:
            data["max_tokens"] = MAX_TOKENS
        existing_stop = data.get("stop")
        if isinstance(existing_stop, str):
            stops = [existing_stop]
        elif isinstance(existing_stop, list):
            stops = list(existing_stop)
        else:
            stops = []
        for stop in STOP:
            if stop not in stops:
                stops.append(stop)
        data["stop"] = stops

        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        conn = http.client.HTTPConnection(UPSTREAM_HOST, UPSTREAM_PORT, timeout=900)
        try:
            conn.request(
                "POST",
                "/v1/chat/completions",
                body=body,
                headers={
                    "content-type": "application/json",
                    "content-length": str(len(body)),
                    "authorization": self.headers.get("authorization", "Bearer local"),
                },
            )
            resp = conn.getresponse()
            upstream_payload = resp.read()
            if resp.status >= 400:
                self._send(resp.status, resp.getheader("content-type") or "application/json", upstream_payload)
                return
        finally:
            conn.close()

        try:
            upstream = json.loads(upstream_payload)
            content = upstream["choices"][0]["message"].get("content") or ""
        except Exception:
            self._send(502, "application/json", upstream_payload)
            return

        tool_calls = parse_tool_calls(content)
        if tool_calls:
            print(f"[pi-openai-tool-proxy] repaired tool calls: {tool_calls}", flush=True)
            status, ctype, payload = openai_response(model, tool_calls=tool_calls, stream=requested_stream)
        else:
            status, ctype, payload = openai_response(model, content=strip_model_tokens(content), stream=requested_stream)
        self._send(status, ctype, payload)


def main():
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
    print(
        f"[pi-openai-tool-proxy] listening on http://{LISTEN_HOST}:{LISTEN_PORT} "
        f"-> http://{UPSTREAM_HOST}:{UPSTREAM_PORT}",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
