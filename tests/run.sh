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
# 後始末は必ず本物の rm で行う。この機には osfs/rm-guard が入っていることがあり、
# 素の `rm` だとテストの残骸が丸ごとゴミ箱へ送られる（しかも隔離用の偽 HOME ごと
# 移そうとして失敗し、残骸が消えない）。
trap 'HARNESS_RM_REAL=1 /usr/bin/rm -rf "$TMP"' EXIT INT TERM

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

# --- rm はオプションの綴りで抜けられてはいけない ---
# 以前は "rm -rf" "rm -r" "rm -f" を literal で並べていたため、順序を変えた
# "rm -fr" が素通りしていた。綴りの列挙では必ず取りこぼす。
for spelling in 'rm -rf /tmp/x' 'rm -fr /tmp/x' 'rm -Rf /tmp/x' 'rm -r -f /tmp/x' \
	'rm --recursive --force /tmp/x' 'sudo /bin/rm -f /tmp/x'; do
	out=$(judge irreversible_ops.py "$(printf '{"tool_input":{"command":"%s"}}' "$spelling")")
	contains "綴りを変えても拾う: $spelling" '"permissionDecision"' "$out"
done

# git rm は追跡下のファイルしか消さず git から戻せる。
out=$(judge irreversible_ops.py '{"tool_input":{"command":"git rm -r foo"}}')
empty 'git rm では発火しない' "$out"

# 単独の "--build" は docker と無関係なコマンドで誤爆していた。
out=$(judge irreversible_ops.py '{"tool_input":{"command":"make --build"}}')
empty '無関係な --build で発火しない' "$out"

out=$(judge irreversible_ops.py '{"tool_input":{"command":"docker compose up --build"}}')
contains 'docker compose up は拾う' '"permissionDecision"' "$out"

# --- Bash 経由の書き込みも保護パスを見る ---
# Edit ツールでは止まるのにリダイレクトなら通るのでは、守っていることにならない。
for writing in 'echo x >> /home/ubuntu/.ssh/authorized_keys' 'echo x >/tmp/p/.env' \
	'tee -a /tmp/p/.env' 'cp /tmp/p/secret.pem /tmp/b' 'sed -i s/a/b/ /tmp/p/.env' \
	'dd if=/dev/zero of=/tmp/p/server.key'; do
	out=$(judge protected_paths.py "$(printf '{"tool_input":{"command":"%s"}}' "$writing")")
	contains "Bash 経由の書き込みを拾う: $writing" 'protected path' "$out"
done

# 読み取りは対象にしない。ここまで拾うと日常操作が確認だらけになる。
out=$(judge protected_paths.py '{"tool_input":{"command":"cat /tmp/p/.env"}}')
empty '読み取りでは発火しない' "$out"

# 2>&1 はファイル記述子であってパスではない。
out=$(judge protected_paths.py '{"tool_input":{"command":"make build 2>&1 | tee /tmp/log"}}')
empty 'ファイル記述子をパスと誤解しない' "$out"

out=$(judge protected_paths.py '{"tool_input":{"command":"echo hi > /tmp/plain.txt"}}')
empty '通常のリダイレクトは素通しする' "$out"

# ---------------------------------------------------------------- userConfig
section 'userConfig（multiple の直列化）'

# v2.1.220 で実測した形式そのものを入力にする。Claude Code は multiple: true の値を
# JavaScript の String(配列) で渡す——カンマ区切り、区切りにスペースなし。
# judge_opt <環境変数名> <値> <判定器> <入力>
judge_opt() {
	printf '%s' "$4" | env "$1=$2" python3 "$GUARD/scripts/$3" 2>/dev/null
}

out=$(judge_opt CLAUDE_PLUGIN_OPTION_EXTRA_PATTERNS 'flyctl deploy,terraform apply' \
	irreversible_ops.py '{"tool_input":{"command":"terraform apply"}}')
contains 'カンマ区切りの追加パターンが効く' '"permissionDecision"' "$out"

