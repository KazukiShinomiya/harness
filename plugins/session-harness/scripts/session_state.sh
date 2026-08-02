#!/bin/sh
# SessionStart で状態ファイルを注入する。
#
# 注入の失敗は危険ではない（偽の安心を作らない）ので止めも確認もしない。
# ただし黙りもしない。python が無ければ注入は決して働かないので、それを伝える。
set -u

emit_warning() {
	printf '{"systemMessage":"session-harness: %s","hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"session-harness: %s"}}\n' "$1" "$1"
	exit 0
}

root="${CLAUDE_PLUGIN_ROOT:-}"
[ -n "$root" ] || emit_warning "CLAUDE_PLUGIN_ROOT が未設定でセッション状態を読み込めない"

py=$(command -v python3 || command -v python) || py=""
[ -n "$py" ] || emit_warning "python が無くセッション状態を読み込めない。前回の経緯は引き継がれていない"

exec "$py" "$root/scripts/session_state.py"
