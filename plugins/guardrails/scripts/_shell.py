"""判定器が共有する、シェルのコマンド文字列の分解。

以前は各判定器がコマンド全体を `shlex.split()` で一列の語にして照合していた。
そのせいで次のような書き方で抜けられた（2026-11-08 に実測。docs/redteam/2026-11-08/）。

- 区切りの前後に空白が無い: `cd x&&git push`、`git push|cat`、`(git push)`
- リダイレクトの前に空白が無い: `echo x>>~/.ssh/authorized_keys`
- `bash -lc '...'` のように `-c` がまとめ書きされている
- `$(...)` やバッククォートの中身

ここでは、コマンド文字列を単純コマンド（区切りで切った語の列）に分ける。そのうえで、
`bash -c` / `eval` / `$(...)` / バッククォートの中身も同じように分けて返す。
判定器は単純コマンドを一つずつ見ればよい。

**完全ではない。** 実行時に決まる変数展開、インタプリタの中身（`python -c`）、
MAX_DEPTH より深い入れ子は読めない。README に穴として書いてある。
"""

import os
import re
import shlex

# 入れ子を潜る深さ。現実の入れ子は浅い。文字列は潜るたびに短くなるので停止はするが、
# 際限なく潜る必要もない。tests/run.sh がこの境界（3 段は見る・4 段は見ない）を固定している。
MAX_DEPTH = 3

# `-c` の引数がそれ自体シェルコマンドになるもの。basename で照合する。
SHELL_RUNNERS = frozenset(("bash", "sh", "zsh", "dash", "ksh"))

# 引数を一つ取るシェルのオプション。`bash -o pipefail -c '...'` の `pipefail` を
# スクリプト名と取り違えないために要る。
SHELL_OPTIONS_WITH_ARG = frozenset(("-o", "+o", "-O", "+O", "--rcfile", "--init-file"))

# 語を区切る記号。改行も区切りとして扱う（既定の shlex は改行を空白として読み捨てる）。
_PUNCTUATION = "();<>|&\n"
_BOUNDARY_CHARS = frozenset(";&|()\n")


# シェルの演算子。長いものから順に照合する。
_OPERATORS = (
    "&>>", "<<<", "&&", "||", ";;", "|&", "&>", ">>", ">|", ">&", "<<", "<>", "<&",
    ";", "|", "&", ">", "<", "(", ")", "\n",
)


def _split_operators(token):
    """記号だけの語を、シェルの演算子の並びに切り直す。

    shlex は連続する記号を一つの語にまとめる。そのため `printf x;> file` の `;>` が
    区切りでもリダイレクトでもない語になり、リダイレクト先を見落としていた
    （2026-11-08、Codex のレビューで判明。実測）。引用符で囲まれた記号も同じ形で
    返ってくるので切ってしまうが、誤って確認が増える側なので許容する。
    """
    parts = []
    rest = token
    while rest:
        for operator in _OPERATORS:
            if rest.startswith(operator):
                parts.append(operator)
                rest = rest[len(operator):]
                break
        else:
            return [token]  # 演算子として読めない並び。手を付けずに返す
    return parts


def tokenize(command):
    """引用符を解釈しつつ、`&&` や `>>` などの記号を独立した語に切り出す。

    解釈できない文字列（閉じていない引用符など）では ValueError になる。
    判定器はそれを異常として非 0 で終わり、guard.sh が ask に倒す。
    """
    lexer = shlex.shlex(command, posix=True, punctuation_chars=_PUNCTUATION)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    tokens = []
    for token in lexer:
        if token and all(char in _PUNCTUATION for char in token):
            tokens += _split_operators(token)
        else:
            tokens.append(token)
    return tokens


def is_boundary(token):
    """`;` `&&` `|` `(` 改行など、単純コマンドの区切りか。"""
    return bool(token) and all(char in _BOUNDARY_CHARS for char in token)


def is_redirect(token):
    """`>` `>>` `2>` の `>`、`&>`、`>|`、`<` などのリダイレクト記号か。"""
    return bool(token) and ("<" in token or ">" in token) and all(char in "<>&|" for char in token)


def _split(tokens):
    commands = []
    current = []
    for index, token in enumerate(tokens):
        if is_boundary(token):
            if current:
                commands.append(current)
            current = []
            continue
        # `2>file` は `2` `>` `file` に切れる。`2` はファイル記述子であって引数ではない。
        if token.isdigit() and index + 1 < len(tokens) and is_redirect(tokens[index + 1]):
            continue
        current.append(token)
    if current:
        commands.append(current)
    return commands


def shell_command_argument(words, index):
    """`bash -c '<cmd>'` の `<cmd>` を返す。無ければ None。

    `-c` は `-lc` や `-ec` のようにまとめ書きされることが多い。以前はそれを見落としていた。
    `-c` より前に非オプションが来たら、それはスクリプトファイルの実行であって
    文字列の評価ではない（`bash script.sh`）。中身を静的には読めないので対象外。
    """
    position = index + 1
    while position < len(words):
        token = words[position]
        if token in SHELL_OPTIONS_WITH_ARG:
            position += 2
            continue
        if token.startswith("-") and not token.startswith("--") and "c" in token[1:]:
            return words[position + 1] if position + 1 < len(words) else None
        if not token.startswith(("-", "+")):
            return None
        position += 1
    return None


def _nested(words):
    """単純コマンドの中で、文字列として評価されるコマンドを返す。"""
    found = []
    for index, word in enumerate(words):
        if os.path.basename(word) in SHELL_RUNNERS:
            inner = shell_command_argument(words, index)
            if inner:
                found.append(inner)
        elif word == "eval":
            # eval は残りの引数を連結して評価する。
            found.append(" ".join(words[index + 1:]))
    return found


def substitutions(command):
    """`$(...)` とバッククォートの中身を返す。

    二重引用符の中でも展開されるので、引用符を見ずに文字列から拾う。単一引用符の中の
    ものまで拾ってしまうが、誤って確認が増える側なので許容する。
    """
    found = []
    start = command.find("$(")
    while start >= 0:
        depth = 0
        end = start + 1
        while end < len(command):
            if command[end] == "(":
                depth += 1
            elif command[end] == ")":
                depth -= 1
                if depth == 0:
                    break
            end += 1
        found.append(command[start + 2:end])
        start = command.find("$(", start + 2)
    found += re.findall(r"`([^`]*)`", command)
    return found


def simple_commands(command, depth=0):
    """コマンド文字列を単純コマンド（語のリスト）に分けて返す。

    `bash -c` / `eval` / `$(...)` / バッククォートの中身は、MAX_DEPTH 段まで潜って
    同じように分け、外側の単純コマンドの直後に並べる。
    """
    expanded = []
    for words in _split(tokenize(command)):
        expanded.append(words)
        if depth < MAX_DEPTH:
            for inner in _nested(words):
                expanded += simple_commands(inner, depth + 1)
    if depth < MAX_DEPTH:
        for inner in substitutions(command):
            expanded += simple_commands(inner, depth + 1)
    return expanded
