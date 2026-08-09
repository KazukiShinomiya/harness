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
    """検出時に返す決定。userConfig の decision で ask / deny を切り替える。

    ask は Claude Code 側で確認として表示されないことがある（v2.1.220 の WSL2 機で実測。
    v2.1.226 のネイティブ機では表示される）。確実に止めたいなら deny。
    """
    value = os.environ.get("CLAUDE_PLUGIN_OPTION_DECISION", "ask").strip().lower()
    return value if value in ("ask", "deny") else "ask"


def option_list(key):
    """userConfig の multiple 値を読む。

    v2.1.220 で実測（生バイトで確認）: multiple: true の値は JavaScript の
    String(配列) で直列化される。つまり**カンマ区切り**で、区切りにスペースは
    入らない。JSON 配列でも改行区切りでもない。

        ["alpha", "bra vo", "char,lie"] -> "alpha,bra vo,char,lie"

    要素そのものがカンマを含むと区切りと区別できない。これは Claude Code 側の
    直列化の性質で、受け側では復元できない。パターンにカンマを使わないこと。

    userConfig のキーは Claude Code が ^[A-Za-z_]\\w* に制限しているため、
    環境変数名は upper() だけで一致する。
    """
    raw = os.environ.get("CLAUDE_PLUGIN_OPTION_" + key.upper(), "")
    return [item.strip() for item in raw.split(",") if item.strip()]


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
