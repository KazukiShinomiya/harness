#!/bin/sh
# harness を導入する。
#
#   ./install.sh                  マーケットプレイス登録 + 両プラグイン導入
#   ./install.sh --guardrails     guardrails だけ
#   ./install.sh --dry-run        実行せず、走らせるコマンドを表示するだけ
#
# なぜスクリプトが要るか: プロジェクトの .claude/settings.json に
# extraKnownMarketplaces を書いても**効かない**（実測）。marketplace の登録は
# ユーザーが自分で行う必要があり、clone しただけでは有効にならない。
# 詳細は README の「他リポジトリへの展開」を参照。
set -u

MARKETPLACE=KazukiShinomiya/harness
plugins="guardrails session-harness"
dry=""

for arg in "$@"; do
	case "$arg" in
		--guardrails) plugins="guardrails" ;;
		--dry-run) dry=1 ;;
		-h|--help)
			sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'
			exit 0
			;;
		*)
			printf 'unknown option: %s\n' "$arg" >&2
			exit 2
			;;
	esac
done

run() {
	if [ -n "$dry" ]; then
		printf '  %s\n' "$*"
	else
		printf '\n$ %s\n' "$*"
		"$@" || exit 1
	fi
}

command -v claude >/dev/null 2>&1 || {
	printf 'fatal: claude が PATH に無い\n' >&2
	exit 1
}

[ -n "$dry" ] && printf '実行されるコマンド:\n'

run claude plugin marketplace add "$MARKETPLACE"
for p in $plugins; do
	run claude plugin install "$p@harness"
done

[ -n "$dry" ] && exit 0

cat <<'EOF'

導入した。次に確認すること。

  1. 新しいセッションを開き、起動時の文脈に次の行が出るか見る
       guardrails: 有効（<path>、decision=...）
       session-harness: <path> を読み込んだ   （SESSION_STATE.md がある場合）
     出なければ自己診断が警告を出しているはず。黙っていることは無い。

  2. ask が確認として表示される環境かを確かめる
       rm -f /tmp/guardrails-manual-check
     確認が出なければ、この環境では検出しても素通しになる。
     その場合は githooks/ と permissions/ の層を併用すること（README 参照）。

EOF