# 要素内のスペースは区切りではない。2 語のパターンが 1 件として保たれること。
out=$(judge_opt CLAUDE_PLUGIN_OPTION_EXTRA_PATTERNS 'flyctl deploy,terraform apply' \
	irreversible_ops.py '{"tool_input":{"command":"flyctl deploy --now"}}')
contains '要素内のスペースを区切りにしない' 'flyctl deploy' "$out"

# 空要素と前後の空白は捨てる。空文字のパターンは全コマンドに一致してしまう。
out=$(judge_opt CLAUDE_PLUGIN_OPTION_EXTRA_PATTERNS ' , ,  ' \
	irreversible_ops.py '{"tool_input":{"command":"ls -la /tmp"}}')
empty '空要素で誤爆しない' "$out"

out=$(judge_opt CLAUDE_PLUGIN_OPTION_PROTECTED_PATHS '*/secrets.yml,*.tfstate' \
	protected_paths.py '{"tool_input":{"file_path":"/tmp/x/main.tfstate"}}')
contains '追加の保護パスが効く' 'protected path' "$out"

out=$(judge irreversible_ops.py '{"tool_input":{"command":"terraform apply"}}')
empty '未設定なら既定パターンのみ' "$out"

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

# 自己診断は git config / HOME / PATH を読んで四層すべてを実測する。テストの結果が
# この機の導入状況で変わらないよう、隔離した環境を既定として渡す。読み取りしかしない
# ので副作用は無い。git はリポジトリの外（$TMP）から呼ぶ——このリポジトリ自身の
# ローカル設定を拾わせないため。
SCHOME="$TMP/schome"
SCBIN="$TMP/scbin"
mkdir -p "$SCHOME/.claude" "$SCBIN"
: > "$TMP/gitconfig-empty"

# sc <CLAUDE_PLUGIN_ROOT> [HOME] [PATH] [GIT_CONFIG_GLOBAL]
sc() {
	(cd "$TMP" && printf '{}' | env -u CLAUDE_PROJECT_DIR \
		HOME="${2:-$SCHOME}" PATH="${3:-/usr/bin:/bin}" \
		GIT_CONFIG_GLOBAL="${4:-$TMP/gitconfig-empty}" GIT_CONFIG_SYSTEM=/dev/null \
		CLAUDE_PLUGIN_ROOT="$1" sh "$GUARD/scripts/selfcheck.sh" 2>/dev/null)
}

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

# ask は確認ダイアログが出ないことがある。v2.1.226 では同じ機・同じ版でもセッションに
# よって割れた（素通りした側でもフックは発火し deny は効いた。落ちるのは ask だけ）。
# 出ない版では「検出しているのに何も起きない」が静かに続くため、手動確認の手順を
# 添えることだけが気付く手がかりになる。deny に切り替えた環境には無用なので出さない。
sc_decision() {
	(cd "$TMP" && printf '{}' | env -u CLAUDE_PROJECT_DIR \
		HOME="$SCHOME" PATH="/usr/bin:/bin" \
		GIT_CONFIG_GLOBAL="$TMP/gitconfig-empty" GIT_CONFIG_SYSTEM=/dev/null \
		CLAUDE_PLUGIN_OPTION_DECISION="$1" \
		CLAUDE_PLUGIN_ROOT="$GUARD" sh "$GUARD/scripts/selfcheck.sh" 2>/dev/null)
}

out=$(sc_decision ask | decode)
contains 'ask なら手動確認の手順を添える' 'rm -f /tmp/guardrails-manual-check' "$out"
contains 'ask なら版で挙動が変わることを言う' 'v2.1.226' "$out"

out=$(sc_decision deny | decode)
case "$out" in
	*guardrails-manual-check*) ng 'deny なら手動確認の手順は出さない' ;;
	*) ok 'deny なら手動確認の手順は出さない' ;;
esac

# ---------------------------------------------------------------- 四層の診断
section '自己診断（四層）'

