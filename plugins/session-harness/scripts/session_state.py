#!/usr/bin/env python3
"""状態ファイルがあれば SessionStart の additionalContext として注入する。

**黙って諦めない。** 以前はどの失敗も例外を握り潰して終了していたが、それだと
「継続運用が働いていない」ことに誰も気付けない。実際、別ディレクトリから起動した
セッションが前回の経緯を知らないまま始まり、経緯の復元にセッションログを漁る羽目になった。

ガードレールと違い注入の失敗は危険ではない（偽の安心を作らない）ので、
止めも確認もしない。**ただし黙らない。** 三通りを区別して報告する。

    読み込めた     -> 中身を注入し、どのパスから読んだかを添える
    ファイルが無い -> どこを探したかを Claude に伝える（起動位置の取り違えに気付ける）
    読めなかった   -> systemMessage でユーザーにも警告する（想定外の失敗）
"""

import json
import os
import pathlib
import sys


def emit(context, warning=None):
    out = {"hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": context,
    }}
    if warning:
        out["systemMessage"] = warning
    json.dump(out, sys.stdout)


def main():
    name = os.environ.get("CLAUDE_PLUGIN_OPTION_STATE_FILE", "").strip() or "SESSION_STATE.md"
    base = os.environ.get("CLAUDE_PROJECT_DIR") or "."
    path = pathlib.Path(base) / name

    if not path.is_file():
        # 異常ではない。状態ファイルを置いていないプロジェクトの方が多い。
        # ただし「探した場所」は伝える。起動位置を間違えたときの唯一の手がかりになる。
        emit(
            "session-harness: %s が無いため、前回のセッション状態は読み込んでいない。"
            "別の場所から起動していないか確認すること。" % path
        )
        return

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        emit(
            "session-harness: %s を読めなかった (%s)。前回の経緯は引き継がれていない。" % (path, exc),
            warning="session-harness: %s を読めなかった。セッション状態は引き継がれていない" % path,
        )
        return

    if not text.strip():
        emit("session-harness: %s は空だった。引き継ぐ経緯は無い。" % path)
        return

    emit("session-harness: %s を読み込んだ。\n\n%s" % (path, text))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 -- 何が起きても起動は止めない
        json.dump({
            "systemMessage": "session-harness: 自己診断が異常終了した (%s)。"
                             "セッション状態は引き継がれていない可能性がある" % exc,
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "session-harness: 状態ファイルの注入に失敗した (%s)。"
                                     "前回の経緯は引き継がれていない前提で進めること。" % exc,
            },
        }, sys.stdout)
        sys.exit(0)
