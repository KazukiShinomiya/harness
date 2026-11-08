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
import _shell

# git は語の並びではなく、サブコマンドと引数の意味で判定する（find_git_hit）。
# 以前は "git push" のような語の並びで照合していたため、`git -C dir push` や
# `git reset HEAD~1 --hard` のように語が離れるだけで素通りしていた（2026-11-08 実測）。
#
# 利用者が userConfig の extra_patterns で足すものは、従来どおり語の並びで照合する。

# グローバルオプションのうち、次の語を引数に取るもの。これを飛ばしてサブコマンドを探す。
GIT_OPTIONS_WITH_ARG = frozenset(
    ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env", "--super-prefix")
)

# 読むだけの git config。`git config --get core.hooksPath` は harness 自身も使う。
GIT_CONFIG_READ = frozenset(("--get", "--get-all", "--get-regexp", "--list", "-l", "get", "list"))

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
    "git checkout .": "作業ツリーの未コミットの変更が消える。git では戻せない",
    "git checkout -f": "未コミットの変更を捨てて切り替える。git では戻せない",
    "git restore": "そのファイルの未コミットの変更が消える。git では戻せない",
    "git stash drop": "退避した変更が消える。戻すのは難しい",
    "git stash clear": "退避した変更がすべて消える。戻すのは難しい",
    "git core.hooksPath": "git 層のフックを外す。commit や push の前の確認が働かなくなる",
    "find -delete": "一致したファイルを削除する。rm-guard を通らないので戻せない",
    "git gc --prune": "到達できないコミットを今すぐ消す。reflog から戻す手段がなくなる",
    "git reflog expire": "reflog を消す。誤った reset や rebase から戻す手段がなくなる",
    "git tag -d": "タグを削除する。リモートに無いタグなら戻せない",
    "docker compose down --volumes": "コンテナと一緒にボリュームを消す。DB などの永続データが消える",
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
                # GNU は曖昧でない省略形を受け付ける（`--rec` は `--recursive`）。
                if len(arg) >= 3 and any(full.startswith(arg) for full in RM_LONG):
                    return "rm " + arg
                continue
            if any(char in RM_SHORT for char in arg[1:]):
                return "rm " + arg
    return None


def git_invocation(words):
    """`git ...` を見つけ、(サブコマンド, その引数, -c で渡された設定) を返す。無ければ None。

    **語の位置を問わず探す（意図した振る舞い）。** そのため `echo git push` や
    `grep git push .` でも確認が出る。先頭の語だけを見れば誤検出は消えるが、
    `timeout 10 git push` や `xargs git push` のような前置きを一つずつ覚えさせる
    ことになり、覚え漏れはそのまま素通りになる。誤検出の方がまだましと判断した。
    """
    for index, word in enumerate(words):
        if os.path.basename(word) != "git":
            continue
        configs = []
        position = index + 1
        while position < len(words):
            token = words[position]
            if token in GIT_OPTIONS_WITH_ARG:
                if token in ("-c", "--config-env") and position + 1 < len(words):
                    configs.append(words[position + 1])
                position += 2
                continue
            if token.startswith("--config-env="):
                configs.append(token.split("=", 1)[1])
            if token.startswith("-"):
                position += 1
                continue
            return token, words[position + 1:], configs
        return None, [], configs
    return None


def short_flags(args):
    """`-df` のようなまとめ書きを含め、短オプションの文字を集める。"""
    return {char for arg in args if arg.startswith("-") and not arg.startswith("--") for char in arg[1:]}


def find_git_hit(words):
    found = git_invocation(words)
    if found is None:
        return None
    sub, args, configs = found

    # git 層を外す操作は、サブコマンドが何であれ拾う。プラグインの層と git 層を同時に
    # 抜けられてしまうため（`git -c core.hooksPath=/dev/null commit`）。
    if any(config.lower().startswith("core.hookspath") for config in configs):
        return "git core.hooksPath"
    if sub == "config" and any(arg.lower() == "core.hookspath" for arg in args):
        if not any(arg in GIT_CONFIG_READ for arg in args):
            return "git core.hooksPath"

    flags = short_flags(args)
    if sub in ("push", "commit", "rebase", "clean"):
        return "git " + sub
    if sub == "reset" and "--hard" in args:
        return "git reset --hard"
    if sub == "checkout":
        if "--" in args:
            return "git checkout --"
        if "." in args:
            return "git checkout ."
        if "f" in flags or "--force" in args:
            return "git checkout -f"
    if sub == "restore":
        staged_only = ("--staged" in args or "S" in flags) and not ("--worktree" in args or "W" in flags)
        if not staged_only:
            return "git restore"
    if sub == "branch":
        deleting = "d" in flags or "--delete" in args
        forcing = "f" in flags or "--force" in args
        if "D" in flags or (deleting and forcing):
            return "git branch -D"
    if sub == "stash" and args[:1] in (["drop"], ["clear"]):
        return "git stash " + args[0]
    # 以下は 2026-11-08 の Codex のレビューで挙がったもの。誤った操作から戻る手段を消す。
    if sub == "prune" or (sub == "gc" and any(arg == "--prune" or arg.startswith("--prune=") for arg in args)):
        return "git gc --prune"
    if sub == "reflog" and args[:1] in (["expire"], ["delete"]):
        return "git reflog expire"
    if sub == "tag" and ("d" in flags or "--delete" in args):
        return "git tag -d"
    return None


def find_hit_in(words, patterns):
    """単純コマンド一つ（語のリスト）を判定する。"""
    for pattern in patterns:
        if contains_sequence(words, shlex.split(pattern)):
            return pattern

    hit = find_git_hit(words) or find_rm_hit(words)
    if hit is not None:
        return hit

    names = [os.path.basename(word) for word in words]
    if "find" in names and "-delete" in words:
        return "find -delete"

    # トークン列だけでは表せない複合形。v1 のハイフン綴りも拾う。
    compose = contains_sequence(words, ["docker", "compose"]) or "docker-compose" in names
    if compose and "up" in words:
        return "docker compose up"
    if compose and "down" in words and ("--volumes" in words or "v" in short_flags(words)):
        return "docker compose down --volumes"

    # かつてここに `"--build" in tokens` という単独パターンがあったが、削除した。
    # 意図していた `docker compose up --build` は上の行が先に拾うため、この規則が
    # 実際に発火するのは `make --build` のような無関係なコマンドだけだった（実測）。
    return None


def find_hit(command, patterns):
    for words in _shell.simple_commands(command):
        hit = find_hit_in(words, patterns)
        if hit is not None:
            return hit
    return None


def main():
    payload = json.load(sys.stdin)
    command = payload.get("tool_input", {}).get("command", "")
    if not command:
        return

    # 解釈できないコマンドは判定を諦める。例外で非 0 終了し、guard.sh に ask を任せる。
    hit = find_hit(command, _common.option_list("extra_patterns"))
    if hit is None:
        return  # 決定なし。通常の権限フローへ。

    _common.emit(REASON.format(hit=hit, consequence=consequence_for(hit)))


if __name__ == "__main__":
    main()
