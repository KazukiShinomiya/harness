#!/bin/sh
# harness の回帰テスト。
#
#   tests/run.sh
#
# 今日まで、動作確認はすべて使い捨てのコマンドで行っていた。それでは壊れたときに
# 黙って壊れる——このリポジトリが一貫して潰そうとしている失敗そのものになる。
# ここで確かめているのは、実際に一度は手で確認した項目だけ。
#
# 副作用は持たない。git のテストは隔離した一時リポジトリ（HOME ごと差し替え）で行い、
# ユーザーの設定にも既存のリポジトリにも触れない。
set -u

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
GUARD="$ROOT/plugins/guardrails"
SESS="$ROOT/plugins/session-harness"
TMP=$(mktemp -d) || exit 1
trap 'rm -rf "$TMP"' EXIT INT TERM

pass=0
fail=0

ok()  { pass=$((pass + 1)); printf '  ok    %s\n' "$1"; }
ng()  { fail=$((fail + 1)); printf '  FAIL  %s\n' "$1"; }

# contains <説明> <期待する部分文字列> <実際>
contains() {
	case "$3" in
		*"$2"*) ok "$1" ;;
		*) ng "$1 -- '$2' が見当たらない: $(printf '%.90s' "$3")" ;;
	esac
}

# empty <説明> <実際>
empty() {
	if [ -z "$2" ]; then ok "$1"; else ng "$1 -- 出力があった: $(printf '%.90s' "$2")"; fi
}

judge() { printf '%s' "$2" | python3 "$GUARD/scripts/$1" 2>/dev/null; }

# json.dump は既定で非 ASCII を \uXXXX に符号化するため、生の JSON には日本語が現れない。
# 文言を比べる前に復号する。systemMessage と additionalContext を続けて出す。
decode() {
	python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
print(d.get("systemMessage", ""))
print(d.get("hookSpecificOutput", {}).get("additionalContext", ""))
' 2>/dev/null
}

section() { printf '\n%s\n' "$1"; }

# ---------------------------------------------------------------- 判定器
section '判定器'

out=$(judge irreversible_ops.py '{"tool_input":{"command":"rm -rf /tmp/x"}}')
contains '不可逆操作を検出する' '"permissionDecision"' "$out"

out=$(judge irreversible_ops.py '{"tool_input":{"command":"ls -la /tmp"}}')
empty '無害なコマンドは素通しする' "$out"

# トークン境界で判定する。引用符の中のパターンで発火してはいけない。
out=$(judge irreversible_ops.py '{"tool_input":{"command":"echo \"git push はまだしない\""}}')
empty '引用符の中のパターンで発火しない' "$out"

out=$(judge protected_paths.py '{"tool_input":{"file_path":"/tmp/x/.env"}}')
contains '保護パスを検出する' 'protected path' "$out"

out=$(judge protected_paths.py '{"tool_input":{"file_path":"/tmp/x/main.py"}}')
empty '通常のパスは素通しする' "$out"

# ---------------------------------------------------------------- guard.sh
section 'guard.sh の fail-safe'

out=$(printf '{}' | sh "$GUARD/scripts/guard.sh" 2>/dev/null)
contains '判定器名が無ければ ask に倒す' '"ask"' "$out"

out=$(printf '{}' | CLAUDE_PLUGIN_ROOT="$GUARD" PATH=/nonexistent /bin/sh "$GUARD/scripts/guard.sh" x 2>/dev/null)
contains 'python が無ければ ask に倒す' '"ask"' "$out"

# exit 2 は「ブロック」と解釈されるため決して返してはいけない。
printf '{}' | sh "$GUARD/scripts/guard.sh" >/dev/null 2>&1
[ $? -ne 2 ] && ok 'exit 2 を返さない' || ng 'exit 2 を返した'

# ---------------------------------------------------------------- 自己診断
section 'guardrails の自己診断'

sc() { printf '{}' | CLAUDE_PLUGIN_ROOT="$1" sh "$GUARD/scripts/selfcheck.sh" 2>/dev/null; }

out=$(sc "$GUARD")
case "$out" in
	*systemMessage*) ng '正常時は警告を出さない' ;;
	*) contains '正常時は有効と報告する' '有効' "$(printf '%s' "$out" | decode)" ;;
esac

out=$(printf '{}' | env -u CLAUDE_PLUGIN_ROOT sh "$GUARD/scripts/selfcheck.sh" 2>/dev/null)
contains 'root 未設定なら警告する' 'systemMessage' "$out"

# 判定器が黙る（検出できない）状態を作って、気付けることを確かめる。
cp -r "$GUARD" "$TMP/broken"
printf '#!/usr/bin/env python3\nimport sys\nsys.stdin.read()\n' > "$TMP/broken/scripts/irreversible_ops.py"
out=$(sc "$TMP/broken")
contains '判定器が黙ると警告する' 'systemMessage' "$out"

# ---------------------------------------------------------------- session-harness
section 'session-harness'

ss() { printf '{}' | CLAUDE_PLUGIN_ROOT="$SESS" CLAUDE_PROJECT_DIR="$1" sh "$SESS/scripts/session_state.sh" 2>/dev/null; }

mkdir -p "$TMP/withstate" "$TMP/nostate" "$TMP/emptystate"
printf '# SESSION_STATE\n\n続き。\n' > "$TMP/withstate/SESSION_STATE.md"
: > "$TMP/emptystate/SESSION_STATE.md"

