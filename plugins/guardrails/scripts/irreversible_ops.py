#!/usr/bin/env python3
"""Bash コマンドが不可逆操作かを判定する。

部分文字列一致ではなくトークン境界で照合する。`echo "git push はまだしない"` の
ように、引用符の中にたまたまパターンが現れるだけの文字列で発火しないようにするため。
"""

import json
import os
import shlex
import sys

import _common

# 既存のグローバル settings.json のフックから移植した既定パターン。
# 空白区切りはトークン列として扱い、連続一致で判定する。
#
# rm はここに置かない。オプションの綴りが多すぎてトークン列では表せないため、
# 下の find_rm_hit() が意味で判定する。
DEFAULT_PATTERNS = (
    "git push",
    "git commit",
    "git reset --hard",
    "git rebase",
    "git clean",
    "git checkout --",
    "git branch -D",
)

# rm の破壊的オプション。-rf / -fr / -Rf / -r -f / --recursive --force は
# すべて同じ意味だが、綴りは違う。以前は "rm -rf" "rm -r" "rm -f" を literal で
# 並べていたため、**"rm -fr" が素通りしていた**（実測）。綴りを列挙する方針では
# 必ず取りこぼす。まとめ書きされた短オプションは 1 文字ずつ見る。
RM_SHORT = "rRf"
RM_LONG = ("--recursive", "--force")

# 確認ダイアログに出る文。**止められた人間が Yes / No を選ぶための情報**を書く。
#
# 以前はここに "NO fabricated consent -- confirm full-context read and EXPLICIT
# user approval before proceeding" と書いていた。これはエージェントへの戒めであって、
# 人間には何が起きようとしているのか分からない。しかも操作の種類によらず同じ文だった。
#
# **判断できないダイアログは、意識せず承認される。** 2026-08-10、確認は出ていたのに
# 無意識に Yes が押されていたことが分かった。確認が出ることと、確認として機能する
# ことは別。ここが空疎だと、ガードレールは「出ているのに効いていない」状態になる。
CONSEQUENCES = {
    "git push": "リモートへ反映される。取り消しても、取得済みの相手の手元には残る",
    "git commit": "コミットが作られる。履歴なので git で戻せる",
    "git reset --hard": "未コミットの変更が消える。git では戻せない",
    "git rebase": "履歴が書き換わる。共有済みなら他の人の手元と食い違う",
    "git clean": "追跡していないファイルが消える。git では戻せない",
    "git checkout --": "そのファイルの未コミットの変更が消える。git では戻せない",
    "git branch -D": "未マージでもブランチを削除する",
    "docker compose up": "コンテナが起動する。ボリュームやポートが実際に変わる",
}

# rm は綴りで hit が変わる（rm -rf / rm -fr / rm --force …）ので接頭辞で引く。
RM_CONSEQUENCE = (
    "ファイル・ディレクトリを削除する。rm-guard 経由ならゴミ箱へ入り trash-restore で"
    "戻せるが、そうでなければ戻せない"
)

# userConfig の extra_patterns で足されたものはここに説明が無い。
# 「何が起きるか」を語れない以上、語れないことを言う。
UNKNOWN_CONSEQUENCE = "取り消しにくい操作として登録されている"

REASON = "{hit} — {consequence}。意図した操作か確かめてほしい"


def consequence_for(hit):
    if hit.startswith("rm "):
        return RM_CONSEQUENCE
    return CONSEQUENCES.get(hit, UNKNOWN_CONSEQUENCE)


def contains_sequence(tokens, needle):
    """tokens の中に needle が連続して現れるか。"""
    if not needle:
        return False
    span = len(needle)
    return any(tokens[i : i + span] == needle for i in range(len(tokens) - span + 1))


def find_rm_hit(tokens):
    """rm の呼び出しを見つけ、破壊的なオプションが付いていれば綴りごと返す。

    `/bin/rm` のような絶対パス呼びも拾う。`git rm` は追跡下のファイルしか消さず
    git から戻せるので対象にしない。
    """
    for index, token in enumerate(tokens):
        if os.path.basename(token) != "rm":
            continue
        if index > 0 and tokens[index - 1] == "git":
            continue

        for arg in tokens[index + 1:]:
            if arg == "--":
                break  # 以降はオプションではなくパス。
            if not arg.startswith("-") or arg == "-":
                continue
            if arg.startswith("--"):
                if arg in RM_LONG:
                    return "rm " + arg
                continue
            if any(char in RM_SHORT for char in arg[1:]):
                return "rm " + arg
    return None


def find_hit(tokens, patterns):
    for pattern in patterns:
        if contains_sequence(tokens, shlex.split(pattern)):
            return pattern

    hit = find_rm_hit(tokens)
    if hit is not None:
        return hit

    # トークン列だけでは表せない複合形。
    if contains_sequence(tokens, ["docker", "compose"]) and "up" in tokens:
        return "docker compose up"

    # かつてここに `"--build" in tokens` という単独パターンがあったが、削除した。
    # 意図していた `docker compose up --build` は上の行が先に拾うため、この規則が
    # 実際に発火するのは `make --build` のような無関係なコマンドだけだった（実測）。
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

    _common.emit(REASON.format(hit=hit, consequence=consequence_for(hit)))


if __name__ == "__main__":
    main()
