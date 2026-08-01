#!/usr/bin/env python3
"""状態ファイルがあれば SessionStart の additionalContext として注入する。"""

import json
import os
import pathlib
import sys


def main():
    name = os.environ.get("CLAUDE_PLUGIN_OPTION_STATE_FILE", "").strip() or "SESSION_STATE.md"
    base = os.environ.get("CLAUDE_PROJECT_DIR") or "."
    path = pathlib.Path(base) / name
    if not path.is_file():
        return

    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        return

    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": text,
            }
        },
        sys.stdout,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:  # 注入できないだけなら黙って諦める
        sys.exit(0)
