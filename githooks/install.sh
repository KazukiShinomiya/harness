#!/bin/sh
# git 層のガードレールを有効にする。
#
#   ./install.sh            グローバル（全リポジトリ）に適用
#   ./install.sh --local    カレントのリポジトリだけに適用（試すとき用）
#   ./install.sh --uninstall
#
# core.hooksPath はリポジトリ固有の .git/hooks を丸ごと無効にする。各フックは最後に
# ローカルのフックへ委譲するので実害は出ないはずだが、既存の設定は上書きする前に見せる。
set -u

hooks_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
scope=--global
action=install

for arg in "$@"; do
	case "$arg" in
		--local) scope=--local ;;
		--uninstall) action=uninstall ;;
		-h|--help)
			sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
			exit 0
			;;
		*)
			printf 'unknown option: %s\n' "$arg" >&2
			exit 2
			;;
	esac
done

if [ "$action" = uninstall ]; then
	current=$(git config "$scope" --get core.hooksPath 2>/dev/null) || current=""
	if [ "$current" = "$hooks_dir" ]; then
		git config "$scope" --unset core.hooksPath
		printf 'core.hooksPath (%s) を解除した\n' "$scope"
	else
		printf 'core.hooksPath (%s) は %s を指していない。触らない\n' "$scope" "$hooks_dir"
		[ -n "$current" ] && printf '  現在の値: %s\n' "$current"
	fi
	exit 0
fi

for hook in pre-commit pre-push; do
	if [ ! -x "$hooks_dir/$hook" ]; then
		printf 'fatal: %s に実行権限が無い\n' "$hooks_dir/$hook" >&2
		printf '  chmod +x %s/pre-commit %s/pre-push\n' "$hooks_dir" "$hooks_dir" >&2
		exit 1
	fi
done

current=$(git config "$scope" --get core.hooksPath 2>/dev/null) || current=""
if [ -n "$current" ] && [ "$current" != "$hooks_dir" ]; then
	printf 'core.hooksPath (%s) は既に設定されている:\n' "$scope" >&2
	printf '  %s\n' "$current" >&2
	printf '上書きするなら先に解除すること: git config %s --unset core.hooksPath\n' "$scope" >&2
	exit 1
fi

git config "$scope" core.hooksPath "$hooks_dir"

printf 'core.hooksPath (%s) を設定した:\n  %s\n\n' "$scope" "$hooks_dir"
printf '効くもの:\n'
printf '  pre-commit  秘密情報（.env / *.pem / *.key 等）のコミットを止める\n'
printf '  pre-push    保護ブランチへの強制 push と削除を止める（既定 main master）\n\n'
printf '設定:\n'
printf '  git config guardrails.protectedBranches "main master release"\n'
printf '  git config guardrails.disable true      # このリポジトリでは切る\n\n'
printf '解除:\n'
printf '  %s/install.sh --uninstall%s\n' "$hooks_dir" "$([ "$scope" = --local ] && printf ' --local')"
