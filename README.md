# harness

各プロジェクトへハーネスとガードレールを撒くための道具立て。
このリポジトリ自体がマーケットプレイスを兼ねる。

| ディレクトリ / ファイル | 層 | 効く範囲 |
|---|---|---|
| `install.sh` | 導入 | マーケットプレイス登録とプラグイン導入を包んだだけのもの |
| `tests/run.sh` | 回帰テスト | 全層をまとめて確認（103 項目、副作用なし） |
| `plugins/` | Claude Code プラグイン | 動的判定とチーム配布。`deny` は効くが `ask` は環境依存 |
| `permissions/` | Claude Code の `permissions.deny` | 宣言的で確実。コマンド名単位の粗い粒度 |
| `githooks/` | 素の git フック | **Claude Code 非依存。** 引数レベルの判定が得意 |
| `osfs/` | OS / ファイルシステム | **最下層。** 誰が呼んでも効く。止めるのではなく取り消せるようにする |

**一層に賭けない。** プラグイン側の強制力は Claude Code の実装に左右される（実際、v2.1.220 で
`ask` が黙って表示されなくなり、別のマシンの v2.1.226 では表示された——環境で挙動が変わる）。
本当に失いたくないものは git 層で守り、
プラグインは動的判定とチーム配布のための一番外側の層として扱う。

## 収録プラグイン