# 未適用は異常ではない。層を入れていない環境の方が多いので、報告はしても警告はしない。
# ここで警告すると毎セッション鳴り、やがて誰も読まなくなる。
out=$(sc "$GUARD")
contains '未適用の git 層を報告する'         'git 層: 未適用'         "$(printf '%s' "$out" | decode)"
contains '未適用の permissions 層を報告する' 'permissions 層: 未適用' "$(printf '%s' "$out" | decode)"
contains '未適用の OS/FS 層を報告する'       'OS/FS 層: 未適用'       "$(printf '%s' "$out" | decode)"
case "$out" in
	*systemMessage*) ng '未適用の層では警告しない' ;;
	*) ok '未適用の層では警告しない' ;;
esac

# core.hooksPath が壊れたパスを指していても git は黙って hook を全て飛ばす。
printf '[core]\n\thooksPath = %s/absent-hooks\n' "$TMP" > "$TMP/gitconfig-broken"
out=$(sc "$GUARD" "$SCHOME" "/usr/bin:/bin" "$TMP/gitconfig-broken")
contains 'core.hooksPath が壊れていれば警告する' 'systemMessage' "$out"

printf '[core]\n\thooksPath = %s\n' "$ROOT/githooks" > "$TMP/gitconfig-ok"
out=$(sc "$GUARD" "$SCHOME" "/usr/bin:/bin" "$TMP/gitconfig-ok" | decode)
contains 'harness の githooks を指していれば有効' 'git 層: 有効' "$out"

printf '{"permissions":{"deny":["Bash(dd:*)","Bash(shutdown:*)"]}}' > "$SCHOME/.claude/settings.json"
out=$(sc "$GUARD" | decode)
contains 'deny の件数を数える' 'deny 2 件' "$out"

# 読めない設定ファイルは「deny 0 件」と区別する。前者は故障、後者は未適用。
printf '{"permissions":' > "$SCHOME/.claude/settings.json"
out=$(sc "$GUARD")
contains '読めない設定ファイルを警告する' 'systemMessage' "$out"
HARNESS_RM_REAL=1 /usr/bin/rm -f "$SCHOME/.claude/settings.json"

ln -s "$ROOT/osfs/rm-guard" "$SCBIN/rm"
printf '#!/bin/sh\nexit 0\n' > "$SCBIN/trash-put"
chmod +x "$SCBIN/trash-put"
out=$(sc "$GUARD" "$SCHOME" "$SCBIN:/usr/bin:/bin" | decode)
contains 'PATH の rm が rm-guard なら有効' 'OS/FS 層: 有効' "$out"

# ゴミ箱が無ければ rm-guard は全ての rm を止める。効いているが壊れている状態。
# この機に trash-cli が入っていても影響されないよう、PATH は必要なものだけにする。
SCBIN_BARE="$TMP/scbin-bare"
mkdir -p "$SCBIN_BARE"
ln -s "$ROOT/osfs/rm-guard" "$SCBIN_BARE/rm"
for tool in sh python3 git; do
	ln -s "$(command -v "$tool")" "$SCBIN_BARE/$tool"
done
out=$(sc "$GUARD" "$SCHOME" "$SCBIN_BARE")
contains 'ゴミ箱が無ければ警告する' 'systemMessage' "$out"

# 設置してあっても PATH の並びが違えば効かない。効かないことは何も起こさないので、
# こちらから見に行かないと気付けない。
SCHOME_UNUSED="$TMP/schome-pathmiss"
mkdir -p "$SCHOME_UNUSED/.local/bin"
ln -s "$ROOT/osfs/rm-guard" "$SCHOME_UNUSED/.local/bin/rm"
out=$(sc "$GUARD" "$SCHOME_UNUSED")
contains '設置済みでも PATH が拾わなければ警告する' 'systemMessage' "$out"

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

# ---------------------------------------------------------------- OS/FS 層
section 'osfs（rm-guard）'

RM="$ROOT/osfs/rm-guard"
FAKEBIN="$TMP/fakebin"
mkdir -p "$FAKEBIN" "$TMP/rmwork"
# 引数を記録するだけの trash-put。実際には何も消さないので副作用が出ない。
printf '#!/bin/sh\nfor a in "$@"; do [ "$a" = "--" ] && continue; printf "%%s\\n" "$a" >> "$TRASH_LOG"; done\n' \
	> "$FAKEBIN/trash-put"
chmod +x "$FAKEBIN/trash-put"
export TRASH_LOG="$TMP/trashlog"
: > "$TRASH_LOG"

