#!/bin/sh
# SessionStart 自己診断の fail-safe ラッパー。
#
# guard.sh と同じ思想。診断そのものが動かない場合でも黙らない。
# 診断できない状態は「異常なし」ではなく「生死不明」であり、それをユーザーに伝える。
set -u

emit_warning() {
	printf '{"systemMessage":"guardrails: %s","hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"guardrails: %s"}}\n' "$1" "$1"
	exit 0
}

root="${CLAUDE_PLUGIN_ROOT:-}"
[ -n "$root" ] || emit_warning "CLAUDE_PLUGIN_ROOT が未設定で自己診断できない。ガードレールの生死は不明"

py=$(command -v python3 || command -v python) || py=""
[ -n "$py" ] || emit_warning "python が無く自己診断できない。判定器も python に依存するため機能していない"

out=$("$py" "$root/scripts/selfcheck.py" 2>/dev/null) \
	|| emit_warning "自己診断が異常終了した。ガードレールの生死は不明"

[ -n "$out" ] && printf '%s\n' "$out"
exit 0