| プラグイン | 役割 | 強制力 |
|---|---|---|
| `guardrails` | 不可逆操作（commit/push/reset/rm 等）と保護パスへの書き込みの前に確認を挟む | 条件付き（PreToolUse hook。既定の `ask` が表示されない環境では素通しになる。[詳細](#ask-は環境によって黙って消える実測)） |
| `session-harness` | `SESSION_STATE.md` の読み込みと更新運用 | なし（hook による文脈注入 + skill）。失敗と不在は報告する |

責務で分けてある。ガードレールだけ欲しい相手にセッション運用まで押し付けないため。

## 開発中の動作確認

インストールせずに読み込める。

```bash
claude --plugin-dir ~/repos/harness/plugins/guardrails
claude --plugin-dir ~/repos/harness/plugins/guardrails --plugin-dir ~/repos/harness/plugins/session-harness
```

編集後は `/reload-plugins` で再読込。検証は次のとおり。

```bash
claude plugin validate ~/repos/harness                        # marketplace.json
claude plugin validate ~/repos/harness/plugins/guardrails     # plugin.json
claude plugin validate ~/repos/harness/plugins/session-harness
```

なおドキュメントには `metadata.pluginRoot` を置けば `"source": "guardrails"` と短縮できるとあるが、
v2.1.220 の validator はこれを `Invalid input` で弾く。`"./plugins/guardrails"` と明示している。

## テスト

```bash
tests/run.sh
```

判定器・`guard.sh` の fail-safe・両プラグインの自己診断・`permissions/apply.py`・git 層を
まとめて確かめる（103 項目）。失敗があれば非 0 で終了する。

自己診断のテストは `HOME` / `PATH` / `GIT_CONFIG_GLOBAL` を隔離した値に差し替えて走る。
四層の診断は環境そのものを読むため、そうしないとこのマシンの導入状況で結果が変わってしまう。

**副作用は持たない。** git のテストは `HOME` ごと差し替えた隔離リポジトリで行うので、
ユーザーのグローバル設定にも既存のリポジトリにも触れない。実行後に
`core.hooksPath` が空のままであることも確認済み。

テストが無ければ、壊れても黙って壊れる。このリポジトリが一貫して潰そうとしている失敗と
同じものになるので、確認は使い捨てのコマンドで済ませず必ずここへ足すこと。

## 実セッションでの検証手順

```bash
cd ~/repos/harness
claude --plugin-dir ~/repos/harness/plugins/guardrails
```

`/hooks` を開くと `Plugin Hooks` として 3 件が並ぶ。`PreToolUse` が 2 件
（`Bash` と `Bash|Edit|Write|NotebookEdit`）、`SessionStart` が 1 件（自己診断）。

| # | 指示 | 期待 |
|---|---|---|
| 1 | `/tmp/probe/.env` に `FOO=bar` と書かせる | `guardrails: 保護対象への書き込み: /tmp/probe/.env（.env に一致）…` |
| 2 | `git -C /tmp/probe commit --dry-run` を実行させる | `guardrails: git commit — コミットが作られる…` |
| 3 | `ls -la /tmp` を実行させる | 何も出ない |

**確認が出るかは環境に依る**（[詳細](#ask-は環境によって黙って消える実測)）。v2.1.226 の
ネイティブ Linux では 1・2 とも確認が出るが、v2.1.220 の WSL2 では出なかった。出なくても、
フックが死んでいるとは限らない。フックが動いているかは起動時の自己診断が報告する。
判定器が決定を返しているかを直接見たいなら、フックを介さず単体で叩くのが確実:

```bash
cd ~/repos/harness/plugins/guardrails/scripts
echo '{"tool_name":"Bash","tool_input":{"command":"rm -f /tmp/x"}}' | python3 ./irreversible_ops.py
```

1 が最もクリーンな検証になる。`Edit`/`Write` を matcher に持つのは guardrails だけなので、
確認が出れば guardrails 由来と確定できる。

なお `git commit` を試すときは、**git 層の `pre-commit` が別に走る**ことに注意。
`githooks/` を入れている環境では、プラグインの判定を通り抜けても秘密情報のコミットは
git 側で止まる。層が違うので文言で見分けられる（`guardrails(git):` が git 層）。

### 落とし穴

- **`echo` や `true` で試さない。** 組み込みの read-only コマンドなので、フックの結果に関わらず確認が出ない
- **`/mnt/e` で起動しない。** file watcher が効かず、編集が `/reload-plugins` に拾われない
- **マーケットプレイスが `directory` source なら、キャッシュ側は実行されない。**
  `~/.claude/settings.json` の `extraKnownMarketplaces` が `{"source":"directory","path":"..."}`
  でこのリポジトリを指している場合、プラグインは `~/.claude/plugins/cache/...` ではなく
  **リポジトリから直接**読まれる。キャッシュ側を編集しても何も起きない。
  実行中の実体は `CLAUDE_PLUGIN_ROOT` が指すパスであり、自己診断が毎回それを報告する。
  これを取り違えて「フックが発火しない」と 2 セッション誤診した。
  なお `path` には `~/repos/harness` のような**チルダ表記が使える**（展開されて解決されることを
  `claude plugin list` で確認済み）。dotfiles で共有するなら絶対パスを避けること
- **診断ログの出力先はセッションを跨いで生存するパスにする。** scratchpad はセッション終了時に
  消える。`>> ... 2>/dev/null || true` と併せると、書き込み失敗が握りつぶされて
  「ログが増えない = フックが動いていない」と誤読する
- 起動時に `userConfig` の入力を求められるかを見ておく。求められるなら `extra_patterns` に
  値を 2 つ入れることで、`multiple: true` の直列化形式（TODO）もそのまま確認できる

## インストール

```bash
./install.sh                # マーケットプレイス登録 + 両プラグイン導入
./install.sh --guardrails   # guardrails だけ
./install.sh --dry-run      # 走らせるコマンドを見るだけ
```

中身は 2 コマンドなので手で打ってもよい。

```bash
claude plugin marketplace add KazukiShinomiya/harness   # 自分用ならローカルパスでも可
claude plugin install guardrails@harness
```

`--scope project` を付けるとリポジトリの `.claude/settings.json` に `enabledPlugins` が書かれ、
clone した全員へ届く。ただしプロジェクトスコープは workspace trust の承認を経てから読み込まれ、
background monitors は読み込まれない。

### 「clone するだけ」にはできない（実測）

`extraKnownMarketplaces` と `enabledPlugins` を対象リポジトリの `.claude/settings.json` に
コミットしておけば導入手順ゼロになる、と考えたが**ならない**。
プロジェクトスコープの `extraKnownMarketplaces` は効かない。

隔離環境で使い捨てのマーケットプレイスを作って確かめた。

| 置いたもの | 結果 |
|---|---|
| プロジェクト設定の `hooks`（プラグイン非経由） | **発火する**（対照。設定ファイル自体は読まれている） |
| プロジェクト設定の `extraKnownMarketplaces` + `enabledPlugins` | プラグインが読み込まれない |
| 同上の状態で `claude plugin marketplace list` | **マーケットプレイスとして認識すらされない** |

直接フックが効く以上「設定が読まれていない」では説明できない。このキーがプロジェクト
スコープでは扱われないということ。したがって marketplace の登録はユーザー自身が行う必要があり、
`install.sh` はその 2 コマンドを包んだだけのもの。

## git 層のガードレール（Claude Code 非依存）

`githooks/` はプラグインではない。`core.hooksPath` に載せる素の git フックで、
**Claude Code が動いていなくても、別のエージェントが動かしても、シェルから直接叩いても効く。**
プラグイン側の `ask` が黙って消えるような事故があっても、この層は独立して生きている。

```bash
githooks/install.sh            # 全リポジトリ
githooks/install.sh --local    # カレントのリポジトリだけ（試すとき）
githooks/install.sh --uninstall
```

| フック | 止めるもの | 逃げ道 |
|---|---|---|
| `pre-commit` | 秘密情報（`.env` / `*.pem` / `*.key` / `*credentials*` 等）のコミット | `git commit --no-verify` |
| `pre-push` | 保護ブランチへの**強制 push** と**削除**（既定 `main` `master`） | `git push --no-verify` |

```bash
git config guardrails.protectedBranches "main master release"
git config guardrails.disable true      # このリポジトリでは切る
```

### ここは ask に倒さない

プラグイン側の判定器は fail-safe で `ask` に倒すが、git フックには**ユーザーへ問い返す手段が無い**。
標準入力は git が使っており、確認ダイアログも出せない。したがってこの層は「確認を挟む」のではなく
**止める**。代わりに逃げ道を `--no-verify` という明示的な一手に限定してある。
事故で通ることはないが、意図があれば通る。

### `core.hooksPath` はリポジトリ固有のフックを無効にする

これが唯一の副作用で、無視できない。`core.hooksPath` を設定すると git は**そのディレクトリ
しか見ない**。`.git/hooks/` は丸ごと読まれなくなる。

対処は二段構えにしてある。

**1. 実装している種類は委譲する。** `pre-commit` と `pre-push` は判定を行ったあと、
ローカルのフックへ処理を渡す（`_lib.sh` の `chain_local_hook`）。
`git rev-parse --git-common-dir` から実体を引くので `core.hooksPath` の影響を受けず、
自分自身を呼ぶ場合は再帰を避ける。終了コードはそのまま伝播する。

**2. 実装していない種類も殺さない。** ここが見落としやすい。`commit-msg`（commitlint 等）や
`post-merge` は guardrails が判定に使わないため、素朴に作ると**ディレクトリに存在しない=
一切実行されない**ことになる。しかも何の警告も出ない。まさにこのリポジトリが潰そうとしている
「黙って壊れる」ものになる。

そこで受け渡し専用のフックを全種類ぶん置いてある（`_passthrough.sh` と 14 個のシム）。
判定は何もせず、ローカルの実装をそのまま呼ぶだけ。

```
applypatch-msg  pre-applypatch  post-applypatch  pre-merge-commit
prepare-commit-msg  commit-msg  post-commit  pre-rebase
post-checkout  post-merge  pre-auto-gc  post-rewrite
push-to-checkout  sendemail-validate
```

実測で確認済み。受け渡しを置く前は `commit-msg` が黙って無効化されたが、置いた後は
`commit-msg` `prepare-commit-msg` `post-commit` `post-checkout` すべてが動く。
`tests/run.sh` が回帰を見張っている。

### リポジトリ側が `core.hooksPath` を設定していると効かない

husky v9 以降は `.husky` をリポジトリ固有の `core.hooksPath` に設定する。
git の設定は local が global に優先するため、**そういうリポジトリでは husky が勝ち、
この層のガードレールは効かない**（実測）。husky 側が壊れないのは良いが、
守られていると思い込まないこと。そのリポジトリで守りたければ `--local` で個別に入れるか、
husky の設定へ組み込む。

### 検証済みの挙動

隔離したリポジトリ（`HOME` ごと差し替え）で実測した。

| # | 操作 | 結果 |
|---|---|---|
| 1 | 通常ファイルのコミット | 通る |
| 2 | `.env` のコミット | **止まる**（コミット数が増えない） |
| 3 | `git commit --no-verify` | 通る |
| 4 | 通常の push | 通る |
| 5 | 保護ブランチへの `push -f` | **止まる**（remote が変化しない） |
| 6 | 保護ブランチの削除 | **止まる**（remote に残る） |
| 7 | `.git/hooks/pre-commit` への委譲 | 実行される |
| 8 | 保護**外**ブランチへの `push -f` | 通る（誤爆しない） |

さらに `~/repos/harness` 自身へ `--local` で適用した状態でも、`.env` のコミットが
止まることを実リポジトリで確認済み。

`install.sh` は既に別の値が入っている `core.hooksPath` を上書きせず exit 1 する。

## permissions 層（deny のみ）

`permissions` の `ask` ルールが確認として表示されるかは**環境に依る**——v2.1.220 / WSL2 では
素通しになり、v2.1.226 / ネイティブ Linux では出た（[詳細](#ask-は環境によって黙って消える実測)）。
どの環境でも効くのは `deny` だけなので、この層は `deny` に絞る。
`permissions/deny-recommended.json` がその雛形で、`permissions/apply.py` で差分マージする。

```bash
permissions/apply.py                    # dry-run。何が増えるか見るだけ
permissions/apply.py --write            # 適用（実体側に .bak を残す）
permissions/apply.py --to path/to/settings.json
```

既存の規則は消さず和集合を取る。冪等なので何度実行してもよい。

雛形は 18 件だが、**全部入れる必要はない**。作者の環境ではディスク破壊系 8 件と電源系 4 件の
計 12 件だけを適用している。`sudo` は `apt install` 等を任せられなくなるため、
`Edit(~/.claude/settings.json)` 系は設定作業が全て手動になるため外した。
`--from` に部分集合の JSON を渡せば群単位で入れられる。

### 引数を制約するパターンは書かない

公式ドキュメントが明記しているとおり、Bash の引数を絞る規則は脆い。
`Bash(git push --force *)` は `git push -f` にも `--force-with-lease` にも、
オプション順を変えた形にも当たらない。

そこで**この層はコマンド名単位に絞る**。`sudo` `dd` `mkfs` `fdisk` `shred` `chattr`
`shutdown` など、「そのコマンド自体をエージェントに使わせない」と言い切れるものだけを置く。
引数レベルの判定（強制 push、秘密情報のコミット）は git 層が担当する。**層ごとに
得意な粒度が違う**ので、同じことを両方でやろうとしないこと。

`deny` は問い返しが無い。広げすぎると作業が止まり、結局まるごと外される。
足すときは「自分が普段 Claude に使わせているか」で判断する。

### 書き方の注意

- **ファイル系は `Edit(...)` を使う。** `Write(...)` `NotebookEdit(...)` `MultiEdit(...)` の
  パス規則は受理されるが**参照されない**（起動時に警告が出る）。`Edit(...)` は
  ファイル編集ツール全体に効く
- **絶対パスは `//` から始める。** 単一の `/` は「設定ファイルの位置からの相対」を意味する。
  ホームからは `~/` が使える
- **`~/.claude/settings.json` が symlink なら実体側も併記する。** 雛形は
  `~/dotfiles/.claude/settings.json` も同時に拒否している。片方だけでは迂回できてしまう
- **`deny` は先頭の環境変数代入を跨いで一致する。** `FOO=bar rm -rf tmp/` も `Bash(rm *)` に当たる
- **ラッパーは剥がされない。** `npx` `docker exec` `devbox run` 等は内側のコマンドの規則で
  覆えない。必要ならラッパーごと規則を書く

## OS/FS 層（誰が呼んでも効く）

上の三層はいずれも「Claude Code が呼ぶ」か「git が呼ぶ」ことを前提にしている。
その外から消されたものは守れない。最下層はそこを埋める。

```sh
sudo apt install trash-cli     # 先に入れること
osfs/install.sh                # ~/.local/bin/rm として rm-guard を置く
osfs/install.sh --status
osfs/install.sh --uninstall
```

### 止めるのではなく取り消せるようにする

この層だけ思想が違う。上の三層は**危険な操作を止める**。`rm-guard` は止めない——
ゴミ箱（trash-cli）へ送るだけで、コマンドは今までどおり成功する。

止める方向で強くしていくと、必ずどこかで作業が止まって、まるごと外される。
`rm` は日常的に使うものなので、そこに確認を挟むのは長続きしない。
**消えたものが戻せるなら、止める必要がない。**

```sh
trash-list                     # 何が入っているか
trash-restore                  # 戻す
trash-empty 30                 # 30 日より古いものを捨てる
```

### alias ではなく PATH に置く（実測）

`alias rm=trash-put` では**足りない**。Claude Code の Bash ツールは非対話シェルで、
`~/.zshrc` の alias は届かない。実際にこの環境の hook から `alias` を採ったところ、
zsh 組み込みの 3 件しか無かった。エージェントの `rm` を覆えないなら意味がない。

`~/.local/bin` は PATH 上で `/usr/bin` より前にあるため、ここに `rm` という名前で
置けば対話シェル・スクリプト・エージェントのすべてから同じものが呼ばれる。
`install.sh --status` は PATH の順序を確認して、後ろにある場合は警告する。

### ゴミ箱が使えないときは黙って本物の rm へ落とさない

`trash-put` が見つからないとき、`rm-guard` は本物の `rm` へ委譲せずエラーで止まる。
落としてしまうと「守られているつもりで守られていない」状態が黙って続く。
このリポジトリが一貫して潰そうとしている失敗そのものになる。

### 効かない経路を書いておく

過信させないために、効かないものを明記する。

- `sudo rm` — `sudo` は `secure_path` を使うため `/usr/bin/rm` が呼ばれる
- `find -delete`、`unlink`、`> file` による切り詰め
- 脱出口 `HARNESS_RM_REAL=1 rm ...`（意図的に用意してある）

### スクリプトの後始末には脱出口を使う

設置した直後に `tests/run.sh` が 2 件落ちた。この層を入れると**既存のスクリプトの
挙動が変わる**——踏んだ穴を残しておく。

- **`trap 'rm -rf "$TMP"'` が rm-guard を通る。** 一時ディレクトリがゴミ箱へ送られ、
  溜まり続ける。しかもテストは隔離用の偽 `HOME` を `$TMP` の中に作るため、
  `trash-put` が「ゴミ箱を自分自身の中へ移す」形になって失敗し、残骸が消えなくなった。
  後始末は `HARNESS_RM_REAL=1 /usr/bin/rm -rf ...` と書くこと
- **「trash-cli が無い状況」が作れなくなる。** `PATH=/usr/bin:/bin` では本物が見えて
  しまう。`PATH=/nonexistent` で外す（`rm-guard` も `install.sh` も、ゴミ箱の有無を
  判定するところまではシェル組み込みと絶対パスしか使わない）

一般化すると、**捨てると分かっているものまでゴミ箱へ送らない**。ビルドの中間物や
テストの一時ファイルは脱出口経由で消す。そうしないとゴミ箱が実質のゴミ捨て場になり、
本当に戻したいものが埋もれる。

### `chattr +i` は候補を出すだけ

`osfs/immutable.sh` は**既定では何も適用しない**。`status` が候補と、それぞれを
固めたときに何が動かなくなるかを並べる。

| 対象 | 守るもの | 代償 |
|---|---|---|
| `~/.gitconfig` | `core.hooksPath`（git 層の入口） | `git config --global` が全て失敗する |
| `~/.claude/settings.json` | `enabledPlugins`、`permissions.deny` | Claude Code 自身が設定を書けなくなる。dotfiles 等の外部で管理していれば、そこからの反映も止まる |
| `~/.ssh/authorized_keys` | 鍵の追加による侵入経路 | 鍵の管理が手作業になる |

代償の方が大きい場合が多いので、一括で掛ける口は用意していない。
`chattr` は `permissions/deny-recommended.json` の拒否対象に入れてあるため、
このスクリプトは Claude Code からは実行できない。手で叩くこと。
symlink に掛けても中身は守れないので、`lock` は実体を解決してから適用する。

## 設計上の決定

### `userConfig` の `multiple: true` はカンマ区切り（実測）

v2.1.220 で確定。プラグインの `userConfig` の値は、hook 環境変数へ
JavaScript の `String(配列)` で直列化される。本体の該当箇所はこう書かれている。

```js
M[`CLAUDE_PLUGIN_OPTION_${ge}`] = String(Ne)
```

つまり**カンマ区切り**で、区切りにスペースは入らない。JSON 配列でも改行区切りでもない。
生バイトで確認した実測値:

```
["alpha", "bra vo", "char,lie"]  ->  CLAUDE_PLUGIN_OPTION_EXTRA_PATTERNS=alpha,bra vo,char,lie
```

結果として:

- 要素の中のスペースは保たれる。2 語のパターン（`flyctl deploy`）は書ける
- **要素の中のカンマは区切りと区別できない。** 受け側では復元しようがない。
  パターンにカンマを使わないこと
- `_common.option_list()` はカンマで分割し、前後の空白と空要素を捨てるだけにしてある

ついでに分かったことが二つある。

**設定は新しいセッションでしか読まれない。** `pluginConfigs` を書いても、
実行中のセッションの hook 環境には現れない。`permissions.deny` は再起動なしで
効いたので、経路が違う。検証するなら `claude -p` で子セッションを起こす。

**プロジェクトスコープでは効かない。** `.claude/settings.local.json` に
`pluginConfigs` を書いても hook には届かない。`extraKnownMarketplaces` と同じ穴。
ユーザー設定（`~/.claude/settings.json`）に置くこと。保存先の形はこう:

```json
"pluginConfigs": {
  "guardrails@harness": { "options": { "extra_patterns": ["deploy prod"] } }
}
```

なお `${user_config.KEY}` を hook の shell 形式コマンドに書くと Claude Code が
拒否する（置換後の値がシェルで再解釈されるため）。exec 形式か、環境変数を読むこと。

### 理由文は人間が Yes / No を選ぶための情報にする

確認ダイアログに出るのは `permissionDecisionReason` の一行だけで、**止められた人間が
判断に使えるのはそれしかない。** ここが空疎だと、確認は出ているのに実質は素通りになる。

以前はこう出していた。

```
guardrails: irreversible op (rm -f): NO fabricated consent --
confirm full-context read and EXPLICIT user approval before proceeding
```

これはエージェントへの戒めであって、人間には何が起きようとしているのか分からない。
しかも操作の種類によらず同じ文だった。実際、この文言のまま**確認が出ていたのに
無意識に `Yes` が押されていた**（2026-08-10）。

いまは操作ごとに「実行すると何が起きるか」を書く。

```
guardrails: rm -rf — ファイル・ディレクトリを削除する。rm-guard 経由ならゴミ箱へ入り
trash-restore で戻せるが、そうでなければ戻せない。意図した操作か確かめてほしい

guardrails: git push — リモートへ反映される。取り消しても、取得済みの相手の手元には残る。
意図した操作か確かめてほしい

guardrails: 保護対象への書き込み: /tmp/x/.env（.env に一致）。
秘密情報や設定を壊していないか確かめてほしい
```

`userConfig.extra_patterns` で足された操作には説明が無い。その場合も黙らず
「取り消しにくい操作として登録されている」と言う——語れないことを語れないと言う方が、
それらしい文を捏造するより良い。`tests/run.sh` が、操作ごとに説明が変わることと、
説明を使い回していないことを見張っている。

### fail-safe（判定不能なら ask）

`guardrails` の判定器が動かない・落ちた場合、素通し（fail-open）にはせず確認ダイアログへ倒す。

- **fail-open** はガードレールとして意味を成さない。壊れていることに気付けない。
- **fail-close（deny）** は判定器が壊れた瞬間に全プロジェクトで作業不能になる。
- したがって既定は **ask**。人間が判断すれば進める。

`userConfig.decision` を `deny` にすれば即ブロックへ切り替えられる。

### `ask` は環境によって黙って消える（実測）

**この設計を読む前に知っておくべき事実。** Claude Code v2.1.220 で、PreToolUse フックが返した
`permissionDecision: "ask"` が確認ダイアログとして**表示されない**ことを実測した。
`permissionMode` が `default` でも `acceptEdits` でも同じ。同じフック・同じ経路で
`deny` に差し替えると即座にブロックされ理由文も表示されるため、フック機構・出力形式・
exit code はいずれも正常で、`ask` という決定の扱いだけが飛んでいた。

これは公式ドキュメントの記述と食い違う。[permissions](https://code.claude.com/docs/en/permissions)
の "Extend permissions with hooks" は次のように書いている。

> The hook output can deny the tool call, **force a prompt**, or skip the prompt to let the call proceed.

**当初はフック固有の問題ではないと見ていた。** `permissions` の `ask` **ルール**
（フックを介さない設定側）でも同じことが起きたため、壊れているのは経路ではなく
`ask` という決定そのものだと結論した。**この結論は現行版には当てはまらない。**

#### 実測（Linux / Bash）

| 版 | マシン | 経路 | 結果 |
|---|---|---|---|
| v2.1.220 | WSL2（Linux 5.15） | PreToolUse の `ask` | 確認が出ず素通し |
| v2.1.220 | WSL2（Linux 5.15） | `permissions` の `ask` | 確認が出ず素通し |
| **v2.1.226** | ネイティブ（Linux 6.8） | **PreToolUse の `ask`** | **確認ダイアログが出る** |
| **v2.1.226** | ネイティブ（Linux 6.8） | **`permissions` の `ask`** | **確認ダイアログが出る** |

`deny` はどの版・どのマシン・どちらの経路でも効く。フックが発火していることも別途
確かめてある（`guard.sh` の先頭にタイムスタンプを追記させると、Bash 呼び出しごとに
ログが 2 行増える——`hooks.json` の PreToolUse 定義 2 件が `Bash` にマッチするため）。

**`permissions` の `ask` は `allow` を上書きする形で測った。** `Bash(echo:*)` を `ask` に
置き、`echo harness-ask-probe` を単独で撃つ。優先順位が `deny` > `ask` > `allow` なら
確認が出るはずで、実際に出た。`allow` に無いコマンドで測ると、既定の確認と `ask` 由来の
確認が区別できない。**この行は一度「素通し」と記録していた**（2026-08-09）。測り直したら
出たので、記録ではなく測り方を疑うこと。

**版とマシンが同時に違うので、両経路が通るようになった原因は切り分けられていない。**
同じマシンで両方の版を撃つまでは「v2.1.226 で直った」と言い切らないこと。

#### 「確認が出なかった」はエージェントには測れない

**この節は測り方の話だが、上の表より重要かもしれない。** 実際にここで誤った結論を
出しかけた。

エージェント（Claude）から見ると、確認が出て人間が承認した場合と、確認が出ずに
実行された場合の**戻り値が同じ**になる。どちらもツールは成功を返す。したがって
**「素通りした」はエージェントには観測できない**——観測できるのは `deny` によるブロック
（ツールがエラーを返す）と、人間が画面を見て報告した内容だけ。

測るときの決まりごとは三つ。

- **単独コマンドで撃つ。** `rm -f /tmp/x; echo "rc=$?"` のように複合にすると、後半が
  `allow` ルールに一致して全体が自動承認され、`ask` の不発と区別がつかなくなる。
  `deny` は `allow` に勝つため、対照側だけが正しく効いて見えるのが厄介なところ
- **人間が画面を見る。** 「確認が出なかった」は人間にしか言えない。しかも
  **無意識に `Yes` を押していた**ということが実際に起きる。出たかどうかを意識して
  見るつもりで撃つこと
- **人間が「No を押す」と決めておくと、エージェント側にも届く。** 拒否はツールがエラーを
  返すので、確認が出たこと自体は観測できる。承認と違って戻り値が分かれるからだ。
  ただし**人間の目を省く道具にはならない**——2026-08-10 の実測では「確認ダイアログの No」と
  「ESC による割り込み」が、エージェントに届く文言では区別できなかった。どちらだったかは
  人間に聞いて初めて分かった

`claude -p`（非対話）でも測れない。確認を出す相手がいないため `ask` は `denied` に倒れ、
「止まった」が「直った」に見える。上の表は人間が対話セッションで目視して埋めたもので、
`-p` で得た `denied` は証拠として採用していない。

上流への報告の下書きが [`docs/upstream-report-draft.md`](docs/upstream-report-draft.md) にある
（再現手順 2 通りと `deny` の対照つき）。

**既定を `ask` から動かしてはいない。** `deny` は判定器が壊れた瞬間に全プロジェクトで作業不能に
なり、上の fail-safe 方針を撤回することになるため。代わりに**黙っているのをやめる**方向で解いた
（下記の自己診断）。確実に止めたい環境では `userConfig.decision` を `deny` にすること。

自分の環境で `ask` が表示されるかは一発で確かめられる。**対話セッションで**次を
実行させる。**単独で撃ち、出るかどうかを意識して見ること**（前節）。

```bash
rm -f /tmp/guardrails-manual-check   # 確認が出なければ、その環境では検出しても素通しになる
```

このファイルは存在しないので、確認に `Yes` と答えても副作用は無い。

### 自己診断（SessionStart）

黙って死ぬガードレールは、自分用なら「おかしいな」で済むが、配布すると害になる。
守られていると思わせて守っていないのは、何も無いより悪い。

`scripts/selfcheck.sh` が毎セッション開始時に、登録の有無ではなく **実際に動くか** を確認する。
`guard.sh` を合成ペイロード（実在しないパスを対象にした `rm -rf` と `.env` への書き込み）で
実際に起動し、判定器が決定を返すところまで通しで検査する。異常なら `systemMessage` で
ユーザーに警告し、`additionalContext` で Claude 側にも「ガードレールは効いていないので
不可逆操作の前に自分で確認を取れ」と伝える。診断自体が失敗した場合も黙らず「生死不明」と報告する。

正常時も**実行中のプラグインのパスを毎回報告する**。これは飾りではない。上記の落とし穴で
実際に 2 セッションを溶かしたため、どの `guard.sh` が動いているかは常に見えている必要がある。

実体は `plugins/guardrails/scripts/selfcheck.sh`。異常系（`CLAUDE_PLUGIN_ROOT` 未設定、
判定器が黙る）を壊した複製で実測したうえ、実際の `SessionStart` で発火することも
`~/repos/harness` から新規セッションを起こして確認済み。

#### 診断は四層すべてに掛かる

当初はプラグイン層しか見ていなかった。その結果、**`permissions` 層が一件も適用されて
いない状態が何セッションも気付かれずに続いた**。`SESSION_STATE.md` には「適用済み・12 件」と
書いてあり、記録の方が実態から外れていた。手で書いた状態表は腐る。実測は腐らない。

現在は毎セッション、四層を実際に読んで報告する。

```
guardrails: 有効（/path/to/plugins/guardrails、decision=ask）
  git 層: 有効（/home/you/repos/harness/githooks）
  permissions 層: deny 18 件
  OS/FS 層: 有効（rm -> rm-guard）
```

| 層 | 何を見るか |
|---|---|
| プラグイン | `guard.sh` を合成ペイロードで起動し、決定が返るまで通しで確認 |
| git | `core.hooksPath` が実在し、harness の `githooks` で、`pre-commit`/`pre-push` が実行可能か |
| permissions | 実効 `settings.json`（user / project、`.local` 含む）の `deny` 件数 |
| OS/FS | `PATH` 上の `rm` が `rm-guard` に解決されるか、`trash-put` があるか |

**未適用と故障を区別する。ここが要点。**

- **未適用** — 層を入れていない環境の方が多い。報告はするが警告はしない。
  未適用で毎回鳴らすと、やがて誰も読まなくなる。
- **導入済みで故障** — `systemMessage` で警告する。これだけが警告に値する。
  「守られているつもりで守られていない」状態そのものだからだ。

故障として拾うのは、いずれも**それ自体は何のエラーも出さない**ものばかり。

- `core.hooksPath` が存在しないディレクトリを指している（git は hook を全て黙って飛ばす）
- `pre-commit` から実行権限が落ちている（git は黙って飛ばす）
- `settings.json` が壊れた JSON（`deny` が丸ごと効かなくなる）
- `~/.local/bin/rm` に `rm-guard` を置いたが `PATH` の並びで拾われない
- `rm-guard` は効いているが `trash-put` が無い（あらゆる `rm` が失敗する）

`guardrails.disable=true` と「harness 以外の `hooksPath`」は、事故ではなく明示的な意思表示
なので警告しない。ただし状態としては必ず出す——黙らないことと止めることは別。

### 「黙らない」は session-harness にも適用する

`session-harness` は当初、注入の失敗を例外ごと握り潰していた。危険ではない（偽の安心を
作らない）というのがその理由だったが、**それでも黙ってよい理由にはならない**。
実際に別ディレクトリから起動したセッションが前回の経緯を知らないまま始まり、
セッションログを漁って復元する羽目になった。

現在は六通りを区別して報告する。

| 状況 | 報告 |
|---|---|
| 読み込めた | どのパスから読んだかを添えて注入 |
| ファイルが無い | **どこを探したか**を伝える。起動位置の取り違えに気付ける唯一の手がかり |
| 空だった | その旨 |
| 読めなかった | `systemMessage` でユーザーにも警告 |
| python が無い | 同上。注入は決して働かない |
| `CLAUDE_PLUGIN_ROOT` 未設定 | 同上 |

止めも確認もしない点は変わらない。**黙らないことと止めることは別**で、
危険でないものを止める必要は無いが、黙ってよいわけでもない。

### プラグインの settings.json では permissions を配れない

Claude Code のプラグインが `settings.json` で供給できるのは `agent` と `subagentStatusLine` の 2 キーのみ。
`permissions.deny` は**プラグインからは**配布できない。

当初はこれを理由に強制力をすべて hooks へ寄せていたが、v2.1.220 で `ask` が機能しないと
分かった時点で方針を改めた。`permissions` は dotfiles 経由なら配れる（`~/.claude/settings.json`
を dotfiles 側の正本から用意するため。このマシンでは `setup.sh` が正本と `settings.machine.json` を
マージしたプレーンコピーを置いている——symlink ではないので、正本を編集したら再実行が要る）
ので、配布経路としては解決済み。現在は `permissions/` と `githooks/` に分けて持たせている。

### 判定はトークン境界で行う

`irreversible_ops.py` は部分文字列一致ではなく `shlex` でトークン分割してから照合する。
`echo "git push はまだしない"` のように引用符の中にパターンが現れるだけの文字列で発火させないため。
コマンドが解釈できない（クォート不整合など）場合は例外を上げて非 0 で終了し、`guard.sh` が `ask` に倒す。

#### ただし rm は綴りでは照合しない

当初は `"rm -rf"` `"rm -r"` `"rm -f"` を literal で並べていた。**`rm -fr` が素通りしていた**（実測）。
`-rf` `-fr` `-Rf` `-r -f` `--recursive --force` はすべて同じ意味で、綴りを列挙する方針では
必ず取りこぼす。現在は `rm` の呼び出しを見つけてからオプションを意味で判定する
（まとめ書きされた短オプションは 1 文字ずつ見る。`/bin/rm` のような絶対パス呼びも拾う）。

- `git rm` は対象外。追跡下のファイルしか消さず git から戻せる
- **オプションの無い `rm file` は今も発火しない。** 既定パターンを移植した時点からの
  境界をそのまま残してある。日常的すぎるのと、消えたものを戻す役目は OS/FS 層
  （`rm-guard`）が持っているため。変えるなら `find_rm_hit()` の 1 行で済む

なお単独パターンの `--build` は削除した。意図していた `docker compose up --build` は
その前の行が先に拾うため、この規則が実際に発火するのは `make --build` のような
無関係なコマンドだけだった（実測）。

### 保護パスは Bash も見る

`protected_paths.py` の matcher は当初 `Edit|Write|NotebookEdit` だけだった。そのため
`echo x >> ~/.ssh/authorized_keys` が素通りしていた（実測）。**Edit ツールでは止まるのに
シェル経由なら通るのでは、守っていることにならない。** 現在は `Bash` も matcher に含め、
コマンド文字列から書き込み先を拾う。

| 拾うもの | 例 |
|---|---|
| リダイレクト先 | `> .env` / `>>.env` / `2> .env` / `&> .env` / `exec 3> .env` |
| 書き込むと分かっているコマンドの引数 | `tee` `cp` `mv` `install` `ln` `truncate` `dd`（`of=`）`sed -i` |
| サブシェルの中身（再帰・3 段まで） | `bash -c '…'` / `sh` `zsh` `dash` `ksh` の `-c` / `eval '…'` |

**読み取りは対象にしない。** `cat .env` まで拾うと日常操作が確認だらけになり、やがて
誰も読まなくなる。この層の目的は書き込む前に一拍置くこと。

**サブシェルの中身は、以前「静的には無理」と誤って分類していた穴だった。** `bash -c` の
引数はただの文字列なので、同じ判定を再帰的に当てれば読める。当てていなかった間は、
**サブシェルで包むだけでこの層を抜けられた**（実測して塞いだ）。`bash script.sh` は
対象外——スクリプトの中身は静的には読めないので、`-c` の引数だけを見る。

**塞ぎ切ってはいない。** シェルは任意の書き込み方を許すので、静的には拾えないものが残る。

```bash
python3 -c "open('.env','w').write('x')"   # インタプリタの中身は読めない
F=.env; echo x > $F                        # 実行時に決まる変数展開
eval "$cmd"                                # 同上
curl -o .env https://…                     # 書き込み先を取るオプションは見ていない
                                           #   （wget -O / gpg --output / rsync / tar -C も）
bash -c 'bash -c "bash -c …"'              # 入れ子は 3 段まで。4 段目から先は見ない
```

**書き込み先を取るオプションを追いかけないのは、意図的な線引き。** 追い始めると
「次は何を足すのか」が永久に残る。広げるより、本当に失いたくないものを git 層と
OS/FS 層へ寄せる方が筋がいい。

境界は `tests/run.sh` で固定してある——`2>&1` をパスと誤解しないこと、無害な中身の
サブシェルは素通しすること、入れ子 3 段は拾い 4 段は拾わないこと。ここは「確認を挟む層」
であって最後の砦ではない。

### 判定器は guard.sh 経由で呼ぶ

`hooks.json` は判定器を直接呼ばず、必ず `guard.sh <判定器名>` の形で呼ぶ。
`guard.sh` は python の不在・判定器の異常・引数の欠落のいずれでも `ask` を返して exit 0 する。

**exit 2 を返してはいけない。** Claude Code は exit 2 を「ツール呼び出しをブロック」と解釈するため、
設定ミスで全呼び出しが止まる。fail-safe 方針と正面から矛盾する。

### 状態の置き場所

`${CLAUDE_PLUGIN_ROOT}` はプラグイン更新のたびに変わる。永続させたいものは `${CLAUDE_PLUGIN_DATA}` へ。
現状どちらのプラグインも状態を持たない。

## 既存のグローバル設定からの移行（完了）

`~/.claude/settings.json` に残っていた移植元は削除済み。dotfiles の drift / freshness
チェックだけが残っている（harness とは無関係なので残す）。

移行が済んだかどうかは**確認の有無では判断できない**。本来なら二重に発火して確認が
二度出るはずだが、`ask` が表示されない版（作業当時の v2.1.220）では二重にも見えないため。
設定を直接読んで確かめること。

| グローバル側 | 引き継ぎ先 | 削除してよいか |
|---|---|---|
| `PreToolUse`（`Bash` matcher） | `guardrails` の `irreversible_ops.py` | **可**。トークン境界で判定するぶん精度も高い |
| `SessionStart`（SESSION_STATE 注入） | `session-harness` の `session_state.py` | **順序に注意**（下記） |
| `SessionStart`（dotfiles drift / freshness） | なし | 残す。harness とは無関係 |

### 順序を間違えると SESSION_STATE が黙って読まれなくなる

同じ移行を他の環境でやる人向けに残しておく。**SESSION_STATE の注入を担っているのが
グローバルフックただ一つの状態で先にそれを消すと、引き継ぎ先が無いまま注入が落ちる。**
しかも落ちても何も表示されない。次のセッションが「前回の経緯を知らないまま」始まるだけで、
消してから気付く手段が無い。必ずこの順で行う。

```bash
claude plugin install session-harness@harness   # 先に引き継ぎ先を立てる
# 新規セッションを起こし、SESSION_STATE が文脈に入ることを確認してから
# dotfiles 側でグローバルの SessionStart（注入分）を削除する
```

作者の環境ではこの順で実施し、削除後も新規セッションで
`session-harness: <path> を読み込んだ` と `guardrails: 有効（...）` の両方が出ること、
SESSION_STATE が重複注入されていないことを確認した。

`session_state.py` はグローバル側と等価以上（`userConfig.state_file` でファイル名を変えられ、
空ファイルも弾き、失敗時は黙らず報告する）。

なお `~/.claude/settings.json` の正本は `~/dotfiles/.claude/settings.json` 側にあるため、
削除は dotfiles 側で行い同期する。

## 開発環境上の注意（WSL2）

**`/mnt/e` などの Windows マウント配下で作業しない。** drvfs は inotify を通さないため、
設定ファイルの手編集が Claude Code の file watcher に検知されない。`.claude/settings.local.json` に
hooks を書き足しても `/hooks` に現れず、さらに Claude Code 自身が同ファイルへ書き込んだ時点で
手編集が消える。実測で確認済み。開発は WSL ネイティブ側（`~/repos`）で行うこと。

## TODO

### 決着済み

- [x] 実セッションでフックが発火するか → **発火する。**`CLAUDE_PLUGIN_ROOT` はリポジトリ側を指し、
      フック経由の stdout に正しい JSON が出ている
- [x] **`ask` の不発は環境依存。このマシン・この版では両経路とも通る。** v2.1.220（WSL2）では
      フック経由でも `permissions` の `ask` ルールでも確認が出なかったが、v2.1.226
      （ネイティブ Linux）では PreToolUse 経由も `permissions.ask` も確認が出る。
      版とマシンが同時に違うので原因は未切り分け。`deny` はどの条件でも効くので、確実に
      止めたいものは `deny` か git 層（[詳細](#ask-は環境によって黙って消える実測)）
- [x] **「確認が出なかった」はエージェントには測れない。** 出て承認された場合と
      戻り値が同じになる。複合コマンドで撃つと `allow` に拾われてさらに紛れる。
      この二つで一度誤った結論（「セッションによって割れる」）を出しかけた
      （[詳細](#確認が出なかったはエージェントには測れない)）
- [x] 多層防御の git 層 → `githooks/`。隔離環境で 8 通り＋実リポジトリで実測
- [x] `permissions` 雛形 → `permissions/deny-recommended.json` + `apply.py`
- [x] 自己診断 → `SessionStart` で実際に発火するところまで確認

### 未決・未着手

- [x] **グローバル設定からの移行が完了。** `session-harness` を先に入れて注入を確認してから、
      移植元の `PreToolUse`（Bash）と `SessionStart`（SESSION_STATE 注入分）を削除した
- [x] `session-harness` も黙らなくなった。読み込めた / 無い / 空 / 読めない / python 不在 /
      `CLAUDE_PLUGIN_ROOT` 未設定 の 6 通りを区別して報告する（全経路を実測）
- [x] **導入を手順ゼロにはできない。** プロジェクトスコープの `extraKnownMarketplaces` は
      効かない（対照実験で確定）。`install.sh` で 2 コマンドに包む形に落とした
- [x] `githooks` をグローバル（`core.hooksPath`）へ適用済み。適用前に影響を実測し、
      実装していない種類の hook を殺さないよう受け渡しを用意してから入れた
- [x] **`userConfig` の `multiple: true` はカンマ区切りだった**（生バイトで実測、v2.1.220）。
      `_common.option_list()` をそれに合わせて単純化した。あわせて「設定は新セッションでしか
      読まれない」「プロジェクトスコープでは効かない」ことも判明（[詳細](#userconfig-の-multiple-true-はカンマ区切り実測)）
- [x] **OS/FS 層を用意し、このマシンへ適用した** → `osfs/`。`rm-guard`（PATH 前方に置く `rm` の
      置き換え）と `immutable.sh`（`chattr +i` の候補提示）。設置後に実測で確認済み——
      `rm` はゴミ箱経由になり、`rm -rf` でディレクトリごと入り、`trash-restore` で中身ごと
      戻り、`HARNESS_RM_REAL=1` はゴミ箱を経由せず本物の `rm` を呼ぶ
- [ ] `chattr +i` はまだ何も掛けていない。代償が重い項目ばかりなので保留（`immutable.sh status`）
- [x] **`ask` の件は上流へ報告済み。** ただし新規 issue ではない——同じ報告が既に 15 件以上
      上がっていたため、最も近い [#79356](https://github.com/anthropics/claude-code/issues/79356)
      へコメントした（[投稿](https://github.com/anthropics/claude-code/issues/79356#issuecomment-5157316941)）。
      あちらは Windows / PowerShell で報告され `platform:windows` ラベルが付いていたので、
      Linux / Bash / v2.1.220 でも再現することを対照実験ごと足した。顛末は
      [`docs/upstream-report-draft.md`](docs/upstream-report-draft.md)
- [ ] `session-harness` は初版のまま手付かず

## License

MIT。[LICENSE](LICENSE) を参照。
