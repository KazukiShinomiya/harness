#!/usr/bin/env python3
"""Bash コマンドが不可逆操作かを判定する。

部分文字列一致ではなくトークン境界で照合する。`echo "git push はまだしない"` の
ように、引用符の中にたまたまパターンが現れるだけの文字列で発火しないようにするため。
"""

import json
import shlex
import sys

import _common

# 既存のグローバル settings.json のフックから移植した既定パターン。
# 空白区切りはトークン列として扱い、連続一致で判定する。
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


def contains_sequence(tokens, needle):
    """tokens の中に needle が連続して現れるか。"""
    if not needle:
        return False
    span = len(needle)
    return any(tokens[i : i + span] == needle for i in range(len(tokens) - span + 1))


def find_hit(tokens, patterns):
    for pattern in patterns:
        if contains_sequence(tokens, shlex.split(pattern)):
            return pattern
    # トークン列だけでは表せない複合形。
    if contains_sequence(tokens, ["docker", "compose"]) and "up" in tokens:
        return "docker compose up"
    if "--build" in tokens:
        return "--build"
    return None


def main():
    payload = json.load(sys.stdin)
    command = payload.get("tool_input", {}).get("command", "")
    if not command:
        return

    # 解釈できないコマンドは判定を諦める。非 0 で終了し guard.sh に ask を任せる。
    tokens = shlex.split(command)

    hit = find_hit(tokens, list(DEFAULT_PATTERNS) + _common.option_list("extra_patterns"))
    if hit is None:
        return  # 決定なし。通常の権限フローへ。

    _common.emit(REASON.format(hit=hit))


if __name__ == "__main__":
    main()
