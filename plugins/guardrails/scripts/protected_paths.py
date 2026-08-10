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
import re
import shlex
import sys

import _common

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
)

# 人間が Yes / No を選ぶための文。詳しくは irreversible_ops.py の CONSEQUENCES を見ること。
REASON = (
    "保護対象への書き込み: {path}（{pattern} に一致）。"
    "秘密情報や設定を壊していないか確かめてほしい"
)

# 書き込み先を作るリダイレクト。 > >> 2> &> 1>> >| に一致する。
REDIRECT = re.compile(r"^(?:[0-9]*|&)>{1,2}\|?")

# 引数が書き込み先になるコマンド。basename で照合する。
WRITING_COMMANDS = frozenset(("tee", "cp", "mv", "install", "ln", "truncate", "dd", "sed"))

# コマンドの区切り。ここで「書き込みコマンドの引数」の解釈を打ち切る。
BOUNDARIES = frozenset((";", "&&", "||", "|", "|&", "&"))

# `-c` の引数がそれ自体シェルコマンドになるもの。中身はただの文字列なので、同じ判定を
# 再帰的に当てられる。当てないと、サブシェルで包むだけでこの層を抜けられた（実測）。
SHELL_RUNNERS = frozenset(("bash", "sh", "zsh", "dash", "ksh"))

# 再帰の深さ。入れ子は現実には浅い。文字列は潜るたびに短くなるので停止はするが、
# 際限なく潜る必要もない。
MAX_SHELL_DEPTH = 3


def matches(path, pattern):
    return fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(os.path.basename(path), pattern)


def shell_command_argument(tokens, index):
    """`bash -c '<cmd>'` の `<cmd>` を返す。無ければ None。

    `-c` より前に非オプションが来たら、それはスクリプトファイルの実行であって
    文字列の評価ではない（`bash script.sh`）。中身を静的には読めないので対象外。
    """
    for position in range(index + 1, len(tokens)):
        token = tokens[position]
        if token in BOUNDARIES:
            return None
        if token == "-c":
            return tokens[position + 1] if position + 1 < len(tokens) else None
        if not token.startswith("-"):
            return None
    return None


def bash_write_targets(command, depth=0):
    """コマンド文字列から、書き込み先になり得るパスを拾う。

    **完全ではない。** シェルは任意の書き込み方を許すので、静的に全部は拾えない。
    ここで拾えるのはリダイレクト先、書き込むと分かっているコマンドの引数、そして
    `bash -c '...'` / `eval '...'` の中身。最後のものは引数がただの文字列なので、
    同じ関数を再帰的に当てれば読める——以前は「静的には無理」の側に分類していたが、
    それは誤りで、サブシェルで包むだけでこの層を抜けられていた（実測して塞いだ）。

    それでも拾えないもの（`python -c` の中、実行時に決まる変数展開の先など）は
    README に穴として書いてある。**塞いだつもりにならないこと。**

    読み取りは対象にしない。この層は「書き込む前に確認する」ためのもので、
    `cat .env` まで拾うと日常操作が確認だらけになり、やがて誰も読まなくなる。
    """
    tokens = shlex.split(command)
    targets = []
    after_redirect = False
    writing = False

    for index, token in enumerate(tokens):
        # `cp a b; ls` のように区切りが直前の語へくっつくことがある。
        ends_segment = token.endswith(";")
        if ends_segment:
            token = token.rstrip(";")

        if after_redirect:
            after_redirect = False
            if token and not token.startswith("&"):
                targets.append(token)
        elif token in BOUNDARIES or not token:
            writing = False
        else:
            redirect = REDIRECT.match(token)
            if redirect:
                rest = token[redirect.end():]
                if not rest:
                    after_redirect = True
                elif not rest.startswith("&"):  # 2>&1 はファイル記述子であってパスではない
                    targets.append(rest)
            elif depth < MAX_SHELL_DEPTH and os.path.basename(token) in SHELL_RUNNERS:
                nested = shell_command_argument(tokens, index)
                if nested:
                    targets += bash_write_targets(nested, depth + 1)
            elif depth < MAX_SHELL_DEPTH and token == "eval":
                # eval は残りの引数を連結して評価する。連結してから同じ判定を当てる。
                targets += bash_write_targets(" ".join(tokens[index + 1:]), depth + 1)
            elif os.path.basename(token) in WRITING_COMMANDS:
                # sed が書き込むのは -i が付いたときだけ。
                writing = os.path.basename(token) != "sed" or any(
                    arg.startswith("-i") for arg in tokens
                )
            elif writing and not token.startswith("-"):
                if token[:3] in ("of=", "if="):  # dd
                    token = token[3:]
                targets.append(token)

        if ends_segment:
            writing = False

    return targets


def candidates(tool_input):
    """判定対象のパス。Bash はコマンド文字列から、他はツールの引数から取る。"""
    command = tool_input.get("command")
    if command:
        # shlex が解釈できないコマンドはここで例外になり、guard.sh が ask に倒す。
        # 判定できないものを「問題なし」として素通しにはしない。
        return bash_write_targets(command)

    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    return [path] if path else []


def main():
    payload = json.load(sys.stdin)
    patterns = list(DEFAULT_PROTECTED) + _common.option_list("protected_paths")

    for path in candidates(payload.get("tool_input", {})):
        resolved = os.path.expanduser(path)
        for pattern in patterns:
            if matches(resolved, pattern):
                _common.emit(REASON.format(pattern=pattern, path=path))
                return


if __name__ == "__main__":
    main()
