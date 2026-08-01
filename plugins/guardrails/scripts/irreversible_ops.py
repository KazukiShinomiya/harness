#!/usr/bin/env python3
"""Bash コマンドが不可逆操作かを判定し、該当すれば PreToolUse の決定を stdout へ出す。

契約は guard.sh 側のコメントを参照。異常時は例外を上げて非 0 で終了し、
ラッパーに fail-safe（ask）を任せる。
"""

import json
import os
import sys

# 既存のグローバル settings.json フックから移植した既定パターン。
DEFAULT_PATTERNS = (
    "git push",
    "git commit",
    "git reset --hard",
    "git rebase",
    "git clean",
    "git checkout --",
    "git branch -D",
    "rm -rf",
    "rm -r",
    "rm -f",
)

REASON = (
    "irreversible op ({hit}): NO fabricated consent -- confirm full-context read "
    "and EXPLICIT user approval before proceeding"
)


def extra_patterns():
    """userConfig の extra_patterns を環境変数から読む。

    multiple: true の値がどう直列化されるかは未検証のため、JSON 配列・改行区切り・
    カンマ区切りのいずれでも受けられるようにしてある。
    """
    raw = os.environ.get("CLAUDE_PLUGIN_OPTION_EXTRA_PATTERNS", "").strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            return [str(x) for x in json.loads(raw)]
        except json.JSONDecodeError:
            pass
    sep = "\n" if "\n" in raw else ","
    return [p.strip() for p in raw.split(sep) if p.strip()]


def decision():
    value = os.environ.get("CLAUDE_PLUGIN_OPTION_DECISION", "ask").strip().lower()
    return value if value in ("ask", "deny") else "ask"


def find_hit(command, patterns):
    for pattern in patterns:
        if pattern in command:
            return pattern
    # 文字列一致では拾えない複合形。
    if "docker compose" in command and " up" in command:
        return "docker compose up"
    if "--build" in command:
        return "--build"
    return None


def main():
    payload = json.load(sys.stdin)
    command = payload.get("tool_input", {}).get("command", "")
    if not command:
        return

    hit = find_hit(command, list(DEFAULT_PATTERNS) + extra_patterns())
    if hit is None:
        return  # 決定なし。通常の権限フローへ。

    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": decision(),
                "permissionDecisionReason": REASON.format(hit=hit),
            }
        },
        sys.stdout,
    )


if __name__ == "__main__":
    main()
