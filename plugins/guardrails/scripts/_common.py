"""判定器が共有する小さな部品。

各判定器の契約:
    exit 0 + stdout に JSON  -> 検出あり。そのまま Claude Code へ渡る
    exit 0 + stdout が空     -> 決定なし。通常の権限フローへ
    exit 非 0                -> 異常。guard.sh が ask に倒す
"""

import json
import os
import sys


def decision():
    """検出時に返す決定。userConfig の decision で ask / deny を切り替える。"""
    value = os.environ.get("CLAUDE_PLUGIN_OPTION_DECISION", "ask").strip().lower()
    return value if value in ("ask", "deny") else "ask"


def option_list(key):
    """userConfig の multiple 値を読む。

    multiple: true がどう直列化されるかは未検証のため、JSON 配列・改行区切り・
    カンマ区切りのいずれでも受けられるようにしてある。
    """
    raw = os.environ.get("CLAUDE_PLUGIN_OPTION_" + key.upper(), "").strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            return [str(x) for x in json.loads(raw)]
        except json.JSONDecodeError:
            pass
    sep = "\n" if "\n" in raw else ","
    return [item.strip() for item in raw.split(sep) if item.strip()]


def emit(reason):
    """検出を Claude Code へ伝える。"""
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": decision(),
                "permissionDecisionReason": "guardrails: " + reason,
            }
        },
        sys.stdout,
    )
