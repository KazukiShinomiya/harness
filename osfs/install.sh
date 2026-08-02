#!/bin/sh
# OS/FS 層のガードレールを有効にする。
#
#   ./install.sh              rm-guard を ~/.local/bin/rm として設置
#   ./install.sh --uninstall
#   ./install.sh --status
#
# この層は Claude Code にも git にも依存しない。エージェントが暴走しても、
# ユーザー自身が手を滑らせても、同じように効く。
#
# chattr +i による書き込み禁止は別スクリプト（immutable.sh）。副作用の性質が
# 違うため、まとめて適用させない。
set -u

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
bindir="${HOME}/.local/bin"
target="${bindir}/rm"
source="${here}/rm-guard"
action=install

for arg in "$@"; do
	case "$arg" in
		--uninstall) action=uninstall ;;
		--status) action=status ;;
		-h|--help)
			sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
			exit 0
			;;
		*)
			printf 'unknown option: %s\n' "$arg" >&2
			exit 2
			;;
	esac
done

# PATH の中で bindir が /usr/bin より前にあるか。後ろにあると設置しても効かない。
path_position_ok() {
	_found_bin=0
	IFS=:
	for _dir in $PATH; do
		case "$_dir" in
			"$bindir") [ "$_found_bin" -eq 0 ] && _found_bin=1 ;;
			/usr/bin|/bin)
				unset IFS
				[ "$_found_bin" -eq 1 ]
				return $?
				;;
		esac
	done
	unset IFS
	return 1
}

show_status() {
	if [ -e "$target" ] || [ -L "$target" ]; then
		if [ "$(readlink -f "$target" 2>/dev/null)" = "$source" ]; then
			printf 'rm-guard: 設置済み  %s -> %s\n' "$target" "$source"
		else
			printf 'rm-guard: %s は別のものを指している\n' "$target"
			printf '  実体: %s\n' "$(readlink -f "$target" 2>/dev/null || printf '(不明)')"
		fi
	else
		printf 'rm-guard: 未設置\n'
	fi

	printf 'rm の解決先: %s\n' "$(command -v rm)"

	if command -v trash-put >/dev/null 2>&1; then
		printf 'trash-cli: あり  %s\n' "$(command -v trash-put)"
	else
		printf 'trash-cli: **無し**（設置しても rm は止まるだけになる）\n'
	fi

	if path_position_ok; then
		printf 'PATH: %s は /usr/bin より前\n' "$bindir"
	else
		printf 'PATH: **%s が /usr/bin より前に無い**。設置しても効かない\n' "$bindir"
	fi
}

case "$action" in
	status)
		show_status
		exit 0
		;;
	uninstall)
		if [ "$(readlink -f "$target" 2>/dev/null)" = "$source" ]; then
			HARNESS_RM_REAL=1 /usr/bin/rm -f "$target"
			printf '%s を外した\n' "$target"
		else
			printf '%s は rm-guard ではない。触らない\n' "$target"
		fi
		exit 0
		;;
esac

# --- 設置 ---
[ -x "$source" ] || {
	printf 'fatal: %s に実行権限が無い\n' "$source" >&2
	printf '  chmod +x %s\n' "$source" >&2
	exit 1
}

if ! command -v trash-put >/dev/null 2>&1; then
	printf 'fatal: trash-put が無い。先に導入すること:\n' >&2
	printf '  sudo apt install trash-cli\n' >&2
	printf '無い状態で設置すると rm が全て失敗するようになる。\n' >&2
	exit 1
fi

if [ -e "$target" ] || [ -L "$target" ]; then
	if [ "$(readlink -f "$target" 2>/dev/null)" = "$source" ]; then
		printf '既に設置されている: %s\n' "$target"
		exit 0
	fi
	printf 'fatal: %s が既にある。上書きしない\n' "$target" >&2
	printf '  実体: %s\n' "$(readlink -f "$target" 2>/dev/null || printf '(不明)')" >&2
	exit 1
fi

mkdir -p "$bindir"
ln -s "$source" "$target"

printf 'rm-guard を設置した:\n  %s -> %s\n\n' "$target" "$source"

if ! path_position_ok; then
	printf '注意: %s が PATH 上で /usr/bin より前に無い。このままでは効かない\n\n' "$bindir"
fi

printf '効くもの:\n'
printf '  rm したものはゴミ箱へ入る。trash-list で一覧、trash-restore で戻せる\n\n'
printf '効かないもの（過信しないこと）:\n'
printf '  sudo rm      secure_path のため /usr/bin/rm が呼ばれる\n'
printf '  find -delete / unlink / > によるファイルの切り詰め\n\n'
printf '脱出口:\n'
printf '  HARNESS_RM_REAL=1 rm ...\n\n'
printf 'ゴミ箱の掃除:\n'
printf '  trash-list / trash-empty 30   # 30 日より古いものを消す\n\n'
printf '解除:\n'
printf '  %s/install.sh --uninstall\n' "$here"
