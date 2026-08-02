#!/bin/sh
# 実装していない種類の hook を、黙って殺さずローカルへ委譲する。
#
#   _passthrough.sh <hook 名> [引数...]
#
# core.hooksPath を設定すると git は **そのディレクトリしか見ない**。
# したがって、ここに置かれていない種類の hook はリポジトリ固有の .git/hooks に
# 存在しても一切実行されない。commit-msg（commitlint 等）や post-merge が
# 何の警告も無く無効化される——このリポジトリが一貫して潰そうとしている
# 「黙って壊れる」そのもの。
#
# それを避けるため、guardrails が判定に使わない種類にも受け渡し専用の hook を置き、
# ローカルの実装をそのまま呼ぶ。標準入力も終了コードもそのまま伝わる。
set -u

name="${1:-}"
[ -n "$name" ] || exit 0
shift

. "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)/_lib.sh"

chain_local_hook "$name" "$@"
