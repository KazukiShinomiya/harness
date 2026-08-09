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

  1. 新しいセッションを開き、Claude に自己診断の結果を尋ねる
       「起動時に入った guardrails の自己診断を、ツールを実行せずそのまま貼って」
     次の行が返るはず。
       guardrails: 有効（<path>、decision=...）
       session-harness: <path> を読み込んだ   （SESSION_STATE.md がある場合）
     診断は additionalContext で Claude にだけ渡るので**画面には出ない**。
     異常時だけ systemMessage が画面にも出る。黙っていることは無い。

  2. ask が確認として表示されるかを確かめる（対話セッションで）
       rm -f /tmp/guardrails-manual-check
     確認が出なければ、そのセッションでは検出しても素通しになる。
     ファイルは存在しないので副作用は無い。
     **同じ機・同じ版でもセッションによって出たり出なかったりする**（実測）。
     一度出ても保証にはならないので、確実に止めたいものは githooks/ と
     permissions/ の層へ寄せること（README 参照）。

EOF
