# git フックの共通部品。POSIX sh のみ。
#
# この層は Claude Code に依存しない。シェルから直接 git を叩いても、別のエージェントが
# 動かしても効く。プラグイン側の PreToolUse フックが黙って死んでも、ここは生きている。
#
# 保護パターンは plugins/guardrails/scripts/protected_paths.py と意図的に重複させてある。
# git フックはプラグインの導入有無に関わらず単体で動く必要があるため、依存させない。
# 片方を変えたらもう片方も見ること。

# コミットされると困るもの。パス全体と basename の両方で照合する。
PROTECTED_PATTERNS='
.env
.env.*
*.pem
*.key
*.p12
*.pfx
id_rsa*
id_ed25519*
*credentials*
.ssh/*
.aws/*
.gnupg/*
'

# 強制 push と削除を止めるブランチ。git config guardrails.protectedBranches で上書きできる。
protected_branches() {
	branches=$(git config --get guardrails.protectedBranches 2>/dev/null) || branches=""
	[ -n "$branches" ] || branches="main master"
	printf '%s\n' "$branches"
}

# パスが保護対象か。0 なら該当（該当パターンを stdout に出す）。
is_protected_path() {
	path=$1
	base=${path##*/}
	# shellcheck disable=SC2086
	for pattern in $PROTECTED_PATTERNS; do
		case "$path" in
			$pattern) printf '%s\n' "$pattern"; return 0 ;;
		esac
		case "$base" in
			$pattern) printf '%s\n' "$pattern"; return 0 ;;
		esac
	done
	return 1
}

# 無効化されているか。事故ではなく明示的な意思表示のときだけ使うこと。
guardrails_disabled() {
	[ "$(git config --get guardrails.disable 2>/dev/null)" = "true" ]
}

# core.hooksPath はリポジトリ固有の .git/hooks を丸ごと無効にしてしまう。
# 各フックの最後にここを呼び、ローカルのフックがあれば委譲する。
chain_local_hook() {
	name=$1
	shift

	common_dir=$(git rev-parse --git-common-dir 2>/dev/null) || return 0
	local_hook="$common_dir/hooks/$name"

	[ -f "$local_hook" ] || return 0
	[ -x "$local_hook" ] || return 0

	# 自分自身を呼ばないこと。core.hooksPath がリポジトリ内を指している場合に無限再帰する。
	self_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P) || return 0
	hook_dir=$(CDPATH= cd -- "$(dirname -- "$local_hook")" && pwd -P) || return 0
	[ "$self_dir" != "$hook_dir" ] || return 0

	"$local_hook" "$@"
}

die() {
	printf '\n' >&2
	printf 'guardrails(git): %s\n' "$1" >&2
	shift
	for line in "$@"; do
		printf '  %s\n' "$line" >&2
	done
	printf '\n' >&2
	exit 1
}