touch "$TMP/rmwork/a.txt" "$TMP/rmwork/b with space.txt"

# オプションは trash-put へ渡さない。パスだけが、空白を保ったまま渡ること。
PATH="$FAKEBIN:$PATH" sh "$RM" -rf "$TMP/rmwork/a.txt" "$TMP/rmwork/b with space.txt" >/dev/null 2>&1
contains 'オプションを剥がしてパスを渡す' 'a.txt' "$(cat "$TRASH_LOG")"
contains '空白を含むパスを壊さない' 'b with space.txt' "$(cat "$TRASH_LOG")"

# ゴミ箱が使えないときに本物の rm へ落ちてしまうと、黙って破壊することになる。
# この機に trash-cli が入っていても「無い」状況を作れるよう PATH ごと外す
# （rm-guard はこの判定までシェル組み込みと絶対パスしか使わない）。
: > "$TRASH_LOG"
PATH=/nonexistent sh "$RM" -rf "$TMP/rmwork/a.txt" >/dev/null 2>&1
if [ -e "$TMP/rmwork/a.txt" ]; then
	ok 'trash-put が無ければ消さずに止まる'
else
	ng 'trash-put が無いのにファイルが消えた'
fi

PATH="$FAKEBIN:$PATH" sh "$RM" -f "$TMP/does-not-exist" >/dev/null 2>&1
[ $? -eq 0 ] && ok '-f なら存在しないパスでも成功する' || ng '-f で失敗した'

PATH="$FAKEBIN:$PATH" sh "$RM" "$TMP/does-not-exist" >/dev/null 2>&1
[ $? -ne 0 ] && ok '-f 無しで存在しないパスは失敗する' || ng '存在しないパスで成功した'

# 脱出口。ここが壊れると本物の rm へ戻れなくなる。
touch "$TMP/rmwork/real.txt"
HARNESS_RM_REAL=1 PATH="$FAKEBIN:$PATH" sh "$RM" -f "$TMP/rmwork/real.txt" >/dev/null 2>&1
[ ! -e "$TMP/rmwork/real.txt" ] && ok 'HARNESS_RM_REAL=1 で本物の rm へ抜ける' \
	|| ng '脱出口が働かない'

# `--` の後ろはオプションに見えてもパス。
: > "$TRASH_LOG"
touch -- "$TMP/rmwork/-rf"
PATH="$FAKEBIN:$PATH" sh "$RM" -- "$TMP/rmwork/-rf" >/dev/null 2>&1
contains '-- 以降はオプションに見えてもパス' '/-rf' "$(cat "$TRASH_LOG")"

section 'osfs（install.sh）'

OSFS_HOME="$TMP/osfshome"
mkdir -p "$OSFS_HOME/.local/bin"

# ゴミ箱が無い状態で設置すると、あらゆる rm が止まるようになる。設置を拒むこと。
out=$(HOME="$OSFS_HOME" PATH=/nonexistent sh "$ROOT/osfs/install.sh" 2>&1)
[ -e "$OSFS_HOME/.local/bin/rm" ] && ng 'trash-cli 不在でも設置した' \
	|| ok 'trash-cli が無ければ設置しない'

out=$(HOME="$OSFS_HOME" PATH="$FAKEBIN:$PATH" sh "$ROOT/osfs/install.sh" 2>&1)
[ -L "$OSFS_HOME/.local/bin/rm" ] && ok '設置すると ~/.local/bin/rm ができる' \
	|| ng "設置できなかった: $(printf '%.60s' "$out")"

out=$(HOME="$OSFS_HOME" PATH="$FAKEBIN:$PATH" sh "$ROOT/osfs/install.sh" --status 2>&1)
contains '--status が設置済みと報告する' '設置済み' "$out"

out=$(HOME="$OSFS_HOME" PATH="$FAKEBIN:$PATH" sh "$ROOT/osfs/install.sh" 2>&1)
contains '再実行しても壊さない' '既に設置されている' "$out"

