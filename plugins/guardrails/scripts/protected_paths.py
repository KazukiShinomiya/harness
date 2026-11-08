#!/usr/bin/env python3
"""書き込み先が保護対象のパスかを判定する。

秘密情報や、壊れると復旧が面倒なものを既定で拾う。プロジェクト固有の保護対象は
userConfig の protected_paths から足せる。

Edit / Write / NotebookEdit だけでなく **Bash も見る**。以前は Edit 系だけだったため、
`echo x >> ~/.ssh/authorized_keys` のようなリダイレクトが素通りしていた（実測）。
Edit ツールでは止まるのにシェル経由なら通るのでは、守っていることにならない。
"""

import fnmatch
import json
import os
import sys

import _common
import _shell

DEFAULT_PROTECTED = (
    # 秘密情報
    ".env",
    ".env.*",
    "*/.env",
    "*/.env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*/id_rsa*",
    "*/id_ed25519*",
    "*credentials*",
    "*/.ssh/*",
    "*/.aws/*",
    "*/.gnupg/*",
    # 壊すと面倒なもの
    "*/.git/*",
    "*/dotfiles/*",
    # 人間が決めるもの。Codex に見せてよいかの分類（dotfiles の bin/codex-review が読む）。
    # エージェントが承認なしに allow を書けないよう、書き込みの前に確認を挟む
    "*/.codex-review",
)

# 人間が Yes / No を選ぶための文。詳しくは irreversible_ops.py の CONSEQUENCES を見ること。
REASON = (
    "保護対象への書き込み: {path}（{pattern} に一致）。"
    "秘密情報や設定を壊していないか確かめてほしい"
)

# 引数が書き込み先になるコマンド。basename で照合する。
#
# **コピー元も拾う（意図した振る舞い）。** `cp .env /tmp/x` や `dd if=.env` でも確認が出る。
# 秘密情報を持ち出すときに一拍置けるので、残している（tests/run.sh が固定している）。
WRITING_COMMANDS = frozenset(
    ("tee", "cp", "mv", "install", "ln", "truncate", "dd", "sed", "perl", "touch", "mkdir")
)

# この中のコマンドが書き込むのは、`-i`（その場で書き換え）が付いたときだけ。
IN_PLACE_COMMANDS = frozenset(("sed", "perl"))


def matches(path, pattern):
    """パスが保護対象の glob に一致するか。

    書き込み先がディレクトリ名で終わることがある（`cp key ~/.ssh`）。`*/.ssh/*` は
    末尾の `/` が無いと一致しないので、`/` を足した形でも照合する。
    """
    for candidate in (path, path.rstrip("/") + "/"):
        if fnmatch.fnmatch(candidate, pattern):
            return True
    return fnmatch.fnmatch(os.path.basename(path), pattern)


def resolve(path, cwd):
    """`~` を展開し、相対パスを cwd から絶対パスにする。

    以前は書かれたままのパスを照合していたため、`.ssh/authorized_keys` や
    `.git/hooks/pre-commit` のような相対パスが `*/.ssh/*` に一致せず素通りしていた
    （2026-11-08 実測）。
    """
    return os.path.normpath(os.path.join(cwd, os.path.expanduser(path)))


def in_place(words):
    """`sed -i` / `perl -pi` のような、その場で書き換えるオプションがあるか。"""
    for word in words:
        if word.startswith("--in-place"):
            return True
        if word.startswith("-") and not word.startswith("--") and "i" in word[1:]:
            return True
    return False


def command_write_targets(words):
    """単純コマンド一つ（語のリスト）から、書き込み先になり得るパスを拾う。"""
    targets = []
    after_redirect = False
    skip_next = False
    writing = False

    for token in words:
        if skip_next:
            skip_next = False
            continue
        if after_redirect:
            after_redirect = False
            # `2>&1` や `>&-` はファイル記述子であってパスではない。
            if not (token.isdigit() or token == "-"):
                targets.append(token)
            continue
        if _shell.is_redirect(token):
            if ">" in token:
                after_redirect = True
            else:
                skip_next = True  # `<` `<<` `<<<` の次は入力元。書き込み先ではない
            continue

        name = os.path.basename(token)
        if name in WRITING_COMMANDS:
            writing = name not in IN_PLACE_COMMANDS or in_place(words)
        elif writing and not token.startswith("-"):
            if token[:3] in ("of=", "if="):  # dd
                token = token[3:]
            targets.append(token)
    return targets


def bash_write_targets(command, cwd):
    """コマンド文字列から、書き込み先になり得るパスを絶対パスで拾う。

    **完全ではない。** シェルは任意の書き込み方を許すので、静的に全部は拾えない。
    ここで拾えるのは、リダイレクト先と、書き込むと分かっているコマンドの引数だ。
    `bash -c` / `eval` / `$(...)` の中身も見る（_shell.simple_commands が展開する）。
    `cd` は、後に続くコマンドの cwd として追う。

    それでも拾えないもの（`python -c` の中、実行時に決まる変数展開の先など）は
    README に穴として書いてある。**塞いだつもりにならないこと。**

    読み取りは対象にしない。この層は「書き込む前に確認する」ためのもので、
    `cat .env` まで拾うと日常操作が確認だらけになり、やがて誰も読まなくなる。
    """
    targets = []
    for words in _shell.simple_commands(command):
        if os.path.basename(words[0]) == "cd":
            destination = words[1] if len(words) > 1 else "~"
            if destination != "-":
                cwd = resolve(destination, cwd)
            continue
        targets += [resolve(path, cwd) for path in command_write_targets(words)]
    return targets


def candidates(tool_input, cwd):
    """判定対象のパス。Bash はコマンド文字列から、他はツールの引数から取る。"""
    command = tool_input.get("command")
    if command:
        # 解釈できないコマンドはここで例外になり、guard.sh が ask に倒す。
        # 判定できないものを「問題なし」として素通しにはしない。
        return bash_write_targets(command, cwd)

    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    return [resolve(path, cwd)] if path else []


def main():
    payload = json.load(sys.stdin)
    patterns = list(DEFAULT_PROTECTED) + _common.option_list("protected_paths")
    # フックの入力には cwd が入る。無ければ判定器自身の cwd（= Claude Code の cwd）を使う。
    cwd = payload.get("cwd") or os.getcwd()

    for path in candidates(payload.get("tool_input", {}), cwd):
        for pattern in patterns:
            if matches(path, pattern):
                _common.emit(REASON.format(pattern=pattern, path=path))
                return


if __name__ == "__main__":
    main()
