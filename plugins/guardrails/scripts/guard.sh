#!/bin/sh
# PreToolUse ガードレールの fail-safe ラッパー。
#
# 判定器（irreversible_ops.py）が動かない・落ちた場合、素通し（fail-open）にはせず
# 確認ダイアログ（ask）に倒す。deny で全作業を止めると壊れた瞬間に何もできなくなり、
# 素通しではガードレールの意味がないため、その中間を既定とする。
#
# 判定器の契約:
#   exit 0 + stdout に JSON  -> そのまま Claude Code へ渡す（検出あり）
#   exit 0 + stdout が空     -> 決定なし（通常フロー）
#   exit 非 0                -> 異常。ここで ask に倒す
set -u

emit_ask() {
	printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"guardrails: %s"}}\n' "$1"
	exit 0
}

py=$(command -v python3 || command -v python) || py=""
[ -n "$py" ] || emit_ask "python not found -- unable to evaluate the command, falling back to confirmation"

input=$(cat)
out=$(printf '%s' "$input" | "$py" "${CLAUDE_PLUGIN_ROOT}/scripts/irreversible_ops.py" 2>/dev/null) \
	|| emit_ask "checker failed -- unable to evaluate the command, falling back to confirmation"

[ -n "$out" ] && printf '%s\n' "$out"
exit 0