HOME="$OSFS_HOME" PATH="$FAKEBIN:$PATH" sh "$ROOT/osfs/install.sh" --uninstall >/dev/null 2>&1
[ ! -e "$OSFS_HOME/.local/bin/rm" ] && ok '--uninstall で外れる' || ng '外れなかった'

# 自分が置いたものでなければ触らない。
printf '#!/bin/sh\n' > "$OSFS_HOME/.local/bin/rm"
chmod +x "$OSFS_HOME/.local/bin/rm"
out=$(HOME="$OSFS_HOME" PATH="$FAKEBIN:$PATH" sh "$ROOT/osfs/install.sh" 2>&1)
contains '既存の rm を上書きしない' '上書きしない' "$out"
HOME="$OSFS_HOME" PATH="$FAKEBIN:$PATH" sh "$ROOT/osfs/install.sh" --uninstall >/dev/null 2>&1
[ -e "$OSFS_HOME/.local/bin/rm" ] && ok '他人の rm は --uninstall でも消さない' \
	|| ng '他人の rm を消した'

section 'osfs（immutable.sh）'

# sudo が要る経路は走らせない。既定で何も適用しないことと、案内が出ることだけ見る。
out=$(HOME="$OSFS_HOME" sh "$ROOT/osfs/immutable.sh" status 2>&1)
contains 'status は候補を出す' '候補' "$out"
contains 'status は副作用も併記する' '代償' "$out"

out=$(HOME="$OSFS_HOME" sh "$ROOT/osfs/immutable.sh" 2>&1)
contains '引数なしは status と同じ' '候補' "$out"

HOME="$OSFS_HOME" sh "$ROOT/osfs/immutable.sh" lock >/dev/null 2>&1
[ $? -eq 2 ] && ok 'パス無しの lock は何もせず終わる' || ng 'パス無しの lock が想定外の終了'

HOME="$OSFS_HOME" sh "$ROOT/osfs/immutable.sh" bogus >/dev/null 2>&1
[ $? -eq 2 ] && ok '未知のコマンドは使い方を出して終わる' || ng '未知コマンドで想定外の終了'

# settings.json が実体コピーか symlink かで +i の代償が変わる（外部管理なら
# その反映経路が止まる）。一般論ではなく今の状態を出すこと。
IMHOME="$TMP/imhome"
mkdir -p "$IMHOME/.claude"
# 'ファイルが無い' だけだと候補リスト側の状態表示（.gitconfig 等の不在）に
# マッチして、この行が無くても通る。末尾の注意書き側だけを指す形で見ること。
out=$(HOME="$IMHOME" sh "$ROOT/osfs/immutable.sh" status 2>&1)
contains 'settings.json が無ければ無いと言う' 'settings.json: ファイルが無い' "$out"

printf '{}\n' > "$IMHOME/.claude/settings.json"
out=$(HOME="$IMHOME" sh "$ROOT/osfs/immutable.sh" status 2>&1)
contains '実体コピーなら symlink でないと言う' 'symlink ではない' "$out"

printf '{}\n' > "$IMHOME/canonical.json"
ln -sf "$IMHOME/canonical.json" "$IMHOME/.claude/settings.json"
out=$(HOME="$IMHOME" sh "$ROOT/osfs/immutable.sh" status 2>&1)
# 'canonical.json' だけだと readlink -f を出す旧実装でも通る。新しい言い回しで見る。
contains 'symlink なら実体の在り処を出す' 'の実体は' "$out"

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
# core.hooksPath はここに無い種類の hook を黙って無効化する。受け渡し版で防ぐ。
for h in commit-msg prepare-commit-msg post-commit; do
	printf '#!/bin/sh\ntouch "%s/%s-ran"\n' "$TMP" "$h" > ".git/hooks/$h"
	chmod +x ".git/hooks/$h"
done
echo x > b.txt
git add b.txt
git commit -qm chain >/dev/null 2>&1
[ -f "$TMP/chained" ] && ok 'ローカルの .git/hooks へ委譲する' || ng '委譲されなかった'

for h in commit-msg prepare-commit-msg post-commit; do
	[ -f "$TMP/$h-ran" ] && ok "実装していない $h も殺さず委譲する" \
		|| ng "$h が黙って無効化された"
done

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
