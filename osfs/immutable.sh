#!/bin/sh
# chattr +i でファイルを書き換え不能にする。root でも上書き・削除できなくなる
# （root は属性を外せるが、その操作が明示的に必要になる）。
#
#   ./immutable.sh status              守れる候補と現在の属性を出す
#   ./immutable.sh lock   <path>...    +i を付ける（sudo が要る）
#   ./immutable.sh unlock <path>...    -i を外す（sudo が要る）
#
# **既定では何も適用しない。** どれを固めるかは副作用を見て自分で選ぶこと。
# この層の副作用は他の層より重い——固めたファイルは自分でも編集できなくなる。
# 広く掛けすぎると作業が止まり、結局まるごと外される。
#
# ext4 等が必要。tmpfs や Windows マウント（/mnt/c）では効かない。
# なお harness の permissions/deny-recommended.json は chattr を拒否対象に
# 入れてあるため、このスクリプトは Claude Code からは実行できない。手で叩くこと。
set -u

# 候補と、固めたときに何が動かなくなるか。嘘を書かないこと。
# <パス>|<守るもの>|<副作用>
CANDIDATES="\
${HOME}/.gitconfig|core.hooksPath（git 層の入口）|git config --global が全て失敗する
${HOME}/.claude/settings.json|enabledPlugins と permissions.deny|Claude Code 自身が設定を書けなくなる（/plugin での有効化・権限の追加も含む）
${HOME}/.ssh/authorized_keys|鍵の追加による侵入経路|鍵の追加・削除が手作業になる"

usage() { sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; }

show_status() {
	printf '候補（既定では何も適用していない）:\n\n'
	printf '%s\n' "$CANDIDATES" | while IFS='|' read -r path guards effect; do
		[ -n "$path" ] || continue
		if [ -e "$path" ]; then
			attrs=$(lsattr -d -- "$path" 2>/dev/null | awk '{print $1}')
			case "$attrs" in
				*i*) state='固めてある (+i)' ;;
				'')  state='属性を読めない（この FS では chattr が効かない可能性）' ;;
				*)   state='通常' ;;
			esac
		else
			state='ファイルが無い'
		fi
		printf '  %s\n' "$path"
		printf '    状態  : %s\n' "$state"
		printf '    守る  : %s\n' "$guards"
		printf '    代償  : %s\n\n' "$effect"
	done

	printf '注意: symlink には +i を掛けても意味が薄い。実体側に掛けること。\n'
	printf '  例: %s は実体が %s のことがある\n' \
		"${HOME}/.claude/settings.json" "$(readlink -f "${HOME}/.claude/settings.json" 2>/dev/null || printf '(未解決)')"
}

apply() {
	flag=$1
	shift
	[ $# -gt 0 ] || {
		printf 'パスを指定すること\n' >&2
		exit 2
	}

	command -v chattr >/dev/null 2>&1 || {
		printf 'fatal: chattr が無い\n' >&2
		exit 1
	}

	for path in "$@"; do
		if [ ! -e "$path" ]; then
			printf 'skip: %s は存在しない\n' "$path" >&2
			continue
		fi
		# symlink を渡されたら実体を固める。symlink 自体を固めても中身は守れない。
		real=$(readlink -f -- "$path")
		if [ "$real" != "$path" ]; then
			printf '注: %s は %s への symlink。実体側に適用する\n' "$path" "$real"
		fi
		if sudo chattr "$flag" -- "$real"; then
			printf '%s %s\n' "$flag" "$real"
		else
			printf 'fatal: chattr %s に失敗した: %s\n' "$flag" "$real" >&2
			printf '  この FS が対応していない可能性がある（tmpfs / /mnt/c 等）\n' >&2
			exit 1
		fi
	done
}

cmd=${1:-status}
[ $# -gt 0 ] && shift

case "$cmd" in
	status) show_status ;;
	lock) apply +i "$@" ;;
	unlock) apply -i "$@" ;;
	-h|--help) usage ;;
	*)
		printf 'unknown command: %s\n\n' "$cmd" >&2
		usage >&2
		exit 2
		;;
esac
