#!/bin/sh
# PreToolUse ガードレールの fail-safe ラッパー。
#
#   guard.sh <判定器のファイル名>
#
# 判定器が動かない・落ちた場合、素通し（fail-open）にはせず確認ダイアログ（ask）に倒す。
# deny で全作業を止めると壊れた瞬間に何もできなくなり、素通しではガードレールの意味が
# ないため、その中間を既定とする。判定器の契約は _common.py を参照。
set -u

emit_ask() {
	printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"guardrails: %s"}}\n' "$1"
	exit 0
}

# 設定ミスでもツール呼び出しはブロックしない。exit 2 は Claude Code が
# 「ブロック」と解釈するため、ここで落ちると全呼び出しが止まってしまう。
checker="${1:-}"
[ -n "$checker" ] || emit_ask "no checker specified -- hooks.json may be misconfigured"

py=$(command -v python3 || command -v python) || py=""
[ -n "$py" ] || emit_ask "python not found -- unable to evaluate, falling back to confirmation"

input=$(cat)
out=$(printf '%s' "$input" | "$py" "${CLAUDE_PLUGIN_ROOT}/scripts/${checker}" 2>/dev/null) \
	|| emit_ask "checker failed (${checker}) -- unable to evaluate, falling back to confirmation"

[ -n "$out" ] && printf '%s\n' "$out"
exit 0