contains '状態ファイルを読み込む'     'を読み込んだ' "$(ss "$TMP/withstate"   | decode)"
contains '無いときは探した場所を伝える' 'が無いため'   "$(ss "$TMP/nostate"     | decode)"
contains '空のときはその旨を伝える'     'は空だった'   "$(ss "$TMP/emptystate"  | decode)"

out=$(printf '{}' | CLAUDE_PLUGIN_ROOT="$SESS" PATH=/nonexistent /bin/sh "$SESS/scripts/session_state.sh" 2>/dev/null)
contains 'python が無ければ警告する' 'systemMessage' "$out"

# ---------------------------------------------------------------- permissions
section 'permissions/apply.py'

printf '{"permissions":{"allow":["Bash(ls:*)"]}}' > "$TMP/settings.json"
before=$(cat "$TMP/settings.json")

python3 "$ROOT/permissions/apply.py" --to "$TMP/settings.json" >/dev/null 2>&1
[ "$(cat "$TMP/settings.json")" = "$before" ] && ok '既定は dry-run で書き換えない' || ng 'dry-run で書き換えた'

python3 "$ROOT/permissions/apply.py" --to "$TMP/settings.json" --write >/dev/null 2>&1
n=$(python3 -c "import json;print(len(json.load(open('$TMP/settings.json'))['permissions'].get('deny',[])))")
[ "$n" -gt 0 ] && ok '--write で deny が入る' || ng '--write で deny が入らない'
n=$(python3 -c "import json;print(len(json.load(open('$TMP/settings.json'))['permissions'].get('allow',[])))")
[ "$n" -eq 1 ] && ok '既存の allow を壊さない' || ng "既存の allow が壊れた ($n)"

out=$(python3 "$ROOT/permissions/apply.py" --to "$TMP/settings.json" 2>&1)
contains '再実行は冪等' '追加するものは無い' "$out"

# ---------------------------------------------------------------- git 層
section 'githooks（隔離リポジトリ）'

export HOME="$TMP/home"
mkdir -p "$HOME"
git init -q --bare "$TMP/remote.git"
git init -q "$TMP/work"
cd "$TMP/work" || exit 1
git config user.name t
git config user.email t@example.com
git config core.hooksPath "$ROOT/githooks"
git remote add origin "$TMP/remote.git"

echo hello > app.txt
git add app.txt
git commit -qm first >/dev/null 2>&1
[ "$(git rev-list --count HEAD)" = 1 ] && ok '通常のコミットは通る' || ng '通常のコミットが止まった'

echo 'SECRET=1' > .env
git add -f .env
git commit -qm secret >/dev/null 2>&1
[ "$(git rev-list --count HEAD)" = 1 ] && ok '.env のコミットを止める' || ng '.env のコミットが通った'

git commit -qm secret --no-verify >/dev/null 2>&1
[ "$(git rev-list --count HEAD)" = 2 ] && ok '--no-verify なら通す' || ng '--no-verify で通らない'

BR=$(git branch --show-current)
git push -q origin "$BR" >/dev/null 2>&1
remote_before=$(git -C "$TMP/remote.git" rev-parse "$BR")

git reset -q --hard HEAD~1
echo other > app.txt
git add app.txt
git commit -qm rewritten --no-verify >/dev/null 2>&1
git push -f origin "$BR" >/dev/null 2>&1
[ "$(git -C "$TMP/remote.git" rev-parse "$BR")" = "$remote_before" ] \
	&& ok '保護ブランチへの強制 push を止める' || ng '強制 push が通った'

git push origin --delete "$BR" >/dev/null 2>&1
git -C "$TMP/remote.git" rev-parse --verify "$BR" >/dev/null 2>&1 \
	&& ok '保護ブランチの削除を止める' || ng 'ブランチが消えた'

git checkout -q -b feature
git push -q origin feature >/dev/null 2>&1
git commit -q --amend -m amended --no-verify >/dev/null 2>&1
if git push -f -q origin feature >/dev/null 2>&1; then
	ok '保護外ブランチなら強制 push を通す'
else
	ng '保護外ブランチで誤爆した'
fi

mkdir -p .git/hooks
printf '#!/bin/sh\ntouch "%s/chained"\n' "$TMP" > .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
echo x > b.txt
git add b.txt
git commit -qm chain >/dev/null 2>&1
[ -f "$TMP/chained" ] && ok 'ローカルの .git/hooks へ委譲する' || ng '委譲されなかった'

# ---------------------------------------------------------------- 保護パターンの整合
section '保護パターンの整合（意図的な重複）'

for pat in '.env' '*.pem' '*.key'; do
	in_git=$(grep -cF -- "$pat" "$ROOT/githooks/_lib.sh")
	in_py=$(grep -cF -- "$pat" "$GUARD/scripts/protected_paths.py")
	if [ "$in_git" -gt 0 ] && [ "$in_py" -gt 0 ]; then
		ok "両層に $pat がある"
	else
		ng "$pat が片方にしかない (git=$in_git py=$in_py)"
	fi
done

# ----------------------------------------------------------------
printf '\n%s\n' '----------------------------------------'
printf '  成功 %d / 失敗 %d\n\n' "$pass" "$fail"
[ "$fail" -eq 0 ] || exit 1
