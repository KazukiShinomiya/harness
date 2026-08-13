#!/usr/bin/env python3
"""状態ファイルがあれば SessionStart の additionalContext として注入する。

**黙って諦めない。** 以前はどの失敗も例外を握り潰して終了していたが、それだと
「継続運用が働いていない」ことに誰も気付けない。実際、別ディレクトリから起動した
セッションが前回の経緯を知らないまま始まり、経緯の復元にセッションログを漁る羽目になった。

ガードレールと違い注入の失敗は危険ではない（偽の安心を作らない）ので、
止めも確認もしない。**ただし黙らない。** 主なものは次の四通り。

    読み込めた     -> 中身を注入し、どのパスから読んだかを添える
    ファイルが無い -> どこを探したかを Claude に伝える（起動位置の取り違えに気付ける）
    読めなかった   -> systemMessage でユーザーにも警告する（想定外の失敗）
    大きすぎる     -> 切り詰めて注入し、切ったことを両方へ伝える

**大きさは黙って通さない。** 状態ファイルは毎セッション全量が文脈へ入る。「軽量に
保つ」は SKILL.md の原則でしかなく、破っても何も起きなかった——1MB のファイルを置くと
1MB がそのまま注入された（実測）。止めはしない（注入の失敗は危険ではない）が、
情報が落ちている以上ユーザーにも伝える。縮める判断ができるのは人間だけで、
additionalContext は人間の画面に出ない。
"""

import json
import os
import pathlib
import sys

# 既定の上限。超えた分は行単位で落とす。0 以下で無制限。
DEFAULT_MAX_BYTES = 65536


def emit(context, warning=None):
    out = {"hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": context,
    }}
    if warning:
        out["systemMessage"] = warning
    json.dump(out, sys.stdout)


def clip(text, max_bytes):
    """先頭から max_bytes に収まる範囲を行単位で返す。

    返り値は (本文, 落とした行数)。バイト位置で切ると UTF-8 の途中で切れるので
    行単位で積む。**残すのは先頭。** SESSION_STATE の並びは「現在の状況 / 前回の
    戦果 / 次の行動 / 決定事項」で、次のセッションが要るのは前半に寄っている。
    """
    if max_bytes <= 0:
        return text, 0
    if len(text.encode("utf-8")) <= max_bytes:
        return text, 0

    lines = text.splitlines(keepends=True)
    kept, used = [], 0
    for i, line in enumerate(lines):
        size = len(line.encode("utf-8"))
        if used + size > max_bytes:
            return "".join(kept), len(lines) - i
        kept.append(line)
        used += size
    return "".join(kept), 0


def max_bytes_option():
    """(上限, 注意文) を返す。読めない値は既定へ倒すが、黙って倒さない。

    userConfig の型は文字列で受ける。数値型が渡り方まで含めて効くかを実測して
    いないため——`multiple: true` がカンマ区切りだった前例があり、型の扱いは
    測るまで信用しない。
    """
    raw = os.environ.get("CLAUDE_PLUGIN_OPTION_MAX_BYTES", "").strip()
    if not raw:
        return DEFAULT_MAX_BYTES, None
    try:
        return int(raw), None
    except ValueError:
        return DEFAULT_MAX_BYTES, (
            " なお max_bytes の値 %r を数として読めなかったので既定の %d を使った。"
            % (raw, DEFAULT_MAX_BYTES)
        )


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

    limit, note = max_bytes_option()
    body, dropped = clip(text, limit)
    if dropped:
        emit(
            "session-harness: %s を読み込んだ。**ただし %d バイトの上限を超えたので"
            "末尾 %d 行を切った。**落ちた分は引き継がれていないので、参照が要るなら"
            "ファイルを直接読むこと。%s\n\n%s"
            % (path, limit, dropped, note or "", body),
            warning="session-harness: %s が上限 %d バイトを超えた。末尾 %d 行を切って"
                    "注入した。ファイルを縮めるか max_bytes を上げること" % (path, limit, dropped),
        )
        return

    emit("session-harness: %s を読み込んだ。%s\n\n%s" % (path, note or "", text))


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
