#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path


ENCODING_DIR = Path("/data/models/deepseek-ai/DeepSeek-V4-Flash/encoding")
sys.path.insert(0, str(ENCODING_DIR))

from encoding_dsv4 import encode_messages  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Encode a DeepSeek V4 chat prompt.")
    parser.add_argument("prompt", help="User message to encode")
    parser.add_argument("--system", default="You are a helpful assistant.")
    parser.add_argument("--mode", choices=["chat", "thinking"], default="chat")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    text = encode_messages(
        [
            {"role": "system", "content": args.system},
            {"role": "user", "content": args.prompt},
        ],
        thinking_mode=args.mode,
    )
    if args.out is None:
        print(text, end="")
    else:
        args.out.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
